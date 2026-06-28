"""Map VirtualLab material dir_name to oghma-aligned materials/ subdirectories."""

from __future__ import annotations

import re
from pathlib import Path

# Top-level categories mirror og/materials/ plus virtuallab-specific buckets.
OGHMA_TOP_LEVEL = frozenset(
    {
        "generic",
        "glasses",
        "inorganic",
        "liquid",
        "metal",
        "oxides",
        "perovskites",
        "polymers",
        "small_molecules",
        "thin_films",
        "environment",
    }
)

_GLASS_VENDOR_SUFFIX = re.compile(
    r"_(CDGM|Ohara|Hikari|Hoya|Schott|Sumita|LZOS|Corning)_",
    re.IGNORECASE,
)
_GLASS_VENDOR_END = re.compile(r"_Corning$", re.IGNORECASE)
_HERAeUS = re.compile(r"_Heraeus$", re.IGNORECASE)

_OXIDE_HINT = re.compile(
    r"(?:^|_)(?:.*_)?(?:oxide|oxynitride|Oxide|ALON|VO2|WO3|TiO2|SnO2|ZnO|SiO2|Al2O3|ZrO2|Y2O3|MgO|Fe2O3|Fe3O4|Co3O4|Mn3O4|Cr2O3|NiO|CuO|MoO3|V2O5)(?:_|$)",
    re.IGNORECASE,
)

_COMPOUND_HINT = re.compile(
    r"_(?:nitride|arsenide|antimonide|phosphide|selenide|sulfide|telluride|carbide|fluoride|iodide|bromide|chloride|phosphide)(?:_|$)",
    re.IGNORECASE,
)

_CRYSTAL_HINT = re.compile(
    r"_(?:cubic|hexagonal|trigonal|amorphous|polyxtal|singleXtal|ordinaryRay|extraordinaryRay)(?:_|$)",
    re.IGNORECASE,
)

_THIN_FILM_HINT = re.compile(
    r"(?:ThinFilm|thinFilm|_evap_|_sputtered_|evap_thinFilm|sputtered_thinFilm)",
    re.IGNORECASE,
)

_POLYMER_HINT = re.compile(
    r"(?:^|_)(?:PMMA|Polyethylene|Polystyrene|Polypropylene|Polycarbonate|COC|Mylar|Saran|Nylon|Acrylic|Polymer|Polystyrene)(?:_|$)",
    re.IGNORECASE,
)

_GLASS_CODE = re.compile(
    r"^(?:BK|SF|N-BK|N-SF|F\d|K\d|LAK|PK|PSK|BAK|BAL|LAS|LASF|LLF|LLD|KZFS|ZPK|ZPKA|ZF|ZBAF|LZ|MP|MC|AF\d|YGH|E_[A-Z])",
    re.IGNORECASE,
)

_ELEMENT_PREFIX: dict[str, str] = {
    "Actinium": "Ac",
    "Aluminium": "Al",
    "Aluminum": "Al",
    "Antimony": "Sb",
    "Arsenic": "As",
    "Barium": "Ba",
    "Beryllium": "Be",
    "Bismuth": "Bi",
    "Boron": "B",
    "Bromine": "Br",
    "Cadmium": "Cd",
    "Calcium": "Ca",
    "Caesium": "Cs",
    "Carbon": "C",
    "Cerium": "Ce",
    "Chlorine": "Cl",
    "Chromium": "Cr",
    "Cobalt": "Co",
    "Copper": "Cu",
    "Dysprosium": "Dy",
    "Erbium": "Er",
    "Europium": "Eu",
    "Fluorine": "F",
    "Gadolinium": "Gd",
    "Gallium": "Ga",
    "Germanium": "Ge",
    "Gold": "Au",
    "Hafnium": "Hf",
    "Helium": "He",
    "Hydrogen": "H",
    "Indium": "In",
    "Iodine": "I",
    "Iridium": "Ir",
    "Iron": "Fe",
    "Lanthanum": "La",
    "Lead": "Pb",
    "Lithium": "Li",
    "Magnesium": "Mg",
    "Manganese": "Mn",
    "Mercury": "Hg",
    "Molybdenum": "Mo",
    "Neodymium": "Nd",
    "Neon": "Ne",
    "Nickel": "Ni",
    "Niobium": "Nb",
    "Nitrogen": "N",
    "Osmium": "Os",
    "Oxygen": "O",
    "Palladium": "Pd",
    "Phosphorus": "P",
    "Platinum": "Pt",
    "Potassium": "K",
    "Praseodymium": "Pr",
    "Rhenium": "Re",
    "Rhodium": "Rh",
    "Rubidium": "Rb",
    "Ruthenium": "Ru",
    "Samarium": "Sm",
    "Scandium": "Sc",
    "Selenium": "Se",
    "Silicon": "Si",
    "Silver": "Ag",
    "Sodium": "Na",
    "Strontium": "Sr",
    "Sulfur": "S",
    "Tantalum": "Ta",
    "Technetium": "Tc",
    "Tellurium": "Te",
    "Terbium": "Tb",
    "Thallium": "Tl",
    "Thorium": "Th",
    "Thulium": "Tm",
    "Tin": "Sn",
    "Titanium": "Ti",
    "Tungsten": "W",
    "Uranium": "U",
    "Vanadium": "V",
    "Ytterbium": "Yb",
    "Yttrium": "Y",
    "Zinc": "Zn",
    "Zirconium": "Zr",
}

_OXIDE_FORMULA = re.compile(
    r"(Al2O3|ZnO|SiO2|ZrO2|Y2O3|TiO2|SnO2|MgO|Fe2O3|Fe3O4|Co3O4|Mn3O4|Cr2O3|NiO|CuO|MoO3|V2O5|WO3|VO2|H2O|MgF2|CaF2|BaF2|LiF|NaCl|KCl)",
    re.IGNORECASE,
)


def _glass_vendor_parts(dir_name: str) -> tuple[str, ...] | None:
    m = _GLASS_VENDOR_SUFFIX.search(dir_name)
    if m:
        return ("glasses", m.group(1).lower())
    if _GLASS_VENDOR_END.search(dir_name) or "_Corning" in dir_name:
        return ("glasses", "corning")
    if _HERAeUS.search(dir_name):
        return ("glasses", "heraeus")
    if _GLASS_CODE.match(dir_name):
        if dir_name.startswith("LZ"):
            return ("glasses", "lzos")
        return ("glasses", "other")
    return None


def _element_prefix(dir_name: str) -> str | None:
    for name, symbol in sorted(_ELEMENT_PREFIX.items(), key=lambda x: -len(x[0])):
        if dir_name.startswith(name + "_") or dir_name == name:
            return symbol
    return None


_OXIDE_CANON: dict[str, str] = {
    "AL2O3": "Al2O3",
    "ZNO": "ZnO",
    "SIO2": "SiO2",
    "ZRO2": "ZrO2",
    "Y2O3": "Y2O3",
    "TIO2": "TiO2",
    "SNO2": "SnO2",
    "MGO": "MgO",
    "FE2O3": "Fe2O3",
    "FE3O4": "Fe3O4",
    "CO3O4": "Co3O4",
    "MN3O4": "Mn3O4",
    "CR2O3": "Cr2O3",
    "NIO": "NiO",
    "CUO": "CuO",
    "MOO3": "MoO3",
    "V2O5": "V2O5",
    "WO3": "WO3",
    "VO2": "VO2",
    "H2O": "H2O",
    "MGF2": "MgF2",
    "CAF2": "CaF2",
    "BAF2": "BaF2",
    "LIF": "LiF",
    "NACL": "NaCl",
    "KCL": "KCl",
}


def _oxide_subdir(dir_name: str) -> str | None:
    m = _OXIDE_FORMULA.search(dir_name)
    if m:
        return _OXIDE_CANON.get(m.group(1).upper(), m.group(1))
    return None


def _is_pure_metal(dir_name: str) -> bool:
    elem = _element_prefix(dir_name)
    if elem is None:
        return False
    if _OXIDE_HINT.search(dir_name) or _COMPOUND_HINT.search(dir_name):
        return False
    if _CRYSTAL_HINT.search(dir_name):
        return False
    if _THIN_FILM_HINT.search(dir_name):
        return False
    return True


def material_rel_parts(dir_name: str) -> tuple[str, ...]:
    """Return path segments under materials/ for a VirtualLab dir_name (no .yml)."""
    if dir_name.startswith("Air") or dir_name == "Vacuum":
        return ("environment",)

    if dir_name.startswith("Water") or dir_name.startswith("Mercury"):
        return ("liquid",)

    if _THIN_FILM_HINT.search(dir_name):
        return ("thin_films",)

    glass = _glass_vendor_parts(dir_name)
    if glass is not None:
        return glass

    if _OXIDE_HINT.search(dir_name):
        sub = _oxide_subdir(dir_name)
        if sub:
            return ("oxides", sub)
        return ("oxides",)

    if _POLYMER_HINT.search(dir_name):
        return ("polymers",)

    if _is_pure_metal(dir_name):
        return ("metal", _element_prefix(dir_name) or "unknown")

    if _COMPOUND_HINT.search(dir_name) or _CRYSTAL_HINT.search(dir_name):
        return ("inorganic",)

    if re.match(
        r"^(?:AMTIR|CLEARTRAN|Calcite|Sapphire|KDP|KRS|Diamond|Germanium|Silicon|Gallium|Indium|ZBLAN|ZBLA)",
        dir_name,
        re.IGNORECASE,
    ):
        return ("inorganic",)

    if dir_name.startswith("Ideal_"):
        return ("generic",)

    if re.match(
        r"^(?:Fused_Silica|Pyrex|Infrasil|Homosil|Herasil|HOQ)",
        dir_name,
        re.IGNORECASE,
    ):
        return ("generic",)

    return ("generic",)


def material_out_yml(materials_root: Path, dir_name: str) -> Path:
    """Full path for ``materials/{…}/{dir_name}.yml``."""
    return materials_root.joinpath(*material_rel_parts(dir_name), f"{dir_name}.yml")


def stale_flat_yml(materials_root: Path, dir_name: str) -> Path:
    """Legacy flat layout ``materials/{dir_name}.yml``."""
    return materials_root / f"{dir_name}.yml"
