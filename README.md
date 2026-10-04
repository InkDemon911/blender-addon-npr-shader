# Blender NPR Shader Add-on (三渲二)

[![Blender](https://img.shields.io/badge/Blender-5.2%20LTS-orange)](https://www.blender.org/)
[![License](https://img.shields.io/badge/License-GPL--3.0--or--later-blue)](LICENSE)
[![Engine](https://img.shields.io/badge/Engine-EEVEE-green)]()
[![Status](https://img.shields.io/badge/Status-Testing%20%2F%20Beta-red)](docs/测试状态.md)

> ## ⚠️ 测试中（Testing / Beta）— 请先读这一段
>
> **这个插件目前处于测试阶段，有大量未经真实场景验证的部分。** 请当作可用的测试版，
> 不要直接用在有交付期限的项目上而不做备份。
>
> **已经验证过的**：18 个节点组的构建与接口一致性、着色链路的**颜色数值**、
> 12 步功能流程、插件的安装加载。这些都有自动化测试覆盖。
>
> **完全没验证过的**：
>
> | 未验证项 | 说明 |
> |---|---|
> | 🔴 **GUI 交互** | 所有测试都在**无界面**模式下跑。面板布局、鼠标点选、弹窗、滑块拖动**都没有在带界面的 Blender 里点过** |
> | 🔴 **真实模型** | 只在一个立方体上测过。**MMD / FBX / glTF / VRM 导入的模型完全没测** |
> | 🔴 **真实贴图** | 没用参考文件那 28 张 packed 贴图测过。8 个贴图槽里有 5 个**没有端到端验证** |
> | 🔴 **外观一致性** | 没和参考文件做过并排比对。数学式等价是推导的，**不是像素级比对出来的** |
> | 🔴 **跨平台 / 跨版本** | **只在 Windows + Blender 5.2.0 测过**。macOS / Linux / Blender 5.0-5.1 / 4.x 全未测 |
> | 🟡 **保存后重开** | `.blend` 保存再打开，材质组/候选列表是否正确恢复**未验证** |
> | 🟡 **描边几何健壮性** | 薄片 / 非流形 / 带骨骼动画的网格**可能穿插或断裂**，未系统测试 |
> | 🟡 **多 UV / 多物体 / 共享材质** | 参考文件有 3 套 UV，插件只用默认 UV；多物体共享材质未测 |
>
> **完整清单见 [docs/测试状态.md](docs/测试状态.md)** —— 里面逐项列了验证了什么、
> 没验证什么。**遇到问题请提 Issue，测试阶段的报错信息比什么都值钱。**

一个面向 **Blender 5.2 / EEVEE** 的**完全自包含**三渲二（NPR / toon）着色插件。

**全部 18 个 Shader 节点组都由 Python 在插件内部生成** —— 不依赖任何外部 `.blend`
文件、不依赖用户已安装的节点组资产。装上就能用，发文件不会丢节点组。

> 拓扑、接口与全部常量严格对照参考文件 `OdetteV3.blend` 实测导出。
> 逐项对照表见 [`docs/REFERENCE_MAPPING.md`](docs/REFERENCE_MAPPING.md)。

---

## 特性

- **自包含** —— 18 个节点组全部代码生成，首次使用自动补齐（缺失/损坏会自动重建）
- **一键应用** —— 4 种模式：替换 / 追加 / 仅描边 / 替换并保留贴图
- **模块化材质组** —— 一组参数管一批材质，8 个预设组（衣服/头发/身体/眼睛/脸部/睫眉/口齿/金属）
- **勾选式材质分配** —— 列出选中物体的材质，逐条勾选后加入组
- **倒角外壳描边** —— Solidify + 翻转法线 + 背面剔除 + 纯色材质，也可用修改器模式
- **自动贴图识别** —— 按文件名与色彩空间归类到 8 个贴图槽，认不出就留空（不猜）
- **着色不依赖灯光** —— 结果走 Emission，与参考文件一致（实测加灯光前后差异 `0.0000`）
- **N 面板 UI** —— 15 个面板 / 31 个操作符 / 4 个列表
- **可撤销** —— 所有操作登记到 Blender 的 undo 栈

---

## 安装

### 方式 A：下载 Release 里的 zip（最省事）

到 [**Releases**](https://github.com/InkDemon911/blender-addon-npr-shader/releases/latest) 下载
**`npr_shader-v1.0.0-beta.zip`**，然后
`编辑 → 偏好设置 → 插件 → 从磁盘安装…` 选择这个 zip 即可。

> 文件名里的 `beta` 是刻意的 —— 提醒你当前是测试版，见上方警示。

### 方式 B：手动复制目录

把仓库里的 `npr_shader` 整个目录复制到 Blender 的插件目录：

| 系统 | 路径 |
|---|---|
| Windows | `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\` |
| macOS | `~/Library/Application Support/Blender/5.2/scripts/addons/` |
| Linux | `~/.config/blender/5.2/scripts/addons/` |

然后 `编辑 → 偏好设置 → 插件`，搜索 **NPR**，勾选 **NPR Shader**。

### 方式 C：自己打包 zip

```bash
git archive --format=zip --prefix=npr_shader/ -o npr_shader.zip HEAD:npr_shader
```

顶层必须是 `npr_shader/`，否则 Blender 认不出这是插件包。

### 启用后

3D 视图按 `N`，侧栏出现 **三渲二 / NPR** 标签页。

> **节点组会在首次使用时自动补齐。** 无论何时启用插件，只要点任意一个 NPR 按钮，
> 插件都会先检查并补建 18 个节点组。看到面板却暂时没有节点组时，随便点一下按钮即可。

---

## 快速上手

```
① 按 N 打开侧栏 → 三渲二 / NPR
② 「材质组管理」→ 点「创建预设组」          ← 一次性
③ 选中角色网格
④ 「材质组管理」→ 点一下「身体」组
⑤ 「一键应用」→ 点「一键应用三渲二」
```

默认模式是 **替换并保留贴图**，会自动把原材质里的贴图按用途认出来接进去。

---

## 文档

| 文档 | 内容 |
|---|---|
| [**测试状态**](docs/测试状态.md) | ⚠️ **先读这个**：逐项列出验证了什么、**没验证什么** |
| [**使用手册**](docs/使用手册.md) | 面向使用者：13 节，从安装到调参到排错 |
| [**运行逻辑**](docs/运行逻辑.md) | 面向开发者：实现了什么 + 7 条完整工作流程 + 9 个踩坑记录 |
| [README（详细）](docs/README.md) | 完整参数文档、兼容性与已知限制 |
| [面板流程](docs/PANEL_FLOW.md) | N 面板结构与 5 条操作流程 |
| [测试步骤](docs/TESTING.md) | 4 套测试的完整步骤与期望输出 |
| [参考对照表](docs/REFERENCE_MAPPING.md) | 参考文件变量逐项映射 + 差异清单 |

---

## 测试

所有测试都需要 Blender 5.2 可执行文件。在仓库根目录运行：

```bash
BLENDER="D:/Program Files/Blender Foundation/Blender 5.2/blender.exe"   # 按需修改

# 1. 结构 + 接口一致性 + 参数绑定（期望 failures=0）
"$BLENDER" -b --factory-startup --python npr_shader/tools/tools_dev_check.py

# 2. 12 步功能测试，含 EEVEE 渲染断言（期望 fails=0）
"$BLENDER" -b --factory-startup --python npr_shader/tools/tools_func_check.py

# 3. 颜色端到端（期望 结论：✓ 正确）
"$BLENDER" -b --factory-startup --python npr_shader/tools/tools_verify_direct.py

# 4. 分支隔离：先渲染纯红对照，再逐个关分支（期望 01_all_on 即精确蓝色）
"$BLENDER" -b --factory-startup --python npr_shader/tools/tools_iso_branches.py
```

### 实测结果（Blender 5.2.0 LTS，hash `fbe6228777e7`）

| 测试 | 结果 |
|---|---|
| 结构 / 接口一致性 / 参数绑定 | 18 组全部构建，接口全部通过，**failures=0** |
| 12 步功能测试 | **12 步，失败项 0** |
| 颜色端到端 | 基础色设蓝 `(0.1, 0.2, 1.0)` → 渲染线性值 **`(0.0999, 0.1981, 1.0)`** ✓ |
| 灯光无关性 | 加太阳灯前后差异 **`0.0000`** |

> 为什么颜色断言用**线性值**：`bpy.data.images` 读回的 `pixels` 是 sRGB 编码后的数值
> （线性 0.1 读回 0.349）。测试脚本内置了 `_srgb_to_linear()` 还原，否则会把正确的
> 渲染结果误判为"颜色不对"。

---

## 与参考实现的有意差异

参考文件 `OdetteV3.blend` 的整套链路已被复刻，但以下 4 处**刻意**偏离（原因见代码注释）：

| # | 差异 | 原因 |
|---|---|---|
| 1 | Rim 用 `LayerWeight` 数学式实现，而非 `MixShader + ShaderToRGB` | `ShaderToRGB` 在 EEVEE Next（4.2+）下对真实着色器输入返回**黑色** |
| 2 | 基础色的自发光叠加改为「颜色 × 强度」 | 同上，绕开 `ShaderToRGB` |
| 3 | `NPR_BaseColor` 的两个同名 `Result` 输出改名为 `Color` / `Alpha` | 同名会让按名称连线必然歧义；identifier 仍是 `Socket_0`/`Socket_1`，顺序与参考一致 |
| 4 | 颜色乘算用「拆通道 → Math → 合并」，不用 `Mix(MULTIPLY)` | 实测 `Mix(MULTIPLY)` 在**节点组内**于 `A=白/B=目标色/Factor=1` 时输出**两倍**目标色（红 0.1 → 0.1981），同一配置放在材质里却正常 —— 行为随上下文变化，不可依赖 |

---

## 已知限制

> 下面 3 条是**设计取舍**（不是 bug）。**未验证项的完整清单**在
> [docs/测试状态.md](docs/测试状态.md)。

- **高光与阴影层次完全依赖光照贴图**。不提供 `*_Lightmap` / `*_Shadow_Ramp` 时画面
  是"平"的纯色 —— 这是刻意的取舍：宁可平，也不要错误地顶成一片白。
  要还原参考文件外观，请把贴图接进对应组参数。
- **描边是几何外壳方案**，对非流形 / 薄片网格可能出现穿插，建议改用修改器模式。
- **`base_brightness` 默认 1.0**，而参考文件是 0.2（那是"已有贴图时的压暗系数"）。
  插件在无贴图时贴图链输出白色占位，沿用 0.2 会把画面压成近黑。

---

## 测试中阶段特别说明

本插件**尚未在真实生产场景中验证**。发布这个版本的目的，是让着色核心（节点组
构建与颜色数值）这部分**已经被自动化测试覆盖**的工作可以先被别人用起来，
同时收集真实使用中的问题。

**如果你打算用它**：

1. **先在副本上试**，不要直接改你的工程文件。
2. **优先验证你自己的模型**：导入你的角色 → 一键应用 → 看外观是否符合预期。
   立方体上的测试通过**不代表**你的模型没问题。
3. **发现问题就提 Issue**，哪怕是"这个按钮点了没反应"。测试阶段最有价值的就是
   这种反馈。
4. 提 Issue 时带上：Blender 版本、操作系统、「高级 / 工具」面板里的日志、
   复现步骤。

**还没做的事**（欢迎 PR）：GUI 人工验收清单、真实模型外观比对、跨平台测试、
GitHub Actions 自动化测试。

---

## 目录结构

```
.
├── npr_shader/                 # 插件本体（复制这个目录即可安装）
│   ├── __init__.py      (142)  #   注册入口、模块加载顺序、节点组构建兜底
│   ├── utils.py         (571)  #   插槽解析、连线、贴图识别、日志
│   ├── properties.py    (707)  #   数据模型：材质组/材质引用/候选材质/设置/日志
│   ├── shader_nodes.py (1962)  #   ★ 18 个 Shader 节点组的 Python 构建器
│   ├── outline.py       (350)  #   描边：Solidify 倒角外壳 + 修改器
│   ├── presets.py       (262)  #   8 个预设组
│   ├── core.py          (698)  #   应用引擎：材质生成、贴图接线、参数下发、反读
│   ├── operators.py     (775)  #   31 个操作符
│   ├── ui.py            (669)  #   15 个面板 + 4 个 UIList
│   └── tools/                  #   验证与诊断脚本（不参与插件运行）
│       ├── tools_common.py     #     路径推断（三种目录布局通用）
│       ├── tools_dev_check.py  #     结构 / 接口一致性 / 参数绑定
│       ├── tools_func_check.py #     12 步功能测试
│       ├── tools_verify_direct.py  # 颜色端到端
│       ├── tools_iso_branches.py   # 分支隔离
│       └── tools_ascii_view.py     # PNG → 终端字符缩略图
├── docs/                       # 文档
├── reference-spec/             # 参考文件的可读规格导出（不含模型与贴图）
└── LICENSE                     # GPL-3.0-or-later
```

---

## 许可与素材

- **代码**：GPL-3.0-or-later（与 Blender 插件惯例一致），见 [LICENSE](LICENSE)。
- **不附带任何美术资源**：插件只生成节点组与材质，仓库内**不含**任何模型或贴图。
- `reference-spec/` 只包含**从参考文件导出的文本规格**（节点、连线、常量），
  用于说明实现依据，不含任何二进制素材。
- 开发期用于比对的 `OdetteV3.blend`（第三方卡通角色的模型与贴图，版权归原作者）
  **刻意未入库**，见 `.gitignore`。

---

## 致谢

着色算法来自参考文件 `OdetteV3.blend` 的节点组结构；本插件的工作是把它
**重新实现为纯 Python 生成、可参数化、可批量管理**的形式，并补齐了参考文件
没有的描边与材质组管理。
