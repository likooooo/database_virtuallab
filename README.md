# vl

Export VirtualLab optical materials into refractiveindex.info-compatible YAML.

## Source modes

### Primary: VirtualLab install (Windows + Python)

Reads `MaterialsCatalog_LightTrans_Defined.ctlg` via **pythonnet** (no CSV intermediate step).
Only works when a real Python with `pythonnet` is available on Windows.

```bash
python vl/export.py \
  --virtuallab-dir "C:\Program Files\Wyrowski Photonics\VirtualLab Fusion (7.5.0) Trial"
```

### From WSL (recommended: PowerShell on Windows + Python in WSL)

If VirtualLab is on Windows but Python is not, use the two-stage SSH/SCP wrapper:

```bash
chmod +x vl/export_via_windows.sh
./vl/export_via_windows.sh

# Smoke test
./vl/export_via_windows.sh --limit 5
```

The script will:

1. Upload `export_materials.ps1` + `run_remote_export.ps1` to Windows `%TEMP%\virtuallab_export`
2. SSH into Windows and run PowerShell catalog export → `csv_export/materials/` + `meta.json`
3. Download `csv_export/` back to WSL
4. Run `export.py --csv-source …` locally to produce `materials/*.yml` and `logs/`

No Python required on Windows.

Configure [`config.yaml`](../config.example.yaml):

```yaml
virtuallab:
  remote_via_windows: true
  virtuallab_dir: "C:\\Program Files\\Wyrowski Photonics\\VirtualLab Fusion (7.5.0) Trial"
  windows_ssh:
    host: auto          # cmd.exe ipconfig: prefer vEthernet (WSL) IPv4, not resolv.conf
    user: like
    remote_dir: /c/Users/like/AppData/Local/Temp/virtuallab_export
```

Then: `python update_all.py --only virtuallab`

### CSV + meta.json (WSL conversion)

Windows PowerShell writes per-material `meta.json` (formula + parameters) and optional `n.csv` / `alpha.csv`.
WSL `export.py` maps formulas via `vl_formulas.py` and emits YAML.

```bash
python vl/export.py \
  --csv-source vl/csv_export/materials \
  --index-csv vl/csv_export/materials_export/index.csv
```

Legacy CSV-only trees (no `meta.json`) still work but cannot export formula materials without valid `n.csv`.

## Export logic

| VirtualLab type | Output |
|-----------------|--------|
| `SampledDispersion` / valid `SampledRefractiveIndex` | `tabulated nk` (parameters ignored) |
| Formula (Schott, PowerSeries, …) + absorption | `formula N` + `tabulated k` |
| Formula only | `formula N` |
| Sampled n + alpha | `tabulated nk` (cubic merge) |

Warnings and edge cases are recorded in per-material `logs/` and in YAML `COMMENTS`.

## Output

| Path | Contents |
|------|----------|
| `materials/{category}/…/{dir_name}.yml` | ri.info-compatible material (oghma-aligned layout) |
| `logs/` | Per-material warning logs |

Materials are grouped under `materials/` like `og`: `glasses/{vendor}`, `metal/{symbol}`, `oxides/{formula}`, `inorganic`, `liquid`, `polymers`, `thin_films`, `environment`, `generic`. See `vl_material_layout.py`.

## Install

```bash
cd ~/repos/simulation_database
pip install -r requirements.txt
pip install -r vl/requirements.txt   # adds pythonnet on Windows
```

## Usage

```bash
python vl/export.py --limit 5
python vl/export.py --relocate-flat   # one-shot flat → nested migration
python update_all.py --only virtuallab
```

Exit code is 0 when all exported materials succeed, 1 if any fail.

## Formula mapping

VirtualLab `DispersionFormula` → refractiveindex.info `type: formula N` (see `vl_formulas.py`).  
`SampledDispersion` never uses the `parameters` field for n; only sampled tables apply.
