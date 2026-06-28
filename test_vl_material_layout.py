#!/usr/bin/env python3
"""Tests for virtuallab material directory layout."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vl_material_layout import material_out_yml, material_rel_parts


def test_glass_vendor_layout() -> None:
    assert material_rel_parts("ZF1_CDGM_2016") == ("glasses", "cdgm")
    assert material_rel_parts("YGH51_Ohara_2016") == ("glasses", "ohara")
    assert material_rel_parts("A63_65_Corning") == ("glasses", "corning")


def test_metal_layout() -> None:
    assert material_rel_parts("Aluminium_Al_1980") == ("metal", "Al")
    assert material_rel_parts("Silver_Ag_1985") == ("metal", "Ag")


def test_oxide_layout() -> None:
    assert material_rel_parts("Aluminium_oxide_amorphous_a_Al2O3_1975") == ("oxides", "Al2O3")
    assert material_rel_parts("Zinc_oxide_ZnO_5_606gcm_3_1997") == ("oxides", "ZnO")


def test_thin_film_layout() -> None:
    assert material_rel_parts("Zirconium_evap_thinFilm_Zr_1988") == ("thin_films",)
    assert material_rel_parts("Yttrium_Oxide_Y2O3_ThinFilm") == ("thin_films",)


def test_environment_and_liquid() -> None:
    assert material_rel_parts("Air") == ("environment",)
    assert material_rel_parts("Water_H2O_pure") == ("liquid",)


def test_material_out_yml() -> None:
    root = Path("/tmp/materials")
    path = material_out_yml(root, "ZF1_CDGM_2016")
    assert path == root / "glasses" / "cdgm" / "ZF1_CDGM_2016.yml"


if __name__ == "__main__":
    test_glass_vendor_layout()
    test_metal_layout()
    test_oxide_layout()
    test_thin_film_layout()
    test_environment_and_liquid()
    test_material_out_yml()
    print("ok")
