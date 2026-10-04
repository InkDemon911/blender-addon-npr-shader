# Blender NPR Shader Add-on (三渲二)

[![Blender](https://img.shields.io/badge/Blender-5.2%20LTS-orange)](https://www.blender.org/)
[![License](https://img.shields.io/badge/License-GPL--3.0--or--later-blue)](LICENSE)
[![Engine](https://img.shields.io/badge/Engine-EEVEE-green)]()

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

### 方式 A：手动复制（推荐）

把 `npr_studio` 整个目录复制到 Blender 的插件目录：

| 系统 | 路径 |
|---|---|
| Windows | `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\` |
| macOS | `~/Library/Application Support/Blender/5.2/scripts/addons/` |
| Linux | `~/.config/blender/5.2/scripts/addons/` |

然后 `编辑 → 偏好设置 → 插件`，搜索 **NPR**，勾选 **NPR Studio**。

### 方式 B：打包 zip 安装

```bash
# 在仓库根目录
zip -r npr_studio.zip npr_studio -x "npr_studio/tools/*" "npr_studio/__pycache__/*"
```

然后 `编辑 → 偏好设置 → 插件 → 从磁盘安装…` 选择这个 zip。

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
"$BLENDER" -b --factory-startup --python npr_studio/tools/tools_dev_check.py

# 2. 12 步功能测试，含 EEVEE 渲染断言（期望 fails=0）
"$BLENDER" -b --factory-startup --python npr_studio/tools/tools_func_check.py

# 3. 颜色端到端（期望 结论：✓ 正确）
"$BLENDER" -b --factory-startup --python npr_studio/tools/tools_verify_direct.py

# 4. 分支隔离：先渲染纯红对照，再逐个关分支（期望 01_all_on 即精确蓝色）
"$BLENDER" -b --factory-startup --python npr_studio/tools/tools_iso_branches.py
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

- **高光与阴影层次完全依赖光照贴图**。不提供 `*_Lightmap` / `*_Shadow_Ramp` 时画面
  是"平"的纯色 —— 这是刻意的取舍：宁可平，也不要错误地顶成一片白。
  要还原参考文件外观，请把贴图接进对应组参数。
- **描边是几何外壳方案**，对非流形 / 薄片网格可能出现穿插，建议改用修改器模式。
- **`base_brightness` 默认 1.0**，而参考文件是 0.2（那是"已有贴图时的压暗系数"）。
  插件在无贴图时贴图链输出白色占位，沿用 0.2 会把画面压成近黑。

---

## 目录结构

```
.
├── npr_studio/                 # 插件本体（复制这个目录即可安装）
│   ├── __init__.py             #   注册入口、模块加载顺序、节点组构建兜底
│   ├── utils.py         (571)  #   插槽解析、连线、贴图识别、日志
│   ├── properties.py    (629)  #   数据模型：材质组/材质引用/候选材质/设置/日志
│   ├── shader_nodes.py (1937)  #   ★ 18 个 Shader 节点组的 Python 构建器
│   ├── outline.py       (350)  #   描边：Solidify 倒角外壳 + 修改器
│   ├── presets.py       (262)  #   8 个预设组
│   ├── core.py          (680)  #   应用引擎：材质生成、贴图接线、参数下发、反读
│   ├── operators.py     (644)  #   31 个操作符
│   ├── ui.py            (609)  #   15 个面板 + 4 个 UIList
│   └── tools/                  #   验证与诊断脚本（不参与插件运行）
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
