# 参考文件变量对照表（REFERENCE MAPPING）

把参考文件 `OdetteV3.blend` 里的**节点组、接口、硬编码常量、贴图槽**
逐一映射到本插件的实现位置与参数名。所有"参考值"都是从 `.blend` 里实测导出的
（导出脚本见 `npr-ref/dump/`，可读规格见 `npr-ref/spec/ALL_SPECS.txt`）。

参考文件概况：**18 个节点组 / 111 个主组节点 / 165 条连线 / 49 个材质 /
28 张 packed 贴图 / 3 个 UV 图（`UVMap`、`UV1`、`UV2`）**。

---

## 1. 主组 `Shader`

### 1.1 接口对照

| 参考文件接口 | 类型 | 参考默认 | 插件接口名 | 说明 |
|---|---|---|---|---|
| `Emission` | Shader **输出** | — | `Emission` | 同名同序（索引 0） |
| `Face` | Float 输入 | 0 | `Face` | 部位 mask |
| `Body01` | Float 输入 | 0 | `Body01` | 部位 mask |
| `Body` | Float 输入 | 0 | `Body` | 部位 mask |
| `Hair` | Float 输入 | 0 | `Hair` | 部位 mask |
| `Eyes` | Float 输入 | 0 | `Eyes` | 部位 mask |
| `Crystal` | Float 输入 | 0 | `Crystal` | 水晶/宝石分支 |

> 参考文件的 39 个材质实例**全部使用默认 mask**，部位差异完全靠节点组内部
> 按 mask 选择贴图实现。插件保持同样做法。

### 1.2 插件新增的接口（参考文件里是硬编码常量或内嵌贴图）

**贴图槽**（参考文件里是内嵌 `TexImage` 节点，插件提升为接口）

| 插件接口 | 参考文件里的来源 | 组参数名 |
|---|---|---|
| `BaseColorTex` | `*_Tex_*_Diffuse.png` | `tex_base_color` |
| `LightmapTex` | `*_Tex_*_Lightmap.png` | `tex_lightmap` |
| `NormalTex` | `*_Tex_*_Normalmap.png` | `tex_normal` |
| `RampTex` | `*_Tex_*_Shadow_Ramp.png` | `tex_ramp` |
| `MetalTex` | `MetalMap` | `tex_metal` |
| `SdfTex` | `FaceLightmap`（面部 SDF） | `tex_sdf` |
| `EmissionTex` | 自发光贴图 | `tex_emission` |
| `AlphaTex` | `*_Alpha` 通道 | `tex_alpha` |
| `SdfTexAlpha` | SDF 的 alpha 分量 | — |

**数值参数**（参考文件里是 Math 节点上的常量）

| 插件接口 | 参考文件里的位置 | 参考值 | 组参数名 |
|---|---|---|---|
| `Light Euler` | `Light Vecter` 组的 `合并 XYZ` | `(-0.34177, 0.67079, -140.36)` | `light_euler` |
| `Light Intensity` | `Light Normol` 组 | 1.0 | `light_intensity` |
| `Base Brightness` | `Base Color.自发光.Strength` | **0.2**（插件默认 1.0，见下） | `base_brightness` |
| `AO Bias` | Lightmap 的偏移 | 0.1 | `ao_bias` |
| `AO Smooth Lo` | `LightmapSmoothStep.Smoothstep.t1` | **0.2** | `ao_smooth_lo` |
| `AO Smooth Hi` | `LightmapSmoothstep.Smoothstep.t2` | **0.3** | `ao_smooth_hi` |
| `AO Add` | AO 加值 | 0.1 | `ao_add` |
| `Shadow Threshold` | 阴影阈值 | 0.35 | `shadow_threshold` |
| `Spec Gloss` | `群组.014.Gloss`（Blinn-Phong） | **5.0** | `spec_gloss` |
| `Spec Darken` | `运算.006`（SUBTRACT 的常量） | **1.04** | `spec_darken` |
| `Spec Threshold` | `运算.016`（GREATER_THAN） | **0.7** | `spec_threshold` |
| `Metal Threshold` | `运算.011`（GREATER_THAN） | **0.55** | `metal_threshold` |
| `Spec Crystal Threshold` | `运算.020`（GREATER_THAN） | **0.2** | `spec_crystal_threshold` |
| `Rim Power` | `运算.019`（POWER） | **4.8** | `rim_power` |
| `Rim Looseness` | `运算.015`（MULTIPLY_ADD） | 0.2 | `rim_looseness` |
| `Rim Lo` | `Shader.SmoothStep.t1` | **0.423** | `rim_lo` |
| `Rim Hi` | `Shader.SmoothStep.t2` | **0.45** | `rim_hi` |
| `Rim Intensity` | Rim 强度 | 1.0 | `rim_intensity` |
| `Detail Strength` | `Lightmap.运算`（花纹倍率） | **8.0** | `detail_strength` |
| `Ramp Band A0..A4` | `Ramp Select.A0..A4` | **`0, 4, 3, 5, 2`** | — |
| `Ramp Band Step` | `Ramp条数` 步进 | **0.1** | — |
| `Ramp Band Base` | `Ramp条数` 基址 | **1.05** | — |
| `Halo Brightness` | 最终增益 | 1.0 | `halo_brightness` |
| `Emission Strength` | 自发光强度 | 1.0 | `emission_strength` |

**开关类**（参考文件没有，属于插件的参数暴露面）

`Spec Enable`、`Metal Enable`、`Rim Enable`、`SDF Enable`、`Alpha Enable`、
`Color Gain` + `Gain Strength`、`Tint Strength`、`Use Base Color`。

---

## 2. 内部 18 个节点组

| # | 参考文件组名 | 插件组名 | 插件实现 | 作用 |
|---|---|---|---|---|
| 1 | `SmoothStep` | `NPR_SmoothStep` | `build_smoothstep` | 归一化平滑阶跃 |
| 2 | `Lambert` | `NPR_Lambert` | `build_lambert` | 兰伯特项（6 个输出） |
| 3 | `Light Vecter` | `NPR_LightVector` | `build_light_vector` | 由欧拉角算光向量 |
| 4 | `Camera Vector` | `NPR_CameraVector` | `build_camera_vector` | 相机向量 |
| 5 | `Head Vector` | `NPR_HeadVector` | `build_head_vector` | 头部坐标系三点 |
| 6 | `Ramp Amount` | `NPR_RampAmount` | `build_ramp_amount` | Ramp 条数量 |
| 7 | `Ramp Select` | `NPR_RampSelect` | `build_ramp_select` | 按条选 Ramp |
| 8 | `Normalmap Decode` | `NPR_NormalmapDecode` | `build_normalmap_decode` | 法线解码 |
| 9 | `LightmapSmoothStep` | `NPR_LightmapSmoothStep` | `build_lightmap_smoothstep` | 光照图阶跃 |
| 10 | `Blinn-Phong` | `NPR_BlinnPhong` | `build_blinn_phong` | 高光 |
| 11 | `Normalmap` | `NPR_Normalmap` | `build_normalmap` | 法线混合 |
| 12 | `Base Color` | `NPR_BaseColor` | `build_base_color` | 基础色选择链 |
| 13 | `Lightmap` | `NPR_Lightmap` | `build_lightmap` | 光照图分解 |
| 14 | `Ramp` | `NPR_Ramp` | `build_ramp` | 阴影 Ramp |
| 15 | `Eyes Shader` | `NPR_EyesShader` | `build_eyes_shader` | 眼睛着色 |
| 16 | `Additive Detail` | `NPR_AdditiveDetail` | `build_additive_detail` | 花纹叠加 |
| 17 | `Shader` | `NPR_Shader` | `build_master` | **主组** |
| 18 | （新增） | `NPR_OutlineShader` | `build_outline_shader` | 描边纯色材质 |

**头部三点坐标**（`Head Vector` 组内硬编码）

| 插件常量 | 参考文件位置 | 值 |
|---|---|---|
| `REF_HEAD_O` | `Head Vector.合并 XYZ.002` | `(0.0, -0.011286, 1.51312)` |
| `REF_HEAD_FRONT` | `Head Vector.Front` | `(0.0, -1.01129, 1.51312)` |
| `REF_HEAD_RIGHT` | `Head Vector.Right` | `(-1.0, -0.011286, 1.51312)` |

---

## 3. 贴图命名约定

参考文件的贴图命名规律（插件的 `classify_texture()` 按此规则自动归类）：

```
*_Tex_{Part}_{Kind}.png
    Part ∈ {Face, Body01, Body, Hair, Eyes, ...}
    Kind ∈ {Diffuse, Lightmap, Normalmap, Shadow_Ramp}

MetalMap.png           → 金属遮罩      → tex_metal
FaceLightmap*.png      → 面部 SDF      → tex_sdf
Pupil01/02/03.png      → 瞳孔 A/B/C    → Tex Pupil A/B/C
裙_*.png               → 裙子专用贴图
```

**识别策略**（用户选择的行为）：**先自动读取原材质里已有的贴图按用途归类，
认不出就留空**，不猜测、不编造。

---

## 4. 与参考文件的差异清单（逐条说明原因）

| # | 差异 | 原因 |
|---|---|---|
| 1 | Rim 用 `LayerWeight + POWER` 数学式，而非 `MixShader + ShaderToRGB` | `ShaderToRGB` 在 EEVEE Next（4.2+）下对真实着色器输入返回黑色 |
| 2 | 基础色的自发光叠加改为「颜色 × 强度」 | 同上，绕开 `ShaderToRGB` |
| 3 | `NPR_BaseColor` 的两个同名 `Result` 输出改名为 `Color` / `Alpha` | 同名会让按名称连线必然歧义；identifier 仍是 `Socket_0`/`Socket_1`，顺序一致 |
| 4 | 硬编码常量与内嵌贴图提升为组接口 | 让参数可调；默认值等于参考文件实测值 |
| 5 | 颜色乘算用「拆通道 → Math → 合并」 | `Mix(MULTIPLY)` 在节点组内实测会输出**两倍**目标色，行为不可依赖 |
| 6 | 高光贡献额外乘 `MetalTex` 亮度作为遮罩 | 参考文件的高光由光照贴图驱动；不提供贴图时会退化成白色 AO 项并把画面顶白 |
| 7 | `base_brightness` 默认 1.0（参考值 0.2） | 参考文件的 0.2 是"已有贴图时的压暗系数"；插件在无贴图时贴图链输出白色占位，沿用 0.2 会把画面压成近黑。想复刻参考外观就调回 0.2 |
| 8 | 新增 `NPR_OutlineShader` 与描边系统 | 参考文件**完全没有描边实现**（0 个 Solidify、Freestyle 关闭、无 Line Art/Grease Pencil），按用户选择用倒角外壳实现 |

---

## 5. 参考文件的 EEVEE 设置（插件会对齐的部分）

| 项目 | 参考文件 | 插件行为 |
|---|---|---|
| 引擎 | EEVEE（5.x 枚举为 `BLENDER_EEVEE`） | 自检时对齐 |
| 色彩管理 | 按 `Standard` 调色 | 提供"设为 Standard"按钮，并在测试中强制 Standard |
| Freestyle | 关闭 | 不使用 |
| 合成器 | 仅有 Glare（Bloom） | 不修改用户的合成器 |
| 灯光依赖 | **无**（着色结果由固定光向量驱动） | 实测：加太阳灯前后差异 0.0000 |
