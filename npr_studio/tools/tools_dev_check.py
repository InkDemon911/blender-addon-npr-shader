"""开发自检：导入插件模块、构建节点组、比对参考文件的接口与结构。

用法：
    blender -b --factory-startup --python npr_studio/tools/tools_dev_check.py
    # 也可显式指定插件父目录（默认自动取脚本的上上级目录）：
    blender -b --factory-startup --python npr_studio/tools/tools_dev_check.py -- <插件父目录>
"""
import sys
import os
import traceback

argv = sys.argv
# 默认把"插件父目录"推断为脚本所在目录的上两级（tools/ → npr_studio/ → 仓库根）
plugin_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "--" in argv:
    rest = argv[argv.index("--") + 1:]
    if rest:
        plugin_parent = rest[0]

if plugin_parent not in sys.path:
    sys.path.insert(0, plugin_parent)

print("PLUGIN PARENT:", plugin_parent)

import bpy

# ---------------------------------------------------------------- 1. 构建
shader_nodes = None
try:
    import npr_studio
    from npr_studio import shader_nodes, utils
    print("IMPORT OK ->", npr_studio.bl_info["name"], npr_studio.bl_info["version"])
except Exception:
    traceback.print_exc()
    sys.exit("IMPORT FAILED")

report = shader_nodes.ensure_all(force=True)
print("\nBUILT  :", len(report["built"]))
print("SKIPPED:", len(report["skipped"]))
if report["errors"]:
    print("ERRORS :")
    for e in report["errors"]:
        print("   ", e)
if report.get("wiring"):
    print("WIRING FAILURES (%d):" % len(report["wiring"]))
    for item in report["wiring"][:40]:
        print("   ", item)

print("\n%-28s %6s %6s" % ("GROUP", "NODES", "LINKS"))
for name, nodes, links, current in shader_nodes.group_summary():
    print("%-28s %6d %6d %s" % (name, nodes, links, "" if current else "<STALE>"))

# ---------------------------------------------------------------- 2. 参考文件接口对比
REF_INTERFACES = {
    "NPR_Shader": {
        "out": [("Emission", "NodeSocketShader")],
        "in": [("Face", "NodeSocketFloat"), ("Body01", "NodeSocketFloat"),
               ("Body", "NodeSocketFloat"), ("Hair", "NodeSocketFloat"),
               ("Eyes", "NodeSocketFloat"), ("Crystal", "NodeSocketFloat")],
    },
    "NPR_Lambert": {
        "out": [("NoL", "NodeSocketFloat"), ("Max(0,NoL)", "NodeSocketFloat"),
                ("Pow(NoL*0.5+0.5,2)", "NodeSocketFloat"),
                ("Pow(MAx(0,NoL)*0.5+0.5,2)", "NodeSocketFloat"),
                ("NoL*0.5+0.5", "NodeSocketFloat"),
                ("Smoothstepk(0,0.14,NoL+0.5)", "NodeSocketFloat")],
        "in": [("NoL", "NodeSocketFloat")],
    },
    "NPR_SmoothStep": {
        "out": [("Value", "NodeSocketFloat")],
        "in": [("t1", "NodeSocketFloat"), ("t2", "NodeSocketFloat"), ("x", "NodeSocketFloat")],
    },
    "NPR_HeadVector": {
        "out": [("Right", "NodeSocketVector"), ("Front", "NodeSocketVector"), ("Above", "NodeSocketVector")],
        "in": [],
    },
    "NPR_LightVector": {"out": [("Vector", "NodeSocketVector")], "in": []},
    "NPR_CameraVector": {"out": [("Vector", "NodeSocketVector")], "in": []},
    "NPR_NormalmapDecode": {"out": [("Normal", "NodeSocketVector")], "in": [("Normal", "NodeSocketColor")]},
    "NPR_RampAmount": {"out": [("Value", "NodeSocketFloat")], "in": [("Value", "NodeSocketFloat")]},
    "NPR_BlinnPhong": {"out": [("Blinn-Phong", "NodeSocketFloat")], "in": []},
    "NPR_EyesShader": {"out": [("Result", "NodeSocketColor")], "in": []},
    "NPR_AdditiveDetail": {"out": [("Result", "NodeSocketColor")], "in": []},
    "NPR_Lightmap": {
        "out": [("红", "NodeSocketFloat"), ("绿", "NodeSocketFloat"),
                ("蓝", "NodeSocketFloat"), ("Alpha", "NodeSocketFloat")],
        "in": [],
    },
}

print("\n=== 接口一致性检查（与参考文件对比）===")
failures = []
for group_name, spec in REF_INTERFACES.items():
    tree = bpy.data.node_groups.get(group_name)
    if tree is None:
        failures.append("%s 不存在" % group_name)
        continue
    got_out = [(s.name, s.socket_type) for s in tree.interface.items_tree
               if getattr(s, "item_type", "") == 'SOCKET' and s.in_out == 'OUTPUT']
    got_in = [(s.name, s.socket_type) for s in tree.interface.items_tree
              if getattr(s, "item_type", "") == 'SOCKET' and s.in_out == 'INPUT']
    for name, stype in spec["out"]:
        if (name, stype) not in got_out:
            failures.append("%s 缺少输出 %s(%s)" % (group_name, name, stype))
    for name, stype in spec["in"]:
        if (name, stype) not in got_in:
            failures.append("%s 缺少输入 %s(%s)" % (group_name, name, stype))
    print("  %-24s out=%d in=%d" % (group_name, len(got_out), len(got_in)))

# ---------------------------------------------------------------- 3. Shader 组实测数值
print("\n=== 实测着色数值（与参考文件常量比对）===")
tree = bpy.data.node_groups.get("NPR_Shader")
if tree:
    for name in ("Light Normol", "群组.005", "群组.007", "群组.013", "群组.014",
                 "SmoothStep", "映射范围.002", "运算.006", "运算.011", "运算.016",
                 "运算.019", "运算.020"):
        node = tree.nodes.get(name)
        if node is None:
            print("  %-18s <缺失>" % name)
            continue
        props = []
        if hasattr(node, "operation"):
            props.append("op=%s" % node.operation)
        for sock in node.inputs:
            try:
                val = sock.default_value
            except AttributeError:
                continue
            if isinstance(val, float) and val not in (0.0, 0.5):
                props.append("%s=%.5g" % (sock.name, val))
        if node.bl_idname == 'ShaderNodeGroup' and node.node_tree:
            props.append("group=%s" % node.node_tree.name)
        print("  %-18s %s" % (name, "  ".join(props)))

# ---------------------------------------------------------------- 4. 依赖组连线自检
print("\n=== 悬空 / 无效检查 ===")
for name in shader_nodes.BUILD_ORDER:
    t = bpy.data.node_groups.get(name)
    if t is None:
        continue
    bad = [l for l in t.links if not l.is_valid]
    if bad:
        failures.append("%s 有 %d 条无效连线" % (name, len(bad)))
    # 每个组必须有 GroupOutput 且至少一条连线
    if utils.group_output_node(t) is None:
        failures.append("%s 缺少 Group Output 节点" % name)
    if len(t.links) == 0:
        failures.append("%s 没有任何连线" % name)

if failures:
    print("\n!!! 失败项 %d 条：" % len(failures))
    for f in failures:
        print("   -", f)
else:
    print("  全部通过")

# ---------------------------------------------------------------- 5. 接口名字绑定检查
# 材质层通过这些名字写参数；任何一个名字不存在都会导致参数被静默写错插槽。
print("\n=== 材质层参数名 ↔ 主组接口 绑定检查 ===")
try:
    from npr_studio import core
    master = bpy.data.node_groups.get("NPR_Shader")
    if master is None:
        failures.append("NPR_Shader 不存在，无法做绑定检查")
    else:
        have = {sock.name for sock in master.interface.items_tree
                if getattr(sock, "item_type", "") == 'SOCKET' and sock.in_out == 'INPUT'}
        needed = []
        needed += [socket for _attr, socket, _role in core.MASTER_TEXTURE_SLOTS]
        needed += [socket for _attr, socket in core.MASTER_VALUE_SLOTS]
        needed += [socket for _attr, socket in core.MASTER_COLOR_SLOTS]
        needed += [socket for _attr, socket in core.MASTER_FLAG_SLOTS]
        needed += ["Light Euler", "Light Intensity", "Rim Intensity", "SdfTexAlpha",
                   "AlphaTex", "Alpha Enable"] + list(utils.MASK_PARTS)
        missing = sorted({name for name in needed if name not in have})
        if missing:
            failures.append("主组缺少接口：%s" % ", ".join(missing))
            print("  缺少：", ", ".join(missing))
        else:
            print("  全部 %d 个接口名字都能对上" % len(set(needed)))

        # 反向检查：主组里是否有从未被使用的接口（提示拼写错误）
        unused = sorted(have - set(needed) - {"Crystal"})
        if unused:
            print("  提示：以下主组接口未被材质层使用（确认是否有意保留）：%s"
                  % ", ".join(unused))
except ImportError as exc:
    print("  跳过绑定检查：", exc)

print("\nDEV_CHECK_DONE failures=%d" % len(failures))
