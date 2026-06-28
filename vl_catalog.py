"""Load VirtualLab material catalog via pythonnet (Windows + .NET only)."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_WL_MIN_UM = 0.3
DEFAULT_WL_MAX_UM = 2.5

CATALOG_REL = Path("Catalogs") / "MaterialsCatalog_LightTrans_Defined.ctlg"
DLL_NAME = "VirtualLabAPI.dll"

_LOADER_CS = """
using System;
using System.IO;
using System.Reflection;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Formatters.Binary;

public class VLBinder : SerializationBinder {
    Assembly _a;
    public VLBinder(Assembly a) { _a = a; }
    public override Type BindToType(string an, string tn) {
        if (an.StartsWith("VirtualLabAPI")) return _a.GetType(tn);
        return Type.GetType(tn + ", " + an);
    }
}

public static class VLLoader {
    public static object Load(string dll, string ctlg) {
        var asm = Assembly.LoadFrom(dll);
        var fmt = new BinaryFormatter { Binder = new VLBinder(asm) };
        using (var fs = File.OpenRead(ctlg)) return fmt.Deserialize(fs);
    }
}
"""


@dataclass(frozen=True)
class SampledCurve:
    wl_m: np.ndarray
    values: np.ndarray


@dataclass
class VlMaterial:
    name: str
    dir_name: str
    dispersion_formula: str
    absorption_formula: str
    parameters: list[float]
    constant_absorption: float
    sampled_n: SampledCurve | None
    sampled_alpha: SampledCurve | None
    wl_min_um: float
    wl_max_um: float


def safe_dir_name(name: str) -> str:
    """Filesystem-safe directory name (matches export_materials.ps1 Safe-DirName)."""
    out: list[str] = []
    for ch in name:
        out.append(ch if re.match(r"[a-zA-Z0-9_]", ch) else "_")
    result = "".join(out)
    while "__" in result:
        result = result.replace("__", "_")
    result = result.strip("_")
    if not result:
        result = "material"
    if result[0].isdigit():
        result = f"m_{result}"
    if len(result) > 180:
        result = result[:180].rstrip("_")
    return result


def unique_dir_names(names: list[str]) -> dict[str, str]:
    """Map original VirtualLab name -> unique dir_name."""
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for name in names:
        base = safe_dir_name(name)
        candidate = base
        i = 2
        while candidate in used:
            suffix = f"_{i}"
            max_len = 180 - len(suffix)
            candidate = base[:max_len].rstrip("_") + suffix
            i += 1
        used.add(candidate)
        mapping[name] = candidate
    return mapping


def _compile_loader():
    """Compile and return VLLoader type (cached per process)."""
    if _compile_loader._loader_type is not None:
        return _compile_loader._loader_type

    try:
        import clr  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "pythonnet is required to load VirtualLab catalogs. "
            "Install with: pip install pythonnet (Windows only)."
        ) from exc

    from Microsoft.CSharp import CSharpCodeProvider
    from System import Type
    from System.Reflection import Assembly

    provider = CSharpCodeProvider()
    refs = [
        Type.GetType("System.Object").Assembly.Location,
        Type.GetType("System.Runtime.Serialization.Formatters.Binary.BinaryFormatter").Assembly.Location,
    ]
    params = provider.CreateCompilerParameters()
    params.ReferencedAssemblies.AddRange(refs)
    params.GenerateInMemory = True
    result = provider.CompileAssemblyFromSource(params, _LOADER_CS)
    if result.Errors.HasErrors:
        msgs = "\n".join(str(e) for e in result.Errors)
        raise RuntimeError(f"failed to compile VLLoader: {msgs}")
    asm = result.CompiledAssembly
    loader_type = asm.GetType("VLLoader")
    _compile_loader._loader_type = loader_type
    return loader_type


_compile_loader._loader_type = None  # type: ignore[attr-defined]


def load_catalog(install_dir: Path) -> Any:
    """Deserialize VirtualLab materials catalog."""
    install_dir = install_dir.resolve()
    dll = install_dir / DLL_NAME
    ctlg = install_dir / CATALOG_REL
    if not dll.is_file():
        raise FileNotFoundError(f"VirtualLabAPI.dll not found: {dll}")
    if not ctlg.is_file():
        raise FileNotFoundError(f"materials catalog not found: {ctlg}")

    loader_type = _compile_loader()
    return loader_type.Load(str(dll), str(ctlg))


def _to_float_array(net_array) -> list[float]:
    if net_array is None:
        return []
    return [float(net_array[i]) for i in range(len(net_array))]


def read_data_array(da) -> SampledCurve | None:
    """Read VirtualLab 1D sampled field (wavelength in metres)."""
    if da is None:
        return None
    n = int(da.NoOfDataPoints)
    if n <= 0:
        return None

    wl = np.empty(n, dtype=float)
    if bool(da.IsEquidistant):
        start = float(da.CoordinateOfFirstDataPoint)
        step = float(da.SamplingDistance)
        for i in range(n):
            wl[i] = start + i * step
    else:
        nc = da.NonequidistantCoordinates
        for i in range(n):
            wl[i] = float(nc[int(i)])

    field = da.Data[0]
    vals = np.empty(n, dtype=float)
    field_type = field.GetType().Name
    for i in range(n):
        raw = field[int(i)]
        if field_type == "CFieldDerivative1DReal":
            vals[i] = float(raw)
        else:
            vals[i] = float(raw.GetType().GetField("Re").GetValue(raw))

    return SampledCurve(wl_m=wl, values=vals)


def _get_attr(obj, *names: str, default=None):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _wavelength_range_um(mat) -> tuple[float, float]:
    """Best-effort wavelength range in micrometres."""
    for lo_attr, hi_attr in (
        ("MinWavelength", "MaxWavelength"),
        ("MinimumWavelength", "MaximumWavelength"),
        ("WavelengthMin", "WavelengthMax"),
        ("LowerWavelengthLimit", "UpperWavelengthLimit"),
    ):
        lo = _get_attr(mat, lo_attr)
        hi = _get_attr(mat, hi_attr)
        if lo is not None and hi is not None:
            lo_m, hi_m = float(lo), float(hi)
            if lo_m > 0 and hi_m > lo_m:
                return lo_m * 1e6, hi_m * 1e6

    n_data = read_data_array(_get_attr(mat, "SampledRefractiveIndex"))
    a_data = read_data_array(_get_attr(mat, "SampledAbsorptionCoeff"))
    wl_sources = []
    if n_data is not None and n_data.wl_m.size:
        wl_sources.append(n_data.wl_m)
    if a_data is not None and a_data.wl_m.size:
        wl_sources.append(a_data.wl_m)
    if wl_sources:
        wl_all = np.concatenate(wl_sources)
        return float(wl_all.min() * 1e6), float(wl_all.max() * 1e6)

    return DEFAULT_WL_MIN_UM, DEFAULT_WL_MAX_UM


def parse_material(mat, dir_name: str) -> VlMaterial:
    """Extract export-relevant fields from a catalog entry."""
    params = _to_float_array(_get_attr(mat, "Parameters"))
    if len(params) < 10:
        params = params + [0.0] * (10 - len(params))

    wl_min, wl_max = _wavelength_range_um(mat)
    dispersion = str(_get_attr(mat, "DispersionFormula", default="") or "")
    absorption = str(_get_attr(mat, "AbsorptionFormula", default="") or "")

    return VlMaterial(
        name=str(_get_attr(mat, "Name", default=dir_name) or dir_name),
        dir_name=dir_name,
        dispersion_formula=dispersion,
        absorption_formula=absorption,
        parameters=params,
        constant_absorption=float(_get_attr(mat, "ConstantAbsorptionCoeff", default=0.0) or 0.0),
        sampled_n=read_data_array(_get_attr(mat, "SampledRefractiveIndex")),
        sampled_alpha=read_data_array(_get_attr(mat, "SampledAbsorptionCoeff")),
        wl_min_um=wl_min,
        wl_max_um=wl_max,
    )


def iter_materials(install_dir: Path) -> list[VlMaterial]:
    """Load catalog and return parsed material list with stable dir names."""
    catalog = load_catalog(install_dir)
    entries = list(catalog.Entries)
    names = [str(e.Name) for e in entries]
    dir_map = unique_dir_names(names)
    return [parse_material(e, dir_map[name]) for e, name in zip(entries, names)]


def is_windows() -> bool:
    return sys.platform == "win32"
