#!/usr/bin/env python3
"""Smoke tests for YAML emit (no VirtualLab / simulation required)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import yaml
from yaml import BaseLoader

_VL_ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "vl_update", _VL_ROOT / "update_current_database.py"
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
write_formula_yml = _mod.write_formula_yml
tabulated_k_block = _mod.tabulated_k_block


def test_write_formula_plus_k_block() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_material.yml"
        write_formula_yml(
            path,
            3,
            0.36,
            1.55,
            [2.27, -0.009, 2, 0.01, -2],
            extra_blocks=[tabulated_k_block([0.35, 0.5], [1e-6, 2e-6])],
            comments="test material",
        )
        text = path.read_text(encoding="utf-8")
        assert "type: formula 3" in text
        assert "type: tabulated k" in text
        assert "wavelength_range: 0.36 1.55" in text
        model = yaml.load(text, Loader=BaseLoader)
        assert len(model["DATA"]) == 2


if __name__ == "__main__":
    test_write_formula_plus_k_block()
    print("ok")
