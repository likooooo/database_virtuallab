#!/usr/bin/env python3
"""Build VlCatalogInspector on Windows via WSL interop and export live YAML.

Aligns with simulation_baseline_tools/.../fmm_mp.sh vl-build:
  fixed dotnet.exe + %TEMP% staging (not \\\\wsl$) + sync + run exe.
YAML is written under Windows TEMP then rsync'd back to this source tree.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

VL_DIR = Path(__file__).resolve().parent
TOOLS_SRC = VL_DIR / "tools" / "VlCatalogInspector"
DOTNET_LINUX = Path("/mnt/c/Program Files/dotnet/dotnet.exe")
VL_INSTALL_DIR = r"C:\Program Files\Wyrowski Photonics\VirtualLab Fusion (7.5.0) Trial"
STAGING_NAME = "VlCatalogInspector"


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


def _stage_sync(staging_linux: Path) -> None:
    staging_linux.mkdir(parents=True, exist_ok=True)
    if TOOLS_SRC.resolve() == staging_linux.resolve():
        return
    cmd = [
        "rsync",
        "-a",
        "--delete",
        "--exclude",
        "bin",
        "--exclude",
        "obj",
        "--exclude",
        ".git",
        f"{TOOLS_SRC}/",
        f"{staging_linux}/",
    ]
    subprocess.run(cmd, check=True)


def _build(staging_linux: Path) -> Path:
    if not DOTNET_LINUX.is_file():
        raise FileNotFoundError(f"Windows .NET SDK not found at {DOTNET_LINUX}")
    csproj = staging_linux / "VlCatalogInspector.csproj"
    if not csproj.is_file():
        raise FileNotFoundError(f"missing csproj: {csproj}")
    csproj_win = _wslpath_w(csproj)
    subprocess.run([str(DOTNET_LINUX), "build", csproj_win, "-c", "Release"], check=True)
    staging_bin = staging_linux / "bin"
    exe = staging_bin / "VlCatalogInspector.exe"
    if not exe.is_file():
        matches = list(staging_linux.glob("**/VlCatalogInspector.exe"))
        if not matches:
            raise FileNotFoundError(f"build finished but exe not found under {staging_linux}")
        exe = matches[0]
        staging_bin = exe.parent
    dest_bin = TOOLS_SRC / "bin"
    if dest_bin.resolve() != staging_bin.resolve():
        if dest_bin.is_dir():
            shutil.rmtree(dest_bin)
        subprocess.run(["rsync", "-a", f"{staging_bin}/", f"{dest_bin}/"], check=True)
    # Run from Windows staging so VirtualLabAPI.dll resolves beside the exe.
    return staging_bin / "VlCatalogInspector.exe"


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
        # Replace YAML trees only; keep sibling README.md under each kind root.
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
        skip = log_src / "geo_skip.txt"
        if skip.is_file():
            notes = TOOLS_SRC / "notes"
            notes.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skip, notes / "geo_skip.txt")


def main() -> int:
    try:
        _require_wsl_host()
        if not TOOLS_SRC.is_dir():
            raise FileNotFoundError(f"tools missing: {TOOLS_SRC}")
        win_temp = _win_temp()
        staging_win = win_temp.rstrip("\\/") + "\\" + STAGING_NAME
        if "\\wsl" in staging_win.lower() or "wsl.localhost" in staging_win.lower():
            raise RuntimeError(f"VL build staging must be a Windows path (not \\\\wsl$): {staging_win}")
        staging_linux = _wslpath_u(staging_win)
        print(f"vl: staging {staging_win} -> {staging_linux}", flush=True)
        _stage_sync(staging_linux)
        exe = _build(staging_linux)
        print(f"vl: built {exe}", flush=True)
        _run_export(exe, staging_linux)
        print("vl: export done", flush=True)
        return 0
    except (EnvironmentError, FileNotFoundError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
