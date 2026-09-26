# database_virtuallab

VirtualLab source for the assets harness.

## Active paths

| Path | Role |
|------|------|
| `materials/{primary_tag}/{SafeName}.yml` | Materials YAML (~2055; a few VL formulas logged as fail) |
| `films/{primary_tag}/{stem}.yml` | Coatings → `type: films` (13) |
| `geometries/{2d\|3d}/` | Lossy subset (8); skips in `_export_log/geo_skip.txt` |
| `notes/geo_lossy_map.md` | Geometry lossy mapping notes |

## Refresh YAML

统一入口：`update_current_database.py`（可选；被 `scripts/harness.sh` 并行调用）。

```bash
cd database_virtuallab
python3 update_current_database.py \
  --config "$SIMULATION_TOOL_DATABASE/clients/gui/assets/config.example.yaml" \
  --remote SimulationToolkits.Public.Database.Readwrite
```

行为：

1. 要求 WSL + `cmd.exe` / `wslpath`
2. 固定 `ensure_runtime(virtuallab_runtime, win-x86_64, latest_trial)` 下载已发布包（源码真源在 `simulation_vl_plugin`；本仓**不**含 VlCatalogInspector C#；**无** YAML 配置项）
3. 将解包缓存 rsync 到 Windows `%TEMP%\virtuallab_runtime`（禁止 `\\wsl$` 作运行目录，Fusion DLL 旁路解析）
4. 跑 `VlCatalogInspector.exe`：
   - `--install-dir` 写死  
     `C:\Program Files\Wyrowski Photonics\VirtualLab Fusion (7.5.0) Trial`
   - `--out` 在 `%TEMP%` 下；再 rsync `materials|films|geometries` 回本目录
5. 仅 live 安装目录导出（无 `--datas` / 无 dumper）

`scripts/harness.sh` Phase 0 在 sources 含本源时同次 ensure `virtuallab_runtime`；Phase 1 对本源传 `--config` / `--remote`（仅解析 ingest 连接）。

## Harness ingest

Config `harness.<remote>.sources` 含 `database_virtuallab` 即可；不必也不允许顶层 `virtuallab:` 块。

```bash
# 全量 = 刷新 YAML + reinit（reinit 内含 deploy）
bash scripts/harness.sh --config path/to/config.yaml \
  --remote SimulationToolkits.Public.Database.Readwrite --ssh aliyun

# YAML 已就绪：deploy + 删库再灌
bash scripts/reinit_ingest.sh --config path/to/config.yaml \
  --remote SimulationToolkits.Public.Database.Readwrite --ssh aliyun
```

或仅入库（不刷新、不删库）：`simdb-assets --config … --remote SimulationToolkits.Public.Database.Readwrite`。

## Contract

- **TAGS**：见仓库 [`docs/tag_taxonomy.md`](../docs/tag_taxonomy.md)（真源 `vl`；Categories → 闭集 `category:*` / 小写 `vendor:*` / `spectrum:*`；`state:*`）。**禁止** `shelf:*`。
- **name** = DB key，前缀 `virtuallab/`（µ→um）
- `formula_vl_*` / gas literature coeffs；α→k 同点；relative `$ref` via alias table
- Geometry: lossy asphere→sphere / grating→rect；Programmable skipped
