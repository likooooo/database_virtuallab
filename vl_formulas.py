"""Map VirtualLab dispersion formulas to refractiveindex.info formula types."""

from __future__ import annotations

from dataclasses import dataclass

# VirtualLab PowerSeries: n² = Σ pᵢ λ^eᵢ  (λ in µm)
_POWER_SERIES_EXPS = (2, 4, 6, -2, -4, -6, -8)


@dataclass(frozen=True)
class RiFormula:
    formula_type: int
    coefficients: list[float]
    note: str = ""


def _schott_to_poly(params: list[float]) -> RiFormula:
    """VL Schott: n² = p0 + p1*λ² + p2*λ⁻² + ... -> ri.info formula 3."""
    coeffs: list[float] = [params[0]]
    for i in range(1, 6):
        if i < len(params) and params[i] != 0.0:
            exp = 2 if i == 1 else -2 * (i - 1)
            coeffs.extend([params[i], float(exp)])
    return RiFormula(3, coeffs, note="VirtualLab Schott -> refractiveindex.info formula 3")


def _sellmeier1_to_sellmeier2(params: list[float]) -> RiFormula:
    """VL Sellmeier1: 1 + p0*λ²/(λ²-p1)+... -> formula 2 with C0=0."""
    coeffs: list[float] = [0.0]
    for i in range(0, 6, 2):
        if i + 1 < len(params) and (params[i] != 0.0 or params[i + 1] != 0.0):
            coeffs.extend([params[i], params[i + 1]])
    return RiFormula(2, coeffs, note="VirtualLab Sellmeier1 -> refractiveindex.info formula 2")


def _sellmeier4(params: list[float]) -> RiFormula:
    """VL Sellmeier4 maps to refractiveindex.info formula 4 (pass-through)."""
    used = [p for p in params if p != 0.0]
    if not used:
        used = list(params[:6])
    return RiFormula(4, used, note="VirtualLab Sellmeier4 -> refractiveindex.info formula 4")


def _sellmeier3(params: list[float]) -> RiFormula:
    """VL Sellmeier3 -> formula 1 (C0=0, pairs in denominator squared)."""
    coeffs: list[float] = [0.0]
    for i in range(0, 8, 2):
        if i + 1 < len(params) and (params[i] != 0.0 or params[i + 1] != 0.0):
            c2 = params[i + 1]
            coeffs.extend([params[i], c2 * c2 if c2 != 0.0 else 0.0])
    return RiFormula(1, coeffs, note="VirtualLab Sellmeier3 -> refractiveindex.info formula 1")


def _sellmeier5(params: list[float]) -> RiFormula:
    """VL Sellmeier5 (extended) -> formula 2 with all term pairs."""
    coeffs: list[float] = [0.0]
    for i in range(0, 10, 2):
        if i + 1 < len(params) and (params[i] != 0.0 or params[i + 1] != 0.0):
            coeffs.extend([params[i], params[i + 1]])
    return RiFormula(2, coeffs, note="VirtualLab Sellmeier5 -> refractiveindex.info formula 2")


def _herzberger(params: list[float]) -> RiFormula:
    n_use = 5
    for i, p in enumerate(params):
        if p != 0.0:
            n_use = max(n_use, i + 1)
    used = list(params[: min(n_use, 8)])
    while len(used) > 3 and used[-1] == 0.0:
        used.pop()
    if len(used) < 3:
        used = (params + [0.0] * 3)[:5]
    return RiFormula(7, used, note="VirtualLab Herzberger -> refractiveindex.info formula 7")


def _cauchy(params: list[float]) -> RiFormula:
    """VL Cauchy: n = p0 + p1*λ^p2 + ... -> formula 5."""
    coeffs: list[float] = [params[0]]
    if len(params) > 2 and params[1] != 0.0:
        coeffs.extend([params[1], params[2] if len(params) > 2 else -2.0])
    if len(params) > 4 and params[3] != 0.0:
        coeffs.extend([params[3], params[4] if len(params) > 4 else -4.0])
    return RiFormula(5, coeffs, note="VirtualLab Cauchy -> refractiveindex.info formula 5")


def _conrady(params: list[float]) -> RiFormula:
    """VL Conrady: n = p0 + p1/(λ²-p2) + p3*λ² -> approximate as formula 7."""
    return RiFormula(
        7,
        [params[0], params[1], params[2], params[3] if len(params) > 3 else 0.0],
        note="VirtualLab Conrady approximated as refractiveindex.info formula 7",
    )


def _power_series(params: list[float]) -> RiFormula:
    coeffs: list[float] = [params[0]]
    for i, exp in enumerate(_POWER_SERIES_EXPS, start=1):
        if i < len(params) and params[i] != 0.0:
            coeffs.extend([params[i], float(exp)])
    return RiFormula(3, coeffs, note="VirtualLab PowerSeries -> refractiveindex.info formula 3")


def _constant_n(params: list[float]) -> RiFormula:
    n = params[0] if params else 1.0
    return RiFormula(5, [n, 0.0, 0.0], note="constant refractive index")


def _air() -> RiFormula:
    return RiFormula(5, [1.0, 0.0, 0.0], note="air/vacuum n=1")


def map_dispersion_formula(vl_formula: str, params: list[float]) -> RiFormula | None:
    """
    Map VirtualLab DispersionFormula + Parameters to ri.info formula block.

    Returns None for SampledDispersion and other non-formula types.
    """
    key = (vl_formula or "").strip()
    if key in ("SampledDispersion", ""):
        return None

    mapping = {
        "Schott": _schott_to_poly,
        "Sellmeier1": _sellmeier1_to_sellmeier2,
        "Sellmeier3": _sellmeier3,
        "Sellmeier4": _sellmeier4,
        "Sellmeier5": _sellmeier5,
        "Herzberger": _herzberger,
        "Cauchy": _cauchy,
        "Conrady": _conrady,
        "PowerSeries": _power_series,
        "ConstantRefractiveIndex": _constant_n,
        "Edlen_AirFormula": lambda _: _air(),
        "Zemax_AirFormula": lambda _: _air(),
    }

    fn = mapping.get(key)
    if fn is None:
        return None
    return fn(params)
