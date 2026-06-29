#!/usr/bin/env bash
# Orchestrate VirtualLab export from WSL via Windows SSH:
#   1. stage + scp PowerShell scripts to Windows temp dir
#   2. ssh + run export_materials.ps1 (reads VirtualLab catalog -> CSV + meta.json)
#   3. scp csv_export/ back to WSL
#   4. run update_current_database.py locally to convert CSV -> YAML
#
# Requires: OpenSSH client (WSL), OpenSSH Server on Windows, passwordless SSH or agent.
#
# Config: pass --config PATH (parent update_all supplies parent config.yaml).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_OUT="$SCRIPT_DIR"

# Discover Windows host IP for SSH from WSL (not 127.0.0.53 systemd stub).
detect_windows_host_ip() {
  local wsl_ip="" gw_ip="" lan_ip="" adapter="" line ip

  while IFS= read -r line; do
    line="${line//$'\r'/}"
    if [[ "$line" == *adapter* ]]; then
      adapter="$line"
    fi
    if [[ "$line" =~ IPv4[^:]*:[[:space:]]*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+) ]]; then
      ip="${BASH_REMATCH[1]}"
      if [[ "$adapter" == *WSL* ]]; then
        wsl_ip="$ip"
      fi
      if [[ "$ip" != 127.* && "$ip" != 169.254.* && "$ip" != 198.18.* \
            && "$adapter" != *VMware* && "$adapter" != *Loopback* ]]; then
        if [[ -z "$lan_ip" ]]; then
          lan_ip="$ip"
        fi
      fi
    fi
  done < <(cmd.exe /c "chcp 65001>nul & ipconfig" 2>/dev/null | sed 's/\r$//')

  gw_ip="$(ip route show default 2>/dev/null | awk '{print $3; exit}' || true)"

  if [[ -n "$wsl_ip" ]]; then
    echo "$wsl_ip"
  elif [[ -n "$gw_ip" && "$gw_ip" != 127.* ]]; then
    echo "$gw_ip"
  elif [[ -n "$lan_ip" ]]; then
    echo "$lan_ip"
  else
    echo ""
  fi
}

# OpenSSH scp on Windows: absolute /c/Users/USER/... lands under C:\Users\USER\c\Users\USER\...
# Use paths relative to the SSH user's home for scp; PowerShell needs C:/Users/USER/...
to_win_path() {
  local p="${1//\\//}"
  if [[ "$p" =~ ^/([a-zA-Z])/(.*) ]]; then
    printf '%s:/%s' "${BASH_REMATCH[1]^}" "${BASH_REMATCH[2]}"
  elif [[ "$p" =~ ^[A-Za-z]: ]]; then
    echo "$p"
  else
    echo "$p"
  fi
}

to_scp_path() {
  local p="${1//\\//}"
  local user="${2:-}"
  local rest=""

  if [[ "$p" =~ ^/([a-zA-Z])/(.*) ]]; then
    rest="${BASH_REMATCH[2]}"
  elif [[ "$p" =~ ^([A-Za-z]):/(.*) ]]; then
    rest="${BASH_REMATCH[2]}"
  else
    echo "$p"
    return 0
  fi

  if [[ -n "$user" && "$rest" == Users/"$user"/* ]]; then
    echo "${rest#Users/$user/}"
  elif [[ "$rest" == AppData/* ]]; then
    echo "$rest"
  else
    echo "/${rest}"
  fi
}

LIMIT=""
KEEP_REMOTE=0
CONFIG_PATH="${SIMULATION_DATABASE_CONFIG:-}"

if [[ -z "$CONFIG_PATH" || ! -f "$CONFIG_PATH" ]]; then
  for candidate in "$SCRIPT_DIR/../config.yaml" "$SCRIPT_DIR/../config.example.yaml"; do
    if [[ -f "$candidate" ]]; then
      CONFIG_PATH="$candidate"
      break
    fi
  done
fi

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Run VirtualLab catalog export on Windows (PowerShell) and convert CSV to YAML in WSL.

Options:
  --limit N         Export at most N materials (passed to update_current_database.py)
  --config PATH     Config YAML (virtuallab.* and windows_ssh.*)
  --keep-remote     Do not delete remote staging directory after sync
  -h, --help        Show this help

Environment:
  WINDOWS_SSH_HOST, WINDOWS_SSH_USER, WINDOWS_REMOTE_DIR, VIRTUALLAB_DIR
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit)
      LIMIT="$2"
      shift 2
      ;;
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --keep-remote)
      KEEP_REMOTE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

load_config() {
  if [[ ! -f "$CONFIG_PATH" ]]; then
    return 0
  fi
  # shellcheck disable=SC2046
  eval "$(
    python3 - "$CONFIG_PATH" <<'PY'
import sys
from pathlib import Path
import yaml

path = Path(sys.argv[1])
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
vl = cfg.get("virtuallab") or {}
ssh = vl.get("windows_ssh") or {}

def emit(name, value):
    if value is None or value == "":
        return
    print(f"export {name}={value!r}")

def wsl_path_to_windows(path: str) -> str:
    import re
    s = path.replace("\\\\", "/").replace("\\", "/")
    m = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", s)
    if m:
        drive = m.group(1).upper()
        rest = (m.group(2) or "").replace("/", "\\\\")
        return f"{drive}:\\\\{rest}" if rest else f"{drive}:\\\\"
    return path

vl_dir = vl.get("virtuallab_dir")
if isinstance(vl_dir, str) and vl_dir.replace("\\\\", "/").startswith("/mnt/"):
    vl_dir = wsl_path_to_windows(vl_dir)

emit("VIRTUALLAB_DIR", vl_dir)
emit("WINDOWS_SSH_HOST", ssh.get("host"))
emit("WINDOWS_SSH_USER", ssh.get("user"))
emit("WINDOWS_REMOTE_DIR", ssh.get("remote_dir"))
PY
  )"
}

load_config

WIN_USER="${WINDOWS_SSH_USER:-${USER}}"
if [[ -z "${WINDOWS_SSH_HOST:-}" || "${WINDOWS_SSH_HOST}" == "auto" ]]; then
  WINDOWS_SSH_HOST="$(detect_windows_host_ip)"
  if [[ -n "${WINDOWS_SSH_HOST}" ]]; then
    echo "==> Detected Windows host IP via cmd.exe ipconfig: $WINDOWS_SSH_HOST"
  fi
fi
WIN_HOST="${WINDOWS_SSH_HOST:-}"
_remote_raw="${WINDOWS_REMOTE_DIR:-/c/Users/${WIN_USER}/AppData/Local/Temp/virtuallab_export}"
REMOTE_DIR_SCP="$(to_scp_path "$_remote_raw" "$WIN_USER")"
REMOTE_DIR_WIN="$(to_win_path "$_remote_raw")"
VL_DIR="${VIRTUALLAB_DIR:-C:\\Program Files\\Wyrowski Photonics\\VirtualLab Fusion (7.5.0) Trial}"
VL_DIR_PS="${VL_DIR//\\//}"

if [[ -z "$WIN_HOST" ]]; then
  echo "error: WINDOWS_SSH_HOST not set and could not detect Windows host IP via cmd.exe ipconfig" >&2
  echo "hint: set windows_ssh.host in config.yaml or export WINDOWS_SSH_HOST=<ip>" >&2
  exit 1
fi

SSH_TARGET="${WIN_USER}@${WIN_HOST}"
REMOTE_PS1_WIN="${REMOTE_DIR_WIN}/run_remote_export.ps1"
REMOTE_CSV="${REMOTE_DIR_SCP}/csv_export"

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)
SCP_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)

STAGE="$(mktemp -d)"
CACHE_ROOT="$SCRIPT_DIR/.cache"
mkdir -p "$CACHE_ROOT"
CSV_STAGING="$(mktemp -d "$CACHE_ROOT/vl_csv_export.XXXXXX")"

cleanup_stage() { rm -rf "$STAGE"; }
cleanup_csv_staging() { rm -rf "$CSV_STAGING"; }
trap 'cleanup_stage; cleanup_csv_staging' EXIT

echo "==> Windows SSH target: $SSH_TARGET"
echo "==> Remote staging (scp): $REMOTE_DIR_SCP"
echo "==> Remote staging (ps):  $REMOTE_DIR_WIN"
echo "==> VirtualLab install: $VL_DIR"
echo "==> Local YAML output: $LOCAL_OUT"
echo "==> WSL CSV staging:   $CSV_STAGING"

mkdir -p "$STAGE/simulation_database/vl"
cp "$SCRIPT_DIR/export_materials.ps1" \
   "$SCRIPT_DIR/run_remote_export.ps1" \
   "$STAGE/simulation_database/vl/"
cp "$SCRIPT_DIR/run_remote_export.ps1" "$STAGE/"

echo "==> Checking SSH connectivity..."
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "echo ok" >/dev/null

echo "==> Preparing remote directory..."
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "powershell.exe -NoProfile -Command \"Remove-Item -LiteralPath '${REMOTE_DIR_WIN}' -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force -Path '${REMOTE_DIR_WIN}' | Out-Null\""

echo "==> Uploading export payload..."
scp "${SCP_OPTS[@]}" -r "$STAGE/." "${SSH_TARGET}:${REMOTE_DIR_SCP}/"

LIMIT_ARG=""
if [[ -n "$LIMIT" ]]; then
  LIMIT_ARG="-Limit $LIMIT"
fi

echo "==> Running export on Windows (this may take several minutes)..."
REMOTE_CMD="powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"${REMOTE_PS1_WIN}\" -VirtuallabDir \"${VL_DIR_PS}\" -PayloadRoot \"${REMOTE_DIR_WIN}\" ${LIMIT_ARG}"
if ! ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "$REMOTE_CMD"; then
  echo "error: remote export failed on Windows" >&2
  exit 1
fi

echo "==> Downloading csv_export/ from Windows to WSL staging..."
scp "${SCP_OPTS[@]}" -r "${SSH_TARGET}:${REMOTE_CSV}" "$CSV_STAGING/"

CSV_SOURCE="$CSV_STAGING/csv_export/materials"
INDEX_CSV="$CSV_STAGING/csv_export/materials_export/index.csv"
if [[ ! -d "$CSV_SOURCE" ]]; then
  echo "error: remote CSV export missing: $CSV_SOURCE" >&2
  exit 1
fi

CSV_COUNT="$(find "$CSV_SOURCE" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
echo "==> Downloaded $CSV_COUNT material CSV dirs"

echo "==> Converting CSV to YAML in WSL..."
EXPORT_ARGS=(
  "$SCRIPT_DIR/update_current_database.py"
  --csv-source "$CSV_SOURCE"
  --index-csv "$INDEX_CSV"
  --output "$LOCAL_OUT"
)
if [[ -n "$LIMIT" ]]; then
  EXPORT_ARGS+=(--limit "$LIMIT")
fi
if ! python3 "${EXPORT_ARGS[@]}"; then
  echo "error: CSV to YAML conversion failed" >&2
  exit 1
fi

if [[ "$KEEP_REMOTE" -eq 0 ]]; then
  echo "==> Cleaning remote staging directory..."
  ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "powershell.exe -NoProfile -Command \"Remove-Item -LiteralPath '${REMOTE_DIR_WIN}' -Recurse -Force -ErrorAction SilentlyContinue\""
fi

MAT_COUNT="$(find "$LOCAL_OUT/materials" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
LOG_COUNT="$(find "$LOCAL_OUT/logs" -name '*.log' 2>/dev/null | wc -l)"
echo "==> Done: $MAT_COUNT material dirs, $LOG_COUNT log files -> $LOCAL_OUT"
