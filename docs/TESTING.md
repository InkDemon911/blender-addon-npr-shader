# 测试步骤与实测结果（TESTING）

所有测试都在 Blender **5.2.0 LTS**（hash `fbe6228777e7`）下以
`-b --factory-startup` 后台模式运行，结果可复现。

## 0. 环境

```powershell
$blender = "D:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
$ws      = "<工作区路径>"
```

## 1. 结构检查（`tools_dev_check.py`）

```powershell
& $blender -b --factory-startup --python "npr_shader\tools_dev_check.py" -- $ws
```

**覆盖内容**

1. 注册插件，`ensure_all(force=True)` 重建全部节点组
2. 逐组统计节点数 / 连线数 / **无效连线数**（必须为 0）
3. 把每个节点组的接口（名称、类型、默认值）与参考文件 `OdetteV3.blend` 的规格逐条比对
4. 检查"材质层参数名 ↔ 主组接口名"全部能绑定
5. 打印未被材质层使用的主组接口（提示项，不算失败）

**期望输出**

```
BUILT  : 18
=== 接口一致性检查（与参考文件对比）===
  全部通过
=== 材质层参数名 ↔ 主组接口 绑定检查 ===
  全部 53 个接口名字都能对上
DEV_CHECK_DONE failures=0
```

## 2. 功能检查（`tools_func_check.py`）

```powershell
& $blender -b --factory-startup --python "npr_shader\tools_func_check.py" -- $ws
```

**12 个步骤**

| # | 步骤 | 检查要点 |
|---|---|---|
| 1 | 注册插件 | `register()` 后 Scene 属性、Operator、Panel 齐全 |
| 2 | 准备场景 | 相机 / 物体 / 原始材质 / EEVEE 渲染设置 |
| 3 | 创建预设组 | 8 个预设（衣服/头发/身体/眼睛/皮肤/金属/水晶/特效）建成 |
| 4 | 组增删改查 | 新建 / 重命名 / 复制 / 排序 / 删除 |
| 5 | 材质分配与一键应用 | 替换模式、材质槽、**mask 输入（Body=1 其余 0）**、贴图识别回填 |
| 6 | 应用整组 / 反读 / 重置 | 整组参数落盘、从材质读回、重置为参考默认 |
| 7 | 描边 | 生成独立对象、`use_flip_normals`、偏移量、材质背面剔除、**重复执行不重复创建** |
| 8 | 渲染验证 | 取景自检 + 显式蓝色渲染断言 |
| 9 | 灯光无关性 | 加太阳灯前后渲染差异必须 ≈ 0 |
| 10 | 其它模式与撤销 | 追加 / 仅描边模式，材质槽数量变化符合预期 |
| 11 | 自检操作符与渲染设置 | 自检、`View Transform = Standard` |
| 12 | 卸载插件 | `unregister()` 后干净移除 |

**关键断言（第 8 步）**

```
对照纯红发光 中心线性均值 = (0.9993, 0.0000, 0.0000)   ← 取景/几何自检
蓝色高亮     中心线性均值 = (0.1000, 0.1999, 0.9993)   ← 期望 (0.1, 0.2, 1.0)
加入太阳光后 中心线性均值 = (0.1000, 0.1999, 0.9993)   ← 与上一步完全相同
```

**期望输出**

```
步骤数：12，失败项：0
FUNC_CHECK_DONE fails=0
```

> 说明：第 8a 步的"默认参数"渲染会带上第 5 步自动识别到的贴图，
> 贴图可能是深色，因此该步**只记录不断言**；颜色正确性由第 8b 步的
> 显式蓝色用例断言。

## 3. 颜色端到端（`tools_verify_direct.py`）

```powershell
& $blender -b --factory-startup --python "npr_shader\tools_verify_direct.py"
```

直接给材质挂 `NPR_Shader` 主组，写入一组确定的实参，渲染后断言：

```
渲染中心线性 = (0.0999, 0.1981, 1.0)   期望 (0.1, 0.2, 1.0)
结论：✓ 正确
```

## 4. 分支隔离（`tools_iso_branches.py`）

用于回归定位"颜色被顶白"类问题：先渲染纯红对照确认取景，再逐个关闭分支。

```powershell
& $blender -b --factory-startup --python "npr_shader\tools_iso_branches.py"
```

**期望输出**（关键：`01_all_on` 就必须是精确蓝色）

```
00_control_red        = (1.0, 0.0, 0.0)          ← 取景自检
01_all_on             = (0.0999, 0.1981, 1.0)    ← 全分支开启
02_spec_off           = (0.0999, 0.1981, 1.0)
03_spec_rim_off       = (0.0999, 0.1981, 1.0)
04_spec_rim_metal_off = (0.0999, 0.1981, 1.0)
05_plus_smoothstep    = (0.0999, 0.1981, 1.0)
```

> 这个脚本的价值在于：**先渲染一个已知正确的对照**（纯红）再测目标材质。
> 开发中多次出现"把背景像素当成渲染结果"的误判，对照渲染能立刻排除取景问题。

## 5. 视觉确认（可选）

后台渲染出的 PNG 在 `npr-ref/render_out/`。`tools_ascii_view.py` 可以把任意
PNG 转成终端字符缩略图（按最大通道着色，R/G/B/W/w/. 分别代表红/绿/蓝/亮灰/暗灰/背景）：

```powershell
& $blender -b --factory-startup --python "npr_shader\tools_ascii_view.py" -- "<png 路径>"
```

## 6. 人工验收清单（headless 无法覆盖）

- [ ] N 面板能看到 **三渲二 / NPR** 标签页，各面板折叠正常
- [ ] ② 材质组的 UIList 可以点选、▲▼ 排序生效
- [ ] 「新建组」弹窗能输入名称、选部位、选模板
- [ ] 「一键应用」后 `Info` 里有中文提示
- [ ] 一键应用后 `Ctrl+Z` 能完整回退
- [ ] 描边厚度滑块拖动时视口实时更新
- [ ] ② 的「复制」「删除」有确认弹窗
- [ ] ⑤ 的「重建节点组」在已有材质上执行后不报错

## 7. 回归建议

改动着色器后**至少**跑 `tools_dev_check.py` + `tools_iso_branches.py`：
前者保证结构与接口没被改坏，后者保证颜色链没有被重新顶白。
