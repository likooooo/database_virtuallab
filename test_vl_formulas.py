#!/usr/bin/env python3
"""Unit tests for VirtualLab formula mapping (no catalog required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VL_ROOT = Path(__file__).resolve().parent
if str(_VL_ROOT) not in sys.path:
    sys.path.insert(0, str(_VL_ROOT))

from vl_formulas import map_dispersion_formula


def test_sampled_dispersion_returns_none() -> None:
    assert map_dispersion_formula("SampledDispersion", [1.0] + [0.0] * 9) is None


def test_schott_maps_to_formula_3() -> None:
    params = [2.27, -0.009, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ri = map_dispersion_formula("Schott", params)
    assert ri is not None
    assert ri.formula_type == 3
    assert ri.coefficients[0] == pytest.approx(2.27)


def test_sellmeier1_maps_to_formula_2() -> None:
    params = [1.0, 0.01, 0.5, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ri = map_dispersion_formula("Sellmeier1", params)
    assert ri is not None
    assert ri.formula_type == 2
    assert ri.coefficients[0] == 0.0


def test_power_series_maps_to_formula_3() -> None:
    params = [2.271, -0.00947, -8.9e-5, 0.0, 0.0109, 0.0, 0.0, 0.0, 0.0, 0.0]
    ri = map_dispersion_formula("PowerSeries", params)
    assert ri is not None
    assert ri.formula_type == 3
    assert 2 in ri.coefficients
    assert -2 in ri.coefficients
