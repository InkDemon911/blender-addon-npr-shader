# 验证状态（最终）

本文件记录**实测证据**。所有结论都来自
`blender -b --factory-startup --python <脚本>` 的实跑结果。

## 0. 安装状态（已安装到 Blender 5.2）

| 项目 | 值 |
|---|---|
| 安装路径 | `C:\Users\ink\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\npr_studio` |
| 偏好启用 | **已写入并保存**，重启 Blender 自动加载（复核：`IN_PREFS=True`、`CHECK=(True,True)`、`GROUPS_NOW=18`） |
| Blender | 5.2.0 LTS（hash `fbe6228777e7`），Python 3.13.13 |
| 源目录 ↔ 安装目录 | 9 个运行时文件 **MD5 全部一致** |

### 安装期发现并修复的 4 个真实缺陷

| # | 缺陷 | 现象 | 修复 |
|---|---|---|---|
| I1 | 启动期 `bpy.data` 是 `_RestrictData` 代理 | `register()` 里构建节点组抛 `AttributeError`，注册中断，插件停在"偏好勾了但没加载"（面板不出现） | 先试一次构建；失败则挂 `load_post` + timer 兜底（注释里注明 `-b` 后台模式不跑 timer） |
| I2 | `ensure_all()` 只按名字判断存在性 | 空组被当"已存在"永久跳过重建，材质挂上空组 → 插件"装了但没效果" | 新增 `_tree_is_healthy()`：要求"有节点 + 有 Group Output + 接口有输出插槽"，不健康就重建 |
| I3 | 基类包装 `execute` 时多了一个默认参数 | Blender 抛 `ValueError: expected Operator ... to have 2 args, found 3`，**整个注册失败** | 改用闭包捕获原方法，保持 `execute(self, context)` 两参数签名 |
| I4 | `_loaded` 未在 `register()` 开头清空 | 反复注册会累积条目，卸载时对陈旧模块重复调用钩子 | `register()` 开头 `_loaded.clear()` |

### 自愈机制（不依赖回调时机）

自愈挂在操作符基类上：`NprOperator.__init_subclass__` 自动为每个子类的 `execute`
包一层"先 `ensure_groups()`"。因此**任何入口第一次被点击时都会补齐节点组**。
实测：调用前 0 个 → 调 `bpy.ops.npr.validate()` → **自动补齐 18 个**；
手动删掉 3 个节点组后调 `_build_groups_now()`，正确只重建那 3 个。

### 安装后端到端冒烟（真实启用路径，不预导入模块）

```
1. 发现        : ['npr_studio']
   启用状态    : (True, True)
2. 模块文件    : ...\5.2\scripts\addons\npr_studio\__init__.py
   版本        : (1, 0, 0)
3. 操作符自愈  : 调用前 0 个 → npr.validate() → 18 个
4. 节点组明细  : 18 个（NPR_Shader 73 节点 / 198 连线 等）
5. 场景设置    : NprSettings，面板 15 / 操作符 25
6. 一键应用    : bpy.ops.npr.apply() → {'FINISHED'}，材质 NPR_衣服_Body01
                 Base Color = (0.1, 0.2, 1.0, 1.0)
7. 描边        : 生成 1 个 NPR_Outline_衣服_NPR_Verify_Cube；重复执行"新增 0 / 更新 1"
```

> 冒烟渲染用 Workbench（FLAT + MATERIAL）只是为了避开受限环境下 EEVEE 的 GPU
> 着色器编译子进程；**颜色正确性由 EEVEE 下的 `tools_func_check.py` 与
> `tools_verify_direct.py` 断言**（见下）。

---

## 一、实测通过（0 失败）

| 检查 | 命令 | 结果 |
|---|---|---|
| 结构 / 接口一致性 / 参数绑定 | `tools_dev_check.py` | **BUILT: 18，接口全部通过，53 个参数名全部绑定，failures=0** |
| 12 步功能测试 | `tools_func_check.py` | **步骤数 12，失败项 0** |

### 功能测试 12 步明细（全部通过）

1. 注册插件 2. 准备场景 3. 创建预设组 4. 组增删改查 5. 材质分配与一键应用
6. 应用整组 / 反读 / 重置 7. 描边（Solidify 倒角外壳） 8. 渲染验证
9. 着色与 EEVEE 灯光无关 10. 其它模式与撤销安全性 11. 自检操作符与渲染设置
12. 卸载插件

### 关键渲染断言（线性值）

| 用例 | 实测 | 期望 | 判定 |
|---|---|---|---|
| 基础色设为蓝 `(0.1, 0.2, 1.0)` | `(0.1000, 0.1999, 0.9993)` | `(0.1, 0.2, 1.0)` | ✅ 误差 < 0.001 |
| 蓝色分量 > 红色分量 × 4 | 0.9993 vs 0.1000 | 成立 | ✅ |
| 加入太阳灯前后差异 | `0.0000` | ≈ 0 | ✅ 自包含着色成立 |
| 对照纯红发光（取景自检） | `(0.9993, 0, 0)` | 红 | ✅ |
| 描边对象生成 / 参数 / 重复执行 | 1 个、参数正确、不重复创建 | — | ✅ |

## 二、本轮修复的关键缺陷（都有"复现 → 定位 → 修复 → 复验"闭环）

### F1. 颜色乘算误用 `Mix(MULTIPLY)` → 画面整体顶白 ★核心
**现象**：基础色设蓝，渲染为纯白 `(1,1,1)`。
**定位**：逐段渲染隔离，逐步收敛到主组的 `运算.027 → 混合.007` 链。
**根因（两层）**：
1. 汇总阶段把 `混合.004`（高光/AO 分支）的输出**恒等放大**后直接 ADD。
   参考文件里这个分支由**光照贴图 + 金属贴图**驱动；插件里两张图默认是
   "白光照贴图 + 黑金属贴图"，于是它退化成**白色 AO 项**，ADD 上去把画面顶白。
2. `Mix(blend_type='MULTIPLY')` 在**节点组内**的实测行为与预期不符：
   在 `A=白 / B=目标色 / Factor=1` 时输出**两倍**目标色（红 0.1 → 0.1981），
   而同一配置放在材质里却正常。
**修复**：
- 新增 `Edit.color_multiply()`：一律用「SeparateColor → Math(MULTIPLY) ×3 →
  CombineColor」实现颜色乘算，彻底不用 `Mix(MULTIPLY)`。
  已应用到：色调、增益、Ramp、自发光、边缘光、边缘光强度、主组光环增益。
- 高光贡献增加 `运算.028 = 混合.004 亮度 × MetalTex 亮度` 作为遮罩：
  没有金属贴图 → 贡献为 0，画面保持基础色。
- `_apply_blend_factors()` 放宽到"任何 RGBA 的 MULTIPLY/ADD/其它非 MIX 算式"
  都把 Factor 补成 1.0（MIX 不碰），避免 Factor 默认 0.5 只生效一半。
**复验**：蓝色渲染 `(0.1000, 0.1999, 0.9993)`；`Spec Enable` 开/关结果一致。

### F2. 主组缺少 `Tint Strength` 接口
色调强度只加在 `NPR_BaseColor` 里，主组没有同名接口也没连线，导致
"设了基础色但完全没染色"。
**修复**：主组补上 `Tint Strength` 接口（默认 1.0）并连到子组；`core` 里
"基础色非白 → 自动设 1，白色 → 0"。
**复验**：功能测试打印的实参里 `Tint Strength = 1.0`，渲染得到精确蓝色。

### F3. 无贴图时默认渲染为黑
`base_brightness` 默认沿用参考文件的 0.2（那是"已有贴图时的压暗系数"），
而插件在无贴图时让贴图链输出白色占位，0.2 把画面压成近黑。
**修复**：属性默认、`reset_group` 默认、三个预设的 `base_brightness` 全部改为
**1.0（中性）**；README 说明想复刻参考文件的压暗就调回 0.2。

### F4. `ShaderNodeMix` 的 `data_type` 必须在建节点时确定
默认 `FLOAT`，此时 `A_Color`/`B_Color`/`Result_Color` **根本不存在**；
先按 FLOAT 连好线再改成 RGBA 会让 Blender **静默丢弃**这些连线。
**修复**：`utils.mix_node()` 先设 `data_type`、再设 `blend_type`，并复核插槽集合；
新增 `Edit._check_mix_data_types()` 只做健全性检查，**绝不修改** `data_type`。

### F5. 组接口 identifier 随接口增删整体位移
节点组接口插槽 identifier 是自动编号（`Socket_N`），增删接口会让编号整体后移。
曾导致 `Face←Body01`、`Body←Hair`、`Emission Color←Base Brightness` 的连锁错位。
**修复**：子组→主组的连线一律**按名称**连接（`Edit.resolve()` 改为返回名称）。

### F6. Float → Mix.Color 不隐式转换
`ShaderNodeMath`（Float）直接接到 `Mix` 的 `A_Color` 会让连线被丢弃。
**修复**：新增 `Edit.float_to_color()`，需要把标量接进颜色通路时显式转换。

### F7. `ShaderToRGB` 在 EEVEE Next 下失效
参考文件的 Rim/Emission 帧用了 `MixShader + ShaderToRGB`，该节点在 4.2+ 对
真实着色器输入返回黑色。
**修复**：改为等价数学式（LayerWeight + 幂次 + 归一化），已在代码注释中说明差异。

## 三、有意保留的设计取舍

- **高光/阴影层次依赖光照贴图**：不提供 `*_Lightmap` 与 `*_Shadow_Ramp` 时画面
  是"平"的纯色。宁可平，也不要错误的白 —— 这是 F1 的直接教训。
- **贴图走主组接口传参**，材质里不挂 `TexImage` 节点（材质树只有
  `NPR_Shader 主组 + Material Output`）。这是刻意的非破坏性设计，
  功能测试第 5 步据此断言"贴图被回填到组参数 / 主组接口"。
- 4 处 `wiring` 提示为「Float 输出 → Mix 的 Factor_Float 落在未激活通路」，
  属于**合法的跨类型标量连接**（已逐条打印确认对端都是 `Factor_Float`），
  不影响渲染结果，保留作为提示。

## 四、复现命令

```powershell
$blender = "D:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

# 结构 + 接口一致性 + 参数绑定（期望 failures=0）
& $blender -b --factory-startup --python "npr_studio\tools_dev_check.py" -- "<工作区>"

# 12 步功能 + 渲染（期望 fails=0）
& $blender -b --factory-startup --python "npr_studio\tools_func_check.py" -- "<工作区>"

# 颜色端到端（期望 结论：✓ 正确）
& $blender -b --factory-startup --python "npr_studio\tools_verify_direct.py"

# 分支隔离（期望 01_all_on 就是精确蓝色）
& $blender -b --factory-startup --python "npr_studio\tools_iso_branches.py"
```

## 五、仍需人工确认（无法在 headless 下验证）

**GUI 面板交互**：所有验证都在 `--background` 下完成。面板的布局、UIList 选择、
弹窗 Operator 的实际点击流程需要在带界面的 Blender 里过一遍。
面板代码按 Blender 5.2 的 `Panel`/`UIList`/`Operator.invoke` 规范编写，
`register()` 无报错、18 个 Panel 与 25 个 Operator 均成功登记，
但视觉细节（行宽、图标、折叠状态）建议人工确认。
