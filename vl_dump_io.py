"""Read VlCatalogInspector datas/ dump (JSON + CSV). Malformed VL shapes are rejected here."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

_KEY_SAFE = re.compile(r"[^A-Za-z0-9_./+\-:]")

# Physical Edlen dry-air coefficients (same set as predefined/air_edlen). VL dump stores T/P, not these.
_EDLEN_COEFFICIENTS = [
    1.0e-8,
    8342.13,
    2406030.0,
    130.0,
    15997.0,
    38.9,
    760.0,
    1.049,
    0.0157,
    1.0e-6,
    720.775,
    0.003661,
]

# VL DispersionFormula → formula_vl_* with fixed coefficient arity (pad/truncate dump params).
_VL_FORMULA: dict[str, tuple[str, int]] = {
    "Schott": ("formula_vl_schott", 6),
    "Sellmeier1": ("formula_vl_sellmeier_1", 6),
    "Sellmeier2": ("formula_vl_sellmeier_2", 7),
    "Sellmeier3": ("formula_vl_sellmeier_3", 8),
    "Sellmeier4": ("formula_vl_sellmeier_4", 5),
    "Sellmeier5": ("formula_vl_sellmeier_5", 10),
    "Herzberger": ("formula_vl_herzberger", 6),
    "Conrady": ("formula_vl_conrady", 3),
    "Cauchy": ("formula_vl_cauchy", 4),
    "PowerSeries": ("formula_vl_power_series", 10),
    "ConstantRefractiveIndex": ("formula_vl_constant", 1),
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def material_index(datas: Path) -> dict[str, str]:
    """VL material Name → dir_name."""
    idx = load_json(datas / "index.json")
    mats = next(e for e in idx if e.get("folder") == "materials")
    return {i["name"]: i["dir_name"] for i in mats["items"]}


def safe_dir_name(name: str) -> str:
    s = "".join(ch if re.match(r"[a-zA-Z0-9_]", ch) else "_" for ch in name)
    while "__" in s:
        s = s.replace("__", "_")
    s = s.strip("_") or "object"
    if s[0].isdigit():
        s = "m_" + s
    return s[:180]


def build_tags(
    categories: list[str] | None,
    state_of_matter: str,
    *,
    keep_unmapped_category: bool = False,
) -> list[str]:
    from framework.material_tags import build_vl_tags

    return build_vl_tags(
        categories, state_of_matter, keep_unmapped_category=keep_unmapped_category
    )


def primary_tag(tags: list[str]) -> str:
    from framework.material_tags import primary_tag_dir

    return primary_tag_dir(tags, safe_dir_name=safe_dir_name)


def object_key(dir_name: str) -> str:
    if _KEY_SAFE.search(dir_name):
        raise ValueError(f"dir_name not key-safe: {dir_name!r}")
    return f"vl/{dir_name}"


def resolve_air_ref(reference_material: str | None, name_to_dir: dict[str, str]) -> str | None:
    if not reference_material:
        return None
    if reference_material in name_to_dir:
        return object_key(name_to_dir[reference_material])
    if reference_material == "Standard Air" and "Air" in name_to_dir:
        return object_key(name_to_dir["Air"])
    raise ValueError(f"unresolved reference_material {reference_material!r}")


def read_xy_csv(path: Path) -> tuple[list[float], list[float]]:
    """CSV from dump: wavelength column in metres → return wl_um, values."""
    xs: list[float] = []
    ys: list[float] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) != 2:
            raise ValueError(f"{path}: bad row {line!r}")
        wl_m = float(parts[0])
        ys.append(float(parts[1]))
        xs.append(wl_m * 1.0e6)
    if not xs:
        raise ValueError(f"{path}: empty data")
    return xs, ys


def pad_coeffs(params: list[float], n: int) -> list[float]:
    out = [float(x) for x in params[:n]]
    while len(out) < n:
        out.append(0.0)
    return out


def catalog_from_glass(glass: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(glass, dict):
        return {}
    out: dict[str, float] = {}
    nd = glass.get("nd")
    if isinstance(nd, (int, float)) and math.isfinite(nd) and nd != 1.0:
        out["nd"] = float(nd)
    vd = glass.get("abbe_vd")
    if isinstance(vd, (int, float)) and math.isfinite(vd) and vd != 0.0:
        out["Vd"] = float(vd)
    dens = glass.get("density_gcm3")
    if isinstance(dens, (int, float)) and math.isfinite(dens) and dens > 0.0:
        out["density"] = float(dens)
    return out


def edlen_coefficients() -> list[float]:
    return list(_EDLEN_COEFFICIENTS)


def vl_formula_id(dispersion: str) -> tuple[str, int] | None:
    return _VL_FORMULA.get(dispersion)
