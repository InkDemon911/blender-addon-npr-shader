"""最直接的端到端验证：材质 = NPR_Shader 主组，Base Color=蓝，渲染并断言。

每一步都打印实测值，避免"以为设上了其实没设上"。

用法：
    blender -b --factory-startup --python npr_shader/tools_verify_direct.py
"""
import os
import sys

# 让 tools_common 可导入（它与本脚本同目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools_common

# 自动向上找到"包含插件包的那一级目录"
plugin_parent = tools_common.setup()

import bpy
import npr_shader
from npr_shader import shader_nodes, utils

npr_shader.register()
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = scene.render.resolution_y = 32
scene.view_settings.view_transform = 'Standard'
scene.render.film_transparent = False
OUT = os.path.join(plugin_parent, "render_out")
os.makedirs(OUT, exist_ok=True)

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
bpy.ops.mesh.primitive_cube_add(size=1.4)
obj = bpy.context.active_object
cam_data = bpy.data.cameras.new("C")
cam = bpy.data.objects.new("C", cam_data)
scene.collection.objects.link(cam)
cam.location = (0, -3, 0)
cam.rotation_euler = (1.5707963, 0, 0)
scene.camera = cam

BLUE = (0.1, 0.2, 1.0, 1.0)

mat = bpy.data.materials.new("DirectTest")
mat.use_nodes = True
tree = mat.node_tree
for n in list(tree.nodes):
    tree.nodes.remove(n)
out = tree.nodes.new('ShaderNodeOutputMaterial')
inst = tree.nodes.new('ShaderNodeGroup')
inst.node_tree = bpy.data.node_groups[shader_nodes.G_MASTER]
tree.links.new(inst.outputs[0], out.inputs["Surface"])


def _s2l(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


SET = {
    "Body": 1.0, "Base Brightness": 1.0, "Color Gain": 1.0, "Gain Strength": 0.0,
    "Ramp Strength": 0.0, "Ramp Enable": 0.0, "Detail Strength": 0.0,
    "Emission Strength": 0.0, "Spec Enable": 0.0, "Rim Enable": 0.0,
    "Metal Enable": 0.0, "Halo Brightness": 1.0, "Crystal": 0.0,
    "BaseColorTex": (1.0, 1.0, 1.0, 1.0), "Base Color": BLUE,
}
print("写参数并复核：")
for key, value in SET.items():
    sock = utils.get_input(inst, key, -1)
    if sock is None:
        print("   %-18s 插槽缺失！" % key)
        continue
    try:
        sock.default_value = tuple(value) if isinstance(value, tuple) else value
    except (AttributeError, TypeError) as exc:
        print("   %-18s 写入失败 %s" % (key, exc))
        continue
    got = sock.default_value
    try:
        got = tuple(round(x, 3) for x in got)
    except TypeError:
        got = round(float(got), 3)
    print("   %-18s = %s" % (key, got))

obj.data.materials.clear()
obj.data.materials.append(mat)
path = "%s\\direct_test.png" % OUT
scene.render.filepath = path
bpy.ops.render.render(write_still=True)
img = bpy.data.images.load(path, check_existing=False)
w, h = img.size
px = list(img.pixels)
c = ((h // 2) * w + w // 2) * 4
lin = tuple(round(_s2l(px[c + k]), 4) for k in range(3))
print("\n渲染中心线性 = %s   期望 (0.1, 0.2, 1.0)" % (lin,))
print("结论：%s" % ("✓ 正确" if abs(lin[0] - 0.1) < 0.03 and abs(lin[2] - 1.0) < 0.03 else "✗ 不正确"))
bpy.data.images.remove(img)
print("DONE")
