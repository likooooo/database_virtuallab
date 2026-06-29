#!/usr/bin/env python3
"""Export VirtualLab materials to refractiveindex.info-compatible YAML."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from scipy.interpolate import CubicSpline

_VL_ROOT = Path(__file__).resolve().parent
if str(_VL_ROOT) not in sys.path:
    sys.path.insert(0, str(_VL_ROOT))

from vl_catalog import SampledCurve, VlMaterial, is_windows, iter_materials
from vl_formulas import map_dispersion_formula
from vl_material_layout import material_out_yml, stale_flat_yml


# --- inlined helpers (no parent-repo dependency) ---


class MaterialLogger:
    def __init__(self, name: str, log_dir: Path | None = None) -> None:
        self.name = name
        self.warnings: list[str] = []
        self.log_dir = log_dir

    def warn(self, message: str) -> None:
        line = f"[{self.name}] {message}"
        self.warnings.append(message)
        print(line, file=sys.stderr)

    def flush(self) -> None:
        if self.log_dir is None:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self.name.replace("/", "_")
        log_path = self.log_dir / f"{safe_name}.log"
        if not self.warnings:
            if log_path.is_file():
                log_path.unlink()
            return
        log_path.write_text("\n".join(self.warnings) + "\n", encoding="utf-8")


def k_from_alpha_on_wl_um(wl_um: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    wl_um_arr = np.asarray(wl_um, dtype=float)
    alpha_arr = np.asarray(alpha, dtype=float)
    return alpha_arr * wl_um_arr * 1e-6 / (4.0 * np.pi)


def read_oghma_csv(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict[str, Any] = {}
    if lines and lines[0].startswith("#"):
        match = re.search(r"\{(.+)\}", lines[0])
        if match:
            raw = "{" + match.group(1) + "}"
            raw = re.sub(r":\s*nan\b", ": null", raw, flags=re.IGNORECASE)
            raw = re.sub(r":\s*-?inf\b", ": null", raw, flags=re.IGNORECASE)
            meta = json.loads(raw)
    xs: list[float] = []
    ys: list[float] = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [float(x) for x in line.replace(",", " ").split()]
        if len(parts) < 2:
            continue
        xs.append(parts[0])
        ys.append(parts[1])
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float), meta


def oghma_axis_to_um(values: np.ndarray, meta: dict[str, Any], *, axis: str = "y") -> np.ndarray:
    mul_key = "y_mul" if axis == "y" else "x_mul"
    units_key = "y_units" if axis == "y" else "x_units"
    fallback_mul = meta.get("y_mul" if axis == "x" else "x_mul", 1.0)
    fallback_units = meta.get("y_units" if axis == "x" else "x_units", "m")
    mul = float(meta.get(mul_key, fallback_mul))
    units = str(meta.get(units_key, fallback_units))
    pos = values * mul if mul != 1.0 else values
    if units == "nm":
        return np.asarray(pos, dtype=float) * 1e-3
    if units == "um":
        return np.asarray(pos, dtype=float)
    return np.asarray(pos, dtype=float) * 1e6


def read_tabulated_xy_um(path: Path) -> tuple[np.ndarray, np.ndarray]:
    wl_raw, val, meta = read_oghma_csv(path)
    if meta:
        wl_um = oghma_axis_to_um(wl_raw, meta, axis="y")
    else:
        wl_raw_arr = np.asarray(wl_raw, dtype=float)
        if wl_raw_arr.size == 0:
            wl_um = wl_raw_arr
        elif np.nanmax(wl_raw_arr) < 1e-2:
            wl_um = wl_raw_arr * 1e6
        else:
            wl_um = wl_raw_arr
    val_arr = np.asarray(val, dtype=float)
    order = np.argsort(wl_um)
    return wl_um[order], val_arr[order]


def read_material_nk_table(root: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_x, n_y, n_meta = read_oghma_csv(root / "n.csv")
    wl_um = oghma_axis_to_um(n_x, n_meta, axis="y")
    n_vals = np.asarray(n_y, dtype=float)
    alpha_path = root / "alpha.csv"
    if alpha_path.is_file():
        a_x, a_y, a_meta = read_oghma_csv(alpha_path)
        wl_alpha_um = oghma_axis_to_um(a_x, a_meta, axis="y")
        alpha_vals = np.asarray(a_y, dtype=float)
    else:
        wl_alpha_um = np.array([], dtype=float)
        alpha_vals = np.array([], dtype=float)
    n_order = np.argsort(wl_um)
    wl_um = wl_um[n_order]
    n_vals = n_vals[n_order]
    if wl_alpha_um.size:
        alpha_order = np.argsort(wl_alpha_um)
        wl_alpha_um = wl_alpha_um[alpha_order]
        alpha_vals = alpha_vals[alpha_order]
    return wl_um, n_vals, wl_alpha_um, alpha_vals


def _dedupe_sorted(wl: np.ndarray, vals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if wl.size == 0:
        return wl, vals
    order = np.argsort(wl)
    wl = wl[order]
    vals = vals[order]
    unique_wl: list[float] = []
    unique_vals: list[float] = []
    for w, v in zip(wl, vals):
        if unique_wl and np.isclose(w, unique_wl[-1]):
            unique_vals[-1] = float(v)
        else:
            unique_wl.append(float(w))
            unique_vals.append(float(v))
    return np.asarray(unique_wl, dtype=float), np.asarray(unique_vals, dtype=float)


def cubic_interp_extrap(x_new: np.ndarray, x_src: np.ndarray, y_src: np.ndarray) -> np.ndarray:
    if x_src.size == 0:
        return np.zeros_like(x_new, dtype=float)
    if x_src.size == 1:
        return np.full_like(x_new, float(y_src[0]), dtype=float)
    spline = CubicSpline(x_src, y_src, extrapolate=True)
    return np.asarray(spline(x_new), dtype=float)


def merge_n_alpha_to_nk(
    wl_n_um: np.ndarray,
    n_vals: np.ndarray,
    wl_alpha_um: np.ndarray,
    alpha_vals: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    wl_n_um, n_vals = _dedupe_sorted(np.asarray(wl_n_um, dtype=float), np.asarray(n_vals, dtype=float))
    if wl_alpha_um.size:
        wl_alpha_um, alpha_vals = _dedupe_sorted(
            np.asarray(wl_alpha_um, dtype=float),
            np.asarray(alpha_vals, dtype=float),
        )
    grids = [wl_n_um]
    if wl_alpha_um.size:
        grids.append(wl_alpha_um)
    wl_union = np.unique(np.concatenate(grids))
    n_on_union = cubic_interp_extrap(wl_union, wl_n_um, n_vals)
    if wl_alpha_um.size:
        alpha_on_union = cubic_interp_extrap(wl_union, wl_alpha_um, alpha_vals)
    else:
        alpha_on_union = np.zeros_like(wl_union, dtype=float)
    k_on_union = k_from_alpha_on_wl_um(wl_union, alpha_on_union)
    return wl_union, n_on_union, k_on_union


def validate_tabulated_nk(
    wl_um: np.ndarray,
    n_vals: np.ndarray,
    k_vals: np.ndarray,
    log: MaterialLogger,
) -> None:
    if wl_um.size == 0:
        log.warn("empty wavelength grid")
        return
    if not np.all(np.diff(wl_um) > 0):
        log.warn("wavelength grid is not strictly increasing after dedupe")
    if np.any(~np.isfinite(n_vals)):
        log.warn("non-finite n values present")
    if np.any(~np.isfinite(k_vals)):
        log.warn("non-finite k values present")
    if np.any(n_vals < 0):
        log.warn("negative n values present")
    if np.any(k_vals < 0):
        log.warn("negative k values present")


def _format_value(value: float) -> str:
    if value == 0.0:
        return "0"
    abs_val = abs(value)
    if abs_val >= 1e-3 and abs_val < 1e4:
        return f"{value:.6g}"
    return f"{value:.6E}".replace("e", "E")


def _format_coeff(value: float) -> str:
    return "0" if value == 0.0 else _format_value(value)


def _block_scalar(key: str, text: str) -> str:
    if not text.strip():
        return f"{key}: |\n"
    lines = text.rstrip("\n").split("\n")
    body = "\n".join(f"    {line}" for line in lines)
    return f"{key}: |\n{body}\n"


def _render_data_blocks(blocks: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = ["DATA:"]
    for block in blocks:
        btype = block["type"]
        lines.append(f"  - type: {btype}")
        if btype.startswith("formula"):
            lines.append(f"    wavelength_range: {block['wl_min']:.6g} {block['wl_max']:.6g}")
            coeff_text = " ".join(_format_coeff(c) for c in block["coefficients"])
            lines.append(f"    coefficients: {coeff_text}")
        elif btype.startswith("tabulated"):
            lines.append("    data: |")
            for row in block["rows"]:
                if len(row) == 2:
                    w, v = row
                    lines.append(f"        {_format_value(w)} {_format_value(v)}")
                else:
                    w, n, k = row
                    lines.append(
                        f"        {_format_value(w)} {_format_value(n)} {_format_value(k)}"
                    )
    return lines


def write_material_yml(
    path: Path,
    data_blocks: list[dict[str, Any]],
    *,
    references: str = "",
    comments: str = "",
    conditions: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        _block_scalar("REFERENCES", references),
        _block_scalar("COMMENTS", comments),
        _block_scalar("CONDITIONS", conditions),
        *_render_data_blocks(data_blocks),
        "",
    ]
    path.write_text("\n".join(parts), encoding="utf-8")


def tabulated_nk_block(wl_um: np.ndarray, n_vals: np.ndarray, k_vals: np.ndarray) -> dict[str, Any]:
    wl_um = np.asarray(wl_um, dtype=float)
    n_vals = np.asarray(n_vals, dtype=float)
    k_vals = np.asarray(k_vals, dtype=float)
    rows = [(float(w), float(n), float(k)) for w, n, k in zip(wl_um, n_vals, k_vals)]
    return {"type": "tabulated nk", "rows": rows}


def tabulated_k_block(wl_um: np.ndarray, k_vals: np.ndarray) -> dict[str, Any]:
    wl_um = np.asarray(wl_um, dtype=float)
    k_vals = np.asarray(k_vals, dtype=float)
    rows = [(float(w), float(k)) for w, k in zip(wl_um, k_vals)]
    return {"type": "tabulated k", "rows": rows}


def write_tabulated_nk_yml(
    path: Path,
    wl_um: np.ndarray,
    n_vals: np.ndarray,
    k_vals: np.ndarray,
    *,
    references: str = "",
    comments: str = "",
    conditions: str = "",
) -> None:
    write_material_yml(
        path,
        [tabulated_nk_block(wl_um, n_vals, k_vals)],
        references=references,
        comments=comments,
        conditions=conditions,
    )


def write_formula_yml(
    path: Path,
    formula_type: int,
    wl_min: float,
    wl_max: float,
    coefficients: list[float],
    *,
    extra_blocks: list[dict[str, Any]] | None = None,
    references: str = "",
    comments: str = "",
    conditions: str = "",
) -> None:
    blocks: list[dict[str, Any]] = [
        {
            "type": f"formula {formula_type}",
            "wl_min": wl_min,
            "wl_max": wl_max,
            "coefficients": coefficients,
        }
    ]
    if extra_blocks:
        blocks.extend(extra_blocks)
    write_material_yml(
        path,
        blocks,
        references=references,
        comments=comments,
        conditions=conditions,
    )


def relocate_flat_yml(materials_root: Path) -> int:
    """Move legacy flat ``materials/*.yml`` into oghma-aligned subdirectories."""
    moved = 0
    for src in sorted(materials_root.glob("*.yml")):
        dest = material_out_yml(materials_root, src.stem)
        if src.resolve() == dest.resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file():
            src.unlink()
        else:
            shutil.move(str(src), str(dest))
        moved += 1
    return moved

DEFAULT_VL_DIR = Path(
    r"C:\Program Files\Wyrowski Photonics\VirtualLab Fusion (7.5.0) Trial"
)


def _normalize_slashes(path: str) -> str:
    return path.replace("\\", "/")


def windows_path_to_wsl(path: str) -> str:
    """``C:\\Foo\\Bar`` → ``/mnt/c/Foo/Bar``."""
    s = _normalize_slashes(path.strip())
    if re.match(r"^[A-Za-z]:", s):
        drive = s[0].lower()
        rest = s[2:].lstrip("/")
        return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"
    return s


def wsl_path_to_windows(path: str) -> str:
    """``/mnt/c/Foo/Bar`` → ``C:\\Foo\\Bar``."""
    s = _normalize_slashes(path.strip())
    m = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", s)
    if m:
        drive = m.group(1).upper()
        rest = (m.group(2) or "").replace("/", "\\")
        return f"{drive}:\\{rest}" if rest else f"{drive}:\\"
    return path


def virtuallab_dir_candidates(raw: str | Path) -> list[Path]:
    """Windows and WSL mount paths are dual; derive both and try Windows form first."""
    s = str(raw).strip()
    norm = _normalize_slashes(s)
    if re.match(r"^[A-Za-z]:", norm):
        win, wsl = s, windows_path_to_wsl(s)
    elif norm.startswith("/mnt/"):
        wsl, win = norm, wsl_path_to_windows(norm)
    else:
        return [Path(s)]
    seen: set[str] = set()
    out: list[Path] = []
    for p in (win, wsl):
        key = _normalize_slashes(str(p)).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(p))
    return out


def resolve_virtuallab_dir(raw: str | Path) -> Path:
    """Return first existing candidate (Windows path, then WSL mount)."""
    tried: list[str] = []
    for cand in virtuallab_dir_candidates(raw):
        tried.append(str(cand))
        if cand.is_dir():
            return cand.resolve()
    raise FileNotFoundError(
        "VirtualLab install directory not found; tried:\n  " + "\n  ".join(tried)
    )


def _find_database_config() -> Path | None:
    env = os.environ.get("SIMULATION_DATABASE_CONFIG", "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p
    for candidate in (_VL_ROOT.parent / "config.yaml", _VL_ROOT.parent / "config.example.yaml"):
        if candidate.is_file():
            return candidate
    return None


def run_wsl_remote_export(limit: int | None) -> int:
    """scp ps1 → Windows CSV → WSL staging → YAML (see export_via_windows.sh)."""
    script = _VL_ROOT / "export_via_windows.sh"
    if not script.is_file():
        print(f"error: {script} not found", file=sys.stderr)
        return 1
    cmd = ["bash", str(script)]
    config = _find_database_config()
    if config:
        cmd.extend(["--config", str(config)])
    if limit is not None:
        cmd.extend(["--limit", str(limit)])
    print("vl: WSL pipeline — scp ps1 to Windows, fetch CSV to staging, export YAML", file=sys.stderr)
    return subprocess.run(cmd, cwd=_VL_ROOT.parent, check=False).returncode


def load_index_names(index_csv: Path) -> dict[str, str]:
    """Map dir_name -> original VirtualLab name."""
    if not index_csv.is_file():
        return {}
    mapping: dict[str, str] = {}
    with open(index_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dir_name = row.get("dir_name") or row.get("directory") or ""
            original = row.get("original_name") or row.get("name") or ""
            if dir_name:
                mapping[dir_name] = original or dir_name
    return mapping


def _drop_nonfinite(
    wl_um: np.ndarray,
    vals: np.ndarray,
    log: MaterialLogger,
    label: str,
) -> tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(wl_um) & np.isfinite(vals)
    dropped = int(wl_um.size - mask.sum())
    if dropped:
        log.warn(f"dropped {dropped} non-finite {label} point(s)")
    return wl_um[mask], vals[mask]


def _finite_sampled(curve) -> tuple[np.ndarray, np.ndarray] | None:
    if curve is None or curve.wl_m.size == 0:
        return None
    wl_um = curve.wl_m * 1e6
    vals = curve.values.astype(float)
    mask = np.isfinite(wl_um) & np.isfinite(vals)
    if not mask.any():
        return None
    return wl_um[mask], vals[mask]


def _absorption_k(
    mat: VlMaterial,
    log: MaterialLogger,
    wl_ref: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (wl_um, k) from sampled alpha or constant absorption."""
    alpha = _finite_sampled(mat.sampled_alpha)
    if alpha is not None:
        wl_um, alpha_vals = alpha
        k_vals = k_from_alpha_on_wl_um(wl_um, alpha_vals)
        return wl_um, k_vals

    if mat.constant_absorption > 0.0:
        if wl_ref is not None and wl_ref.size:
            wl_um = wl_ref
        else:
            wl_um = np.linspace(mat.wl_min_um, mat.wl_max_um, 221)
        k_vals = k_from_alpha_on_wl_um(wl_um, np.full(wl_um.shape, mat.constant_absorption))
        log.warn(
            f"using constant absorption {mat.constant_absorption} m^-1 on default wavelength grid"
        )
        return wl_um, k_vals

    return None


def _remove_legacy_material_dir(out_yml: Path) -> None:
    """Remove pre-flatten layout ``materials/{name}/`` if it still exists."""
    legacy_dir = out_yml.parent / out_yml.stem
    if legacy_dir.is_dir() and legacy_dir != out_yml.parent:
        shutil.rmtree(legacy_dir)


def _remove_stale_material_yml(materials_out: Path, dir_name: str, out_yml: Path) -> None:
    """Drop legacy flat ``materials/{dir_name}.yml`` after writing nested layout."""
    stale = stale_flat_yml(materials_out, dir_name)
    if stale.is_file() and stale.resolve() != out_yml.resolve():
        stale.unlink()


def _comment_lines(mat: VlMaterial, extra: list[str] | None = None) -> str:
    lines = [f"VirtualLab material: {mat.name}"]
    if mat.dispersion_formula == "SampledDispersion":
        lines.append(
            "Dispersion from VirtualLab SampledRefractiveIndex table; "
            "parameters field ignored (placeholder)."
        )
    if extra:
        lines.extend(extra)
    return "\n".join(lines)


def export_vl_material(mat: VlMaterial, out_yml: Path, log_dir: Path) -> bool:
    log = MaterialLogger(mat.dir_name, log_dir)
    comment_extra: list[str] = []

    try:
        n_sample = _finite_sampled(mat.sampled_n)
        k_sample = _absorption_k(mat, log)

        # --- Path 1: sampled n (includes SampledDispersion) ---
        if n_sample is not None:
            wl_n, n_vals = n_sample
            wl_alpha = np.array([], dtype=float)
            alpha_vals = np.array([], dtype=float)
            if mat.sampled_alpha is not None and mat.sampled_alpha.wl_m.size:
                wl_alpha = mat.sampled_alpha.wl_m * 1e6
                alpha_vals = mat.sampled_alpha.values.astype(float)
                wl_alpha, alpha_vals = _drop_nonfinite(wl_alpha, alpha_vals, log, "alpha")

            if wl_alpha.size and wl_alpha.size != wl_n.size:
                log.warn(
                    f"n grid ({wl_n.size} pts) and alpha grid ({wl_alpha.size} pts) differ; "
                    "using wavelength union with cubic interpolation"
                )

            wl_um, n_out, k_out = merge_n_alpha_to_nk(wl_n, n_vals, wl_alpha, alpha_vals)
            validate_tabulated_nk(wl_um, n_out, k_out, log)

            _remove_legacy_material_dir(out_yml)
            out_yml.parent.mkdir(parents=True, exist_ok=True)
            write_tabulated_nk_yml(
                out_yml,
                wl_um,
                n_out,
                k_out,
                comments=_comment_lines(mat, comment_extra),
            )
            log.flush()
            return True

        # --- SampledDispersion without valid sampled n ---
        if mat.dispersion_formula == "SampledDispersion":
            log.warn("SampledDispersion but no valid SampledRefractiveIndex data")
            log.flush()
            return False

        # --- Path 2: formula dispersion ---
        ri = map_dispersion_formula(mat.dispersion_formula, mat.parameters)
        if ri is None:
            log.warn(f"unsupported dispersion formula: {mat.dispersion_formula}")
            log.flush()
            return False

        comment_extra.append(ri.note)
        extra_blocks = []
        if k_sample is not None:
            wl_k, k_vals = k_sample
            extra_blocks.append(tabulated_k_block(wl_k, k_vals))
            comment_extra.append(
                "Absorption: tabulated k from VirtualLab sampled alpha "
                "(or constant absorption converted alpha->k)."
            )
        elif mat.absorption_formula == "Sampled":
            log.warn("absorption_formula=Sampled but no valid absorption data exported")
            comment_extra.append(
                "Warning: absorption_formula=Sampled but no valid absorption table found."
            )

        _remove_legacy_material_dir(out_yml)
        out_yml.parent.mkdir(parents=True, exist_ok=True)
        write_formula_yml(
            out_yml,
            ri.formula_type,
            mat.wl_min_um,
            mat.wl_max_um,
            ri.coefficients,
            extra_blocks=extra_blocks or None,
            comments=_comment_lines(mat, comment_extra),
        )
        log.flush()
        return True

    except Exception as exc:
        log.warn(f"export failed: {exc}")
        log.flush()
        return False


def load_material_meta(src_dir: Path) -> dict | None:
    meta_path = src_dir / "meta.json"
    if not meta_path.is_file():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8-sig"))


def material_from_csv_meta(
    src_dir: Path,
    meta: dict,
    original_name: str,
) -> VlMaterial:
    """Build VlMaterial from PS1-exported meta.json + optional CSV tables."""
    sampled_n = None
    if meta.get("has_sampled_n") and (src_dir / "n.csv").is_file():
        wl_um, n_vals = read_tabulated_xy_um(src_dir / "n.csv")
        mask = np.isfinite(wl_um) & np.isfinite(n_vals)
        if mask.any():
            sampled_n = SampledCurve(wl_m=wl_um[mask] * 1e-6, values=n_vals[mask])

    sampled_alpha = None
    if (src_dir / "alpha.csv").is_file():
        wl_um, alpha_vals = read_tabulated_xy_um(src_dir / "alpha.csv")
        mask = np.isfinite(wl_um) & np.isfinite(alpha_vals)
        if mask.any():
            sampled_alpha = SampledCurve(wl_m=wl_um[mask] * 1e-6, values=alpha_vals[mask])

    params = [float(x) for x in meta.get("parameters", [])]
    return VlMaterial(
        name=original_name,
        dir_name=src_dir.name,
        dispersion_formula=str(meta.get("dispersion_formula", "")),
        absorption_formula=str(meta.get("absorption_formula", "")),
        parameters=params,
        constant_absorption=float(meta.get("constant_absorption", 0.0)),
        sampled_n=sampled_n,
        sampled_alpha=sampled_alpha,
        wl_min_um=float(meta.get("wl_min_um", 0.3)),
        wl_max_um=float(meta.get("wl_max_um", 2.5)),
    )


def export_material_csv(
    src_dir: Path,
    out_yml: Path,
    original_name: str,
    log_dir: Path,
) -> bool:
    """CSV export path: meta.json + optional n.csv/alpha.csv from Windows PS1."""
    meta = load_material_meta(src_dir)
    if meta is not None:
        mat = material_from_csv_meta(src_dir, meta, original_name)
        return export_vl_material(mat, out_yml, log_dir)

    # Legacy: tabulated n.csv only (no formula metadata).
    log = MaterialLogger(src_dir.name, log_dir)
    try:
        wl_n, n_vals, wl_alpha, alpha_vals = read_material_nk_table(src_dir)
        wl_n, n_vals = _drop_nonfinite(wl_n, n_vals, log, "n")
        if wl_alpha.size:
            wl_alpha, alpha_vals = _drop_nonfinite(wl_alpha, alpha_vals, log, "alpha")
        if wl_n.size == 0:
            log.warn("n.csv has no data points")
            log.flush()
            return False

        wl_um, n_out, k_out = merge_n_alpha_to_nk(wl_n, n_vals, wl_alpha, alpha_vals)
        validate_tabulated_nk(wl_um, n_out, k_out, log)

        _remove_legacy_material_dir(out_yml)
        out_yml.parent.mkdir(parents=True, exist_ok=True)
        write_tabulated_nk_yml(
            out_yml,
            wl_um,
            n_out,
            k_out,
            comments=f"VirtualLab material: {original_name}\nExported from pre-exported CSV.",
        )
        log.flush()
        return True
    except Exception as exc:
        log.warn(f"export failed: {exc}")
        log.flush()
        return False


def find_material_dirs(csv_source: Path) -> list[Path]:
    dirs: list[Path] = []
    for p in csv_source.iterdir():
        if not p.is_dir():
            continue
        if (p / "meta.json").is_file() or (p / "n.csv").is_file():
            dirs.append(p)
    return sorted(dirs)


def export_from_catalog(
    install_dir: Path,
    output: Path,
    log_dir: Path,
    limit: int | None,
) -> tuple[int, int]:
    materials = iter_materials(install_dir)
    if limit is not None:
        materials = materials[: max(limit, 0)]

    materials_out = output / "materials"
    ok = fail = 0
    for mat in materials:
        out_yml = material_out_yml(materials_out, mat.dir_name)
        if export_vl_material(mat, out_yml, log_dir):
            _remove_stale_material_yml(materials_out, mat.dir_name, out_yml)
            ok += 1
        else:
            fail += 1
    return ok, fail


def export_from_csv(
    csv_source: Path,
    index_csv: Path,
    output: Path,
    log_dir: Path,
    limit: int | None,
) -> tuple[int, int]:
    name_map = load_index_names(index_csv)
    material_dirs = find_material_dirs(csv_source)
    if limit is not None:
        material_dirs = material_dirs[: max(limit, 0)]

    materials_out = output / "materials"
    ok = fail = 0
    for src_dir in material_dirs:
        original = name_map.get(src_dir.name, src_dir.name)
        out_yml = material_out_yml(materials_out, src_dir.name)
        if export_material_csv(src_dir, out_yml, original, log_dir):
            _remove_stale_material_yml(materials_out, src_dir.name, out_yml)
            ok += 1
        else:
            fail += 1
    return ok, fail


def main() -> int:
    parser = argparse.ArgumentParser(description="Update VirtualLab materials for this submodule.")
    parser.add_argument(
        "--virtuallab-dir",
        type=Path,
        default=None,
        help="VirtualLab install directory (primary mode; Windows + pythonnet)",
    )
    parser.add_argument(
        "--csv-source",
        type=Path,
        default=None,
        help="Fallback: directory of pre-exported CSV material folders",
    )
    parser.add_argument(
        "--index-csv",
        type=Path,
        default=None,
        help="Optional index.csv for --csv-source mode",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Output root for this submodule",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Directory for per-material warning logs (default: <output>/logs)",
    )
    parser.add_argument(
        "--relocate-flat",
        action="store_true",
        help="Move flat materials/*.yml into category subdirectories (no export)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Export at most N materials (for testing)",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    log_dir = (args.log_dir or output / "logs").resolve()

    if args.relocate_flat:
        materials_out = output / "materials"
        if not materials_out.is_dir():
            print(f"error: materials directory not found: {materials_out}", file=sys.stderr)
            return 1
        moved = relocate_flat_yml(materials_out)
        print(f"vl: relocated {moved} flat yml file(s)")
        return 0

    vl_dir = args.virtuallab_dir
    resolved_vl_dir: Path | None = None
    if vl_dir is not None:
        try:
            resolved_vl_dir = resolve_virtuallab_dir(vl_dir)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    else:
        try:
            resolved_vl_dir = resolve_virtuallab_dir(DEFAULT_VL_DIR)
        except FileNotFoundError:
            resolved_vl_dir = None

    if resolved_vl_dir is not None and is_windows():
        ok, fail = export_from_catalog(resolved_vl_dir, output, log_dir, args.limit)
        print(f"vl: materials ok={ok} fail={fail} (catalog mode)")
        return 1 if fail else 0

    csv_source = args.csv_source
    if csv_source is None:
        csv_source = _VL_ROOT / "csv_export" / "materials"
    csv_source = csv_source.resolve()
    if args.index_csv:
        index_csv = args.index_csv.resolve()
    else:
        index_csv = (_VL_ROOT / "csv_export" / "materials_export" / "index.csv").resolve()

    if csv_source.is_dir():
        ok, fail = export_from_csv(csv_source, index_csv, output, log_dir, args.limit)
        print(f"vl: materials ok={ok} fail={fail} (csv mode)")
        return 1 if fail else 0

    if resolved_vl_dir is not None and not is_windows():
        return run_wsl_remote_export(args.limit)

    if vl_dir is not None:
        print(
            "error: virtuallab_dir not found (tried Windows and WSL mount paths)",
            file=sys.stderr,
        )
    else:
        print(
            "error: no virtuallab install found and csv source not found; "
            f"expected {csv_source}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
