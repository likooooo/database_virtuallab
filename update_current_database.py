#!/usr/bin/env python3
"""Ensure virtuallab_runtime via simdb, then run VlCatalogInspector.exe (WSL→Windows).

Source of truth for the exe is simulation_vl_plugin → published as product
``virtuallab_runtime`` / platform ``win-x86_64``. This script does not build or
keep a local C# fork; it downloads the same package other clients consume via
``ensure_runtime``, stages it under Windows %TEMP% (Fusion DLLs cannot load from
\\\\wsl$), and exports YAML back into this source tree.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

VL_DIR = Path(__file__).resolve().parent
HARNESS_ROOT = VL_DIR.parent
VL_INSTALL_DIR = r"C:\Program Files\Wyrowski Photonics\VirtualLab Fusion (7.5.0) Trial"
STAGING_NAME = "virtuallab_runtime"
VIRTUALLAB_PRODUCT = "virtuallab_runtime"
VIRTUALLAB_PLATFORM = "win-x86_64"
VIRTUALLAB_REF = "latest_trial"


def _require_wsl_host() -> None:
    if shutil.which("wslpath") is None or shutil.which("cmd.exe") is None:
        raise EnvironmentError("wslpath/cmd.exe required — run from WSL with Windows host")


def _win_temp() -> str:
    raw = subprocess.check_output(["cmd.exe", "/c", "echo %TEMP%"], text=True)
    win_temp = raw.strip().strip("\r")
    if not win_temp:
        raise RuntimeError("cannot resolve Windows %TEMP%")
    return win_temp


def _wslpath_u(win_path: str) -> Path:
    out = subprocess.check_output(["wslpath", "-u", win_path], text=True).strip()
    return Path(out)


def _wslpath_w(linux_path: Path) -> str:
    out = subprocess.check_output(["wslpath", "-w", str(linux_path)], text=True).strip()
    return out.replace("\\", "/")


def _ensure_tool_path() -> str:
    tool = os.environ.get("SIMULATION_TOOL_DATABASE")
    if tool is None or not str(tool).strip():
        raise RuntimeError("SIMULATION_TOOL_DATABASE is required")
    tool_root = str(Path(tool).expanduser().resolve())
    if tool_root not in sys.path:
        sys.path.insert(0, tool_root)
    if str(HARNESS_ROOT) not in sys.path:
        sys.path.insert(0, str(HARNESS_ROOT))
    return tool_root


def _ensure_virtuallab_cache(*, config: Path, remote: str) -> Path:
    _ensure_tool_path()
    from framework.config import ConfigError, load_config, ingest_host_port
    from clients.user.core import CommandCore
    from clients.user.runtime_package import ensure_runtime

    try:
        cfg = load_config(config.resolve(), remote=remote)
    except ConfigError as e:
        raise RuntimeError(str(e)) from e
    host, port = ingest_host_port(cfg["ingest"])
    print(
        f"vl: ensure_runtime {host}:{port} product={VIRTUALLAB_PRODUCT} "
        f"ref={VIRTUALLAB_REF} platform={VIRTUALLAB_PLATFORM}",
        flush=True,
    )
    sess = CommandCore(host, port).connect()
    try:
        info = ensure_runtime(
            sess,
            product=VIRTUALLAB_PRODUCT,
            ref=VIRTUALLAB_REF,
            platform=VIRTUALLAB_PLATFORM,
        )
    finally:
        sess.close()
    cache = Path(info["cache_dir"]).resolve()
    exe = cache / "VlCatalogInspector.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"VlCatalogInspector.exe missing under {cache}")
    print(
        f"vl: runtime cache={cache} content_sha256={info.get('content_sha256')} "
        f"version={info.get('version')}",
        flush=True,
    )
    return cache


def _stage_runtime(cache_linux: Path, staging_linux: Path) -> Path:
    """Copy unpacked package to a real Windows path (not \\\\wsl$)."""
    staging_linux.mkdir(parents=True, exist_ok=True)
    cmd = [
        "rsync",
        "-a",
        "--delete",
        f"{cache_linux}/",
        f"{staging_linux}/",
    ]
    subprocess.run(cmd, check=True)
    exe = staging_linux / "VlCatalogInspector.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"staged exe missing: {exe}")
    return exe


def _run_export(exe: Path, staging_linux: Path) -> None:
    if not Path("/mnt/c/Program Files/Wyrowski Photonics/VirtualLab Fusion (7.5.0) Trial").is_dir():
        raise FileNotFoundError(f"VL install dir missing: {VL_INSTALL_DIR}")
    out_linux = staging_linux / "export_out"
    if out_linux.is_dir():
        shutil.rmtree(out_linux)
    out_linux.mkdir(parents=True, exist_ok=True)
    out_win = _wslpath_w(out_linux)
    cmd = [
        str(exe),
        "--install-dir",
        VL_INSTALL_DIR,
        "--out",
        out_win,
    ]
    print("vl: running", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    for name in ("materials", "films", "geometries"):
        src = out_linux / name
        dst = VL_DIR / name
        if not src.is_dir():
            raise FileNotFoundError(f"export missing {src}")
        dst.mkdir(parents=True, exist_ok=True)
        for old in dst.rglob("*"):
            if old.is_file() and old.suffix.lower() in (".yml", ".yaml"):
                old.unlink()
        for sub in list(dst.iterdir()):
            if sub.is_dir():
                shutil.rmtree(sub)
        subprocess.run(["rsync", "-a", f"{src}/", f"{dst}/"], check=True)
    log_src = out_linux / "_export_log"
    if log_src.is_dir():
        log_dst = VL_DIR / "_export_log"
        if log_dst.is_dir():
            shutil.rmtree(log_dst)
        subprocess.run(["rsync", "-a", f"{log_src}/", f"{log_dst}/"], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--remote", required=True)
    args = ap.parse_args()
    try:
        _require_wsl_host()
        cache = _ensure_virtuallab_cache(config=args.config, remote=args.remote)
        win_temp = _win_temp()
        staging_win = win_temp.rstrip("\\/") + "\\" + STAGING_NAME
        if "\\wsl" in staging_win.lower() or "wsl.localhost" in staging_win.lower():
            raise RuntimeError(
                f"VL runtime staging must be a Windows path (not \\\\wsl$): {staging_win}"
            )
        staging_linux = _wslpath_u(staging_win)
        print(f"vl: staging {staging_win} -> {staging_linux}", flush=True)
        exe = _stage_runtime(cache, staging_linux)
        print(f"vl: exe {exe}", flush=True)
        _run_export(exe, staging_linux)
        print("vl: export done", flush=True)
        return 0
    except (EnvironmentError, FileNotFoundError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
