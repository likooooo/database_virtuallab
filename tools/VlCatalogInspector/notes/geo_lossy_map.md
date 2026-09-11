# geo_lossy_map

| VL 源 | core | 损失（写入 COMMENTS） |
|-------|------|------------------------|
| AsphericalInterface（取 Radius R） | `sphere`（radius µm） | 丢高次 asphere / conic |
| Binary/Blazed/Sine/Triangular grating | `rect`（halfwidth from DefinitionArea / Period） | 丢槽形/高度调制 |
| Aperture/Stop Rectangular | `rect` | 丢软边；若 dump 无尺寸则跳过 |
| Aperture/Stop Elliptic | `circle` / `ellipse` | 丢软边；无半轴则跳过 |
| Programmable / Combined / 无尺寸 | 跳过 | 不造假 mesh |

- `name: virtuallab/<stem>`；路径 `geometries/{2d|3d}/…`
- 单位：VL 米 → core µm
- 不导出 `fem`
