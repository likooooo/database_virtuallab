# database_virtuallab

VirtualLab source for the assets harness.

## Active paths

| Path | Role |
|------|------|
| `materials/{primary_tag}/{SafeName}.yml` | Materials YAML (~2055; a few VL formulas logged as fail) |
| `films/{primary_tag}/{stem}.yml` | Coatings → `type: films` (13) |
| `geometries/{2d\|3d}/` | Lossy subset (8); skips in `_export_log/geo_skip.txt` |

## Refresh YAML

统一入口：`update_current_database.py`（可选；被 `script/harness.sh` 并行调用）。

```bash
cd database_virtuallab
python3 update_current_database.py
```

行为（对齐 `fmm_mp.sh` vl-build，无 SSH）：

1. 要求 WSL + `cmd.exe` / `wslpath`
2. 写死 `dotnet.exe`：`/mnt/c/Program Files/dotnet/dotnet.exe`
3. 源码 sync 到 Windows `%TEMP%\VlCatalogInspector`（禁止 `\\wsl$` 作编译目录）
4. `dotnet build -c Release`
5. 从暂存目录跑 `VlCatalogInspector.exe`：
   - `--install-dir` 写死  
     `C:\Program Files\Wyrowski Photonics\VirtualLab Fusion (7.5.0) Trial`
   - `--out` 在 `%TEMP%` 下；再 rsync `materials|films|geometries` 回本目录
6. 仅 live 安装目录导出（无 `--datas` / 无 dumper）

工具源码：[tools/VlCatalogInspector/](tools/VlCatalogInspector/)（materials + films + geometries）。

## Harness ingest

Config `harness.<remote>.sources` 含 `database_virtuallab` 时：

```bash
# 全量 = 刷新 YAML + reinit（reinit 内含 deploy）
bash script/harness.sh --config path/to/config.yaml \
  --remote SimulationToolkits.Public.Database.Readwrite --ssh aliyun

# YAML 已就绪：deploy + 删库再灌
bash script/reinit_ingest.sh --config path/to/config.yaml \
  --remote SimulationToolkits.Public.Database.Readwrite --ssh aliyun
```

或仅入库（不刷新、不删库）：`simdb-assets --config … --remote SimulationToolkits.Public.Database.Readwrite`。

## Contract

- **TAGS**：见仓库 [`docs/tag_taxonomy.md`](../docs/tag_taxonomy.md)（真源 `vl`；Categories → 闭集 `category:*` / 小写 `vendor:*` / `spectrum:*`；`state:*`）。**禁止** `shelf:*`。
- **name** = DB key，前缀 `virtuallab/`（µ→um）
- `formula_vl_*` / gas literature coeffs；α→k 同点；relative `$ref` via alias table
- Geometry: lossy asphere→sphere / grating→rect；Programmable skipped
