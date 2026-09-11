# VlCatalogInspector

Windows x64 tool: live-read VirtualLab install catalogs and write harness YAML
under `database_virtuallab/` (`materials` / `films` / `geometries`).

## Build / run

Prefer the source wrapper (WSL):

```bash
cd ../..   # database_virtuallab
python3 update_current_database.py
```

Manual (on Windows staging / after `dotnet build`):

```bat
VlCatalogInspector.exe ^
  --install-dir "C:\Program Files\Wyrowski Photonics\VirtualLab Fusion (7.5.0) Trial" ^
  --out "<database_virtuallab_or_temp_out>"
```

Both `--install-dir` and `--out` are required (no defaults / no fallback).
`--out` is the **source root** (writes `materials/`, `films/`, `geometries/`).

## Output contract

| Kind | Rule |
|------|------|
| materials | `DATA.name=virtuallab/<stem>`；`formula_vl_*` / Sampled；α→k same-grid；catalog fields in DATA |
| films | coatings live → `type: films` + layer `background_material.$ref` |
| geometries | lossy subset；skips → `notes/geo_skip.txt` |
| TAGS | 见仓库 [`docs/tag_taxonomy.md`](../../../docs/tag_taxonomy.md)（`vl` + 闭集 category / 小写 vendor / spectrum / state） |
| HASH | never written |
