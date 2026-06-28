#!/usr/bin/env python3
"""Export VirtualLab materials to refractiveindex.info-compatible YAML."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_VL_ROOT = Path(__file__).resolve().parent
for p in (ROOT, _VL_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from common.csv_io import read_material_nk_table
from common.interpolation import merge_n_alpha_to_nk
from common.logging_util import MaterialLogger
from common.nk_convert import k_from_alpha_on_wl_um
from common.yml_emit import (
    tabulated_k_block,
    write_formula_yml,
    write_tabulated_nk_yml,
)
from vl_catalog import SampledCurve, VlMaterial, is_windows, iter_materials
from vl_formulas import map_dispersion_formula
from vl_material_layout import material_out_yml, stale_flat_yml


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


def _validate_nk(wl_um: np.ndarray, n_vals: np.ndarray, k_vals: np.ndarray, log: MaterialLogger) -> None:
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
            _validate_nk(wl_um, n_out, k_out, log)

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
    from common.csv_io import read_tabulated_xy_um

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
        _validate_nk(wl_um, n_out, k_out, log)

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
    parser = argparse.ArgumentParser(description="Export VirtualLab materials to YAML.")
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
    if vl_dir is None and DEFAULT_VL_DIR.is_dir():
        vl_dir = DEFAULT_VL_DIR

    if vl_dir is not None:
        if not is_windows():
            print(
                "error: --virtuallab-dir requires Windows with pythonnet",
                file=sys.stderr,
            )
            return 1
        vl_dir = vl_dir.resolve()
        if not vl_dir.is_dir():
            print(f"error: VirtualLab dir not found: {vl_dir}", file=sys.stderr)
            return 1
        ok, fail = export_from_catalog(vl_dir, output, log_dir, args.limit)
        print(f"vl: materials ok={ok} fail={fail} (catalog mode)")
        return 1 if fail else 0

    csv_source = args.csv_source
    if csv_source is None:
        local_csv = _VL_ROOT / "csv_export" / "materials"
        legacy_csv = Path("/home/like/repos/virtuallab_materials/materials")
        csv_source = local_csv if local_csv.is_dir() else legacy_csv
    csv_source = csv_source.resolve()
    if args.index_csv:
        index_csv = args.index_csv.resolve()
    else:
        local_index = _VL_ROOT / "csv_export" / "materials_export" / "index.csv"
        legacy_index = Path("/home/like/repos/virtuallab_materials/materials_export/index.csv")
        index_csv = local_index if local_index.is_file() else legacy_index

    if not csv_source.is_dir():
        print(
            "error: no --virtuallab-dir and csv source not found; "
            f"expected {csv_source}",
            file=sys.stderr,
        )
        return 1

    ok, fail = export_from_csv(csv_source, index_csv, output, log_dir, args.limit)
    print(f"vl: materials ok={ok} fail={fail} (csv fallback)")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
