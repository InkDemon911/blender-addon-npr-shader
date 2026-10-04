# 参考文件解析报告 — OdetteV3.blend

来源文件：`OdetteV3.blend`（12,031,893 bytes, sha256 `8b189864…b588f4`）
解析环境：Blender 5.2.0 LTS（`fbe6228777e7`），`--factory-startup`，脚本化遍历 API 导出。
原始导出物：`E:\deepseek-workspace\npr-ref\dump\`（18 组 JSON）、`E:\deepseek-workspace\npr-ref\spec\`（可读节点规格）。

---

## 0. 文件整体情况

| 项目 | 值 |
|---|---|
| 渲染引擎 | `BLENDER_EEVEE`（Blender 5.2 枚举里**只有** `BLENDER_EEVEE`，即 EEVEE Next 单一引擎） |
| 色彩管理 | `view_transform = Standard`，`look = None`，`display_device = sRGB` |
| 采样 | `taa_render_samples = 16` |
| 阴影 | `use_shadows = True`，`shadow_pool_size = 1024`，`shadow_ray_count = 1`，`shadow_step_count = 6` |
| 光线追踪 | `use_raytracing = False`，`ray_tracing_method = SCREEN` |
| Fast GI | `use_fast_gi = True`，`fast_gi_method = GLOBAL_ILLUMINATION`，`fast_gi_quality = 0.25` |
| Bloom | **不在 EEVEE 里**（5.x 已移除 `use_bloom`），而是合成器节点组 `合成器节点` 里的 Glare(Bloom, Quality=High, Smoothness=0.1, Threshold=10, Iterations=3, Fade=0.9) |
| Freestyle | `render.use_freestyle = False`，无 `bpy.data.linestyles` |
| 描边 | **完全没有**：无 Solidify 修改器（0 个）、无 Freestyle、无 Grease Pencil、无 Line Art 材质、无合成器边缘检测 |
| 模型规模 | 1358 个物体（其中 1190+ 为 MMD 物理刚体 `mmd_tools_rigid_*`） |
| 材质 | 49 个，其中 39 个使用同一个 `Shader` 节点组 |
| 图像 | 28 个 image datablock，全部 **packed** |
| UV | 每个网格 3 套：`UVMap`（主贴图）、`UV1`（Shadow_Ramp 用）、`UV2`（预留/金属） |

## 1. 节点组清单（18 个）

| 组名 | 用户数 | 节点/连线 | 角色 |
|---|---|---|---|
| **`Shader`** | 39 | 111 / 165 | 主着色器，材质唯一入口，输出 **Emission** |
| `Base Color` | 3 | 35 / 37 | 5 部位基础色贴图选择 + 合并 Alpha |
| `Lightmap` | 3 | 17 / 24 | 5 部位光照贴图选择，分离 R/G/B/A |
| `Normalmap` | 5 | 15 / 14 | 4 部位法线贴图选择 + DiffuseBias(=B 通道) |
| `Normalmap Decode` | 4 | 13 / 15 | 手写解码 → 重组为法线贴图输入 |
| `Ramp` | 1 | 13 / 13 | 3 部位 Shadow_Ramp 选择（Closest + EXTEND） |
| `Ramp Select` | 1 | 16 / 22 | 用 Mask 在 A0..A4 五个"条数"间阶梯插值 |
| `Ramp条数` | 5 | 8 / 8 | 单个"条数"→ 归一化 Ramp 坐标 |
| `Blinn-Phong` | 1 | 11 / 15 | 高光 |
| `Lambert` | 2 | 9 / 13 | NoL 派生量 |
| `LightmapSmoothStep` | 1 | 3 / 3 | Lightmap.g 直通 + smoothstep(0.2,0.3) |
| `Light Vecter` | 4 | 5 / 3 | 主光方向（固定欧拉旋转 +Z） |
| `Camera Vecter` | 1 | 6 / 4 | 视方向（转世界空间并归一化） |
| `Head Vector` | 2 | 11 / 11 | 头部坐标系 Right/Front/Above |
| `SmoothStep` | 3 | 9 / 12 | smoothstep(t1,t2,x) 通用实现 |
| `Eyes Shader` | 1 | 7 / 5 | 3 张瞳孔贴图 ADD 叠加 |
| `NodeGroup` | 2 | 9 / 7 | 4 张裙摆花纹贴图 ADD 叠加 |
| `合成器节点` | 1 | 6 / 6 | 合成器：RenderLayer → Glare(Bloom) → AlphaOver |

## 2. 主组 `Shader` 的接口（唯一对外接口 —— 关键结论）

```
INPUT  NodeSocketFloat  Face      default 0.0
INPUT  NodeSocketFloat  Body01    default 0.0
INPUT  NodeSocketFloat  Body      default 0.0
INPUT  NodeSocketFloat  Hair      default 0.0
INPUT  NodeSocketFloat  Eyes      default 0.0
INPUT  NodeSocketFloat  Crystal   default 0.0
OUTPUT NodeSocketShader Emission
```

**没有贴图接口，没有颜色接口。** 39 个材质节点的这些输入**全部保持默认值**（实测 `肌`/`髮`/`裙`/`目`/`金属`/`肌1` 实例值一致），也就是说——

> 参考文件里"某个部位长什么样"**完全由组内部那 5 套贴图节点（label = Body/Body01/Face/Hair/Eyes）决定**，材质实例之间没有任何参数差异。部位切换靠 `Face/Body01/Body/Hair/Eyes` 这 5 个 mask 做 Mix 因子选择，`Crystal` 控制高光分支。

因此：**UI 上的每个贴图槽 / 颜色 / 参数，都是插件新增的暴露面，但底层节点拓扑与默认值必须严格复刻参考文件。** 这就是 README 里"变量映射关系"要说明的核心。

## 3. 着色算法链路（`Shader` 组内部，按功能帧分组）

参考文件用 NodeFrame 分成 6 组：`SDF`、`Base Color`、`AO`、`Specular`、`Ramp`、`Rim`。

```
光方向 L      = Light Vecter.Vector                = rotate((0,0,1), euler(-0.34177, 0.67079, -140.36))
法线   N      = Normalmap Decode(Normalmap(masks).Normol Map)
NoL           = dot(L, N)

AO 帧:
  LightmapG   = Lightmap(masks).绿
  smoothAO    = smoothstep(0.2, 0.3, LightmapG)
  NoLBias     = clamp01(NoL + Normalmap.DiffuseBias)
  x           = map_range(NoLBias, from_min=LightmapG-0.1, from_max=LightmapG+0.1, clamp)   # AO / LightmapSmoothStep
  x           = x * smoothAO
  ao          = clamp01(x + 0.1)

高光 AoM 链:
  s           = Blinn-Phong(masks, Gloss) = max(dot(normalize(V+L), N), 0) ^ Gloss
  sM          = mix(0, s, Crystal)
  LmB         = Lightmap.蓝 ; LmR = Lightmap.红
  gateDark    = (1.04 - sM) < LmB
  baseDim     = BaseColor.Result * (sM * LmB)
  aoCol       = mix( LmR * gateDark, baseDim, (LmR > 0.7) )          # Mix 因子 crystal
  specMasked  = BaseColor.Result * MetalMaskTex( N→camera 空间 remap )
  result      = mix( aoCol, specMasked, (LmR > 0.55) )

阴影带 Ramp 帧:
  rampV       = (Face mask) → 映射范围(to_min = RampSelect(Lightmap.Alpha, A1..A4), to_max = 0.35)
  rampUV      = (X = 映射范围(SDF result, to_min = x*smoothAO, to_max = SDF test), Y = rampV)
  rampCol     = Ramp(masks, rampUV).Result        # Closest 采样 256x20 的 Shadow_Ramp
  baseRamped  = rampCol * BaseColor.Result
  result      = mix( result, baseRamped, 映射范围(SDF...) )            # Mix 标签 'Ramp Mask'
  aoMix       = ADD(result, 混合.007)

边缘光 Rim 帧:
  facing      = LayerWeight.Facing ^ 4.8
  rimColor    = BaseColor.Result
  rim         = MixShader(Factor=facing, Shader=Transparent, Shader2=Emission(rimColor))
  rimRGB      = ShaderToRGB(rim)
  final       = ADD( aoMix, rimRGB )                                   # → 自发光(Emission) → Group Output
  # 同一条 final 也接到 BsdfDiffuse 仅作视口预览
```

其中 SDF 帧（面部阴影）：

```
headAbove   = Head Vector.Above
proj        = project(L, headAbove)          # 光方向投影到头部上方向
delta       = L - proj
sRight      = sign(dot(delta, Head.Right))
uv          = UVMap.UV * (sRight, 1, 1) * (-1, 1, 0)
alpha       = SDF 贴图(uv).Alpha             # Avatar_Girl01_Tex_FaceLightmap.png
frontDot    = dot(delta, Head.Front)
fac         = frontDot * 0.5 + 0.5 - 0.5
sdfMask     = alpha > fac
```

## 4. 固定数值（默认值必须复刻）

| 位置 | 参数 | 值 |
|---|---|---|
| `Shader`/AO | `映射范围.001` from_min/from_max 偏置 | `LightmapG ∓ 0.1` |
| `Shader`/Specular | `运算.006` 被减常数 | `1.04` |
| `Shader`/Specular | `运算.011` 阈值 | `0.55` |
| `Shader`/Specular | `运算.016` 阈值 | `0.7` |
| `Shader`/Specular | `运算.020` 阈值 | `0.2` |
| `Shader`/Specular | Blinn-Phong `Gloss` | `5` |
| `Shader`/Specular | 法线→相机空间 remap | `v*0.5+0.5` |
| `Shader`/Rim | `运算.019` POWER 指数 | `4.8` |
| `Shader`/Rim | `LayerWeight.Blend` | `0.5` |
| `Shader`/SDF | SmoothStep `t1,t2` | `0.423, 0.45` |
| `Shader`/Spec | SmoothStep `t1,t2` | `0.423, 0.45` |
| `Shader`/Ramp | `映射范围.002` to_max | `0.35` |
| `Shader`/Ramp | Ramp Select `A1..A4` | `4, 3, 5, 2` |
| `Light Vecter` | 欧拉旋转 (X,Y,Z) | `-0.34177, 0.67079, -140.36` |
| `Head Vector` | O / Front / Right 坐标 | `(0,-0.011286,1.51312)` / `(0,-1.01129,1.51312)` / `(-1,-0.011286,1.51312)` |
| `Lambert` | Smoothstep `t2` | `1.14`（t1=0） |
| `LightmapSmoothStep` | t1,t2 | `0.2, 0.3` |
| `Lightmap` | `运算` 倍数（裙摆花纹） | `8` |
| `Base Color` | `自发光.Strength` | `0.2` |
| `Normalmap Decode` | 法线贴图节点 | `space=TANGENT, convention=OPENGL, base=DISPLACED` |
| `Ramp` | 采样方式 | `interpolation=Closest, extension=EXTEND, projection=FLAT` |
| 所有 Mix 节点 | `clamp_factor` | `True` |

### `SmoothStep` 组数学
```
t = clamp01((x - t1) / (t2 - t1))
out = t*t * (3 - 2t)      # 实现为 (t^2) * (1 - t*2 ... ) 逐步 Math，结果等价
```

### `Ramp条数` 组数学
```
A = 1.05 - 0.1 * value
B = A - 0.5
out = Mix(blend_type=COLOR, A, B)     # 因子未连接 → 取 A
```
即 `条数 4 → 0.65`，`条数 3 → 0.75`，`条数 5 → 0.55`，`条数 2 → 0.85`。

### `Ramp Select` 阶梯
```
mask > 0.25 → A1 ; mask > 0.45 → A2 ; mask > 0.65 → A3 ; mask > 0.95 → A4 ; 否则 A0
（逐级 Mix，Factor 为布尔比较结果）
```

### `Head Vector` 组
```
Right = normalize((-1, -0.011286, 1.51312) - (0, -0.011286, 1.51312))
Front = normalize((0, -1.01129,   1.51312) - (0, -0.011286, 1.51312))
Above = cross(Right, Front)
```

### `Blinn-Phong` 组
```
H = normalize(CameraVecter.Vector + LightVecter.Vector)
s = max(dot(H, NormalmapDecode(Normalmap(masks).Normol Map)), 0) ^ Gloss
```

### `Normalmap Decode` 组
```
v   = normal * 2 - 1
z   = sqrt(max(0, 1 - min(v.x² + v.y², 1)))
col = (v.xy, z) * 0.5 + 0.5
→ NormalMap 节点(space=TANGENT, convention=OPENGL, base=DISPLACED) → Normal
```

## 5. 贴图命名规约（来自 packed 图像实测）

| 用途 | 命名 | 色彩空间 | 典型尺寸 |
|---|---|---|---|
| 基础色 | `*_Tex_{Part}_Diffuse.png` | sRGB | 1024² |
| 光照/阴影贴图 | `*_Tex_{Part}_Lightmap.png` | **Non-Color** | 1024² |
| 法线 | `*_Tex_{Part}_Normalmap.png` | **Non-Color** | 1024² |
| 阴影 Ramp | `*_Tex_{Part}_Shadow_Ramp.png` | sRGB | **256 × 20** |
| 面部 SDF | `Avatar_Girl01_Tex_FaceLightmap.png` | sRGB | 1024² |
| 金属/高光蒙版 | `Avatar_Tex_MetalMap.png` | Non-Color | 256² |
| 瞳孔 | `*_Tex_Pupil0{1,2,3}_Diffuse.png` | sRGB | 256² |
| 裙摆花纹叠加 | `裙_*.png`（4 张） | sRGB | 2048² |

部位枚举固定为：`Face`, `Body01`, `Body`, `Hair`, `Eyes`（+ `Crystal` 布尔分支）。

## 6. 材质设置实测

- `surface_render_method`：`DITHERED`（不透明/镂空）或 `BLENDED`（半透明，如眼透、金属、裙2_w）
- `use_transparent_shadow`、`use_backface_culling` 等保持默认
- 材质节点只有 2 个：一个 `ShaderNodeGroup` + 一个 `ShaderNodeOutputMaterial`
- 43/49 材质因此是"一个组节点直连输出"的极简结构
- `肌1`/`眼透` 等少数材质在组外额外接了 Principled/MixShader/透明 BSDF 做丝袜细节与眼球透明，**不属于节点组本体**

## 7. 结论：必须向用户确认的缺口

1. **参考文件不含任何描边（outline）实现** —— 无 Solidify / 无 Freestyle / 无 Line Art / 无合成器边缘检测。因此描边部分的"严格模仿参考文件"无法执行，需要用户选择技术路线或补充参考。
2. 参考文件走 **多部位合一**（一套组服务 Face/Body01/Body/Hair/Eyes 五个部位，用 mask 选择），而需求里的"材质组（衣服/头发/身体/眼睛）"是**材质集合**的概念 —— 两者是正交的：本插件把"参考部位"作为每个材质组的 `part` 属性，从而既能一对一，也能一对多复用同一套内部拓扑。
3. 参考文件把贴图**内嵌在组内部**，而需求要求每个组面板暴露贴图槽 —— 插件将把参考里的每个内嵌贴图节点**提升为组接口**，节点拓扑与默认值不变，仅增加暴露面。
