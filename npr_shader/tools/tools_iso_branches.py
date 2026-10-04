"""隔离测试：在"蓝色基础色"下，把各分支逐个关掉，看谁把颜色顶成了白。

探测前先渲染纯红对照，确认取景/几何正常（避免又把背景误读成结果）。

用法：
    blender -b --factory-startup --python npr_shader/tools_iso_branches.py
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
from npr_shader import presets, utils, shader_nodes, core

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


def _s2l(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


SEQ = [0]


def render(tag):
    SEQ[0] += 1
    path = "%s\\iso3_%s_%02d.png" % (OUT, tag, SEQ[0])
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = list(img.pixels)
    c = ((h // 2) * w + w // 2) * 4
    lin = tuple(round(_s2l(px[c + k]), 4) for k in range(3))
    print("   %-30s = %s" % (tag, lin))
    bpy.data.images.remove(img)
    return lin


settings = scene.npr_settings
presets.ensure_default_groups(settings)
settings.active_group_index = [g.name for g in settings.groups].index("身体")
group = settings.active_group()

# 先确认取景：纯红对照
control = bpy.data.materials.new("__CTRL")
control.use_nodes = True
for node in list(control.node_tree.nodes):
    control.node_tree.nodes.remove(node)
co = control.node_tree.nodes.new('ShaderNodeOutputMaterial')
ce = control.node_tree.nodes.new('ShaderNodeEmission')
ce.inputs["Color"].default_value = (1.0, 0.0, 0.0, 1.0)
control.node_tree.links.new(ce.outputs["Emission"], co.inputs["Surface"])
obj.data.materials.clear()
obj.data.materials.append(control)
ctrl = render("00_control_red")
print("   → 取景%s（红=%.3f）" % ("正常" if ctrl[0] > 0.5 else "异常", ctrl[0]))

# 建立 NPR 材质
settings.apply_mode = 'REPLACE'
settings.slot_mode = 'ALL_SLOTS'
settings.auto_texture_detect = False
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.npr.apply()
master = utils.find_group_instance(obj.material_slots[0].material, shader_nodes.G_MASTER)


def base_setup():
    group.base_brightness = 1.0
    group.tex_base_color = None
    group.base_color = (0.1, 0.2, 1.0, 1.0)
    group.base_color_gain = 1.0
    group.tex_alpha = None
    core.apply_group(bpy.context, group)


base_setup()
render("01_all_on")

group.specular_enable = False
core.apply_group(bpy.context, group)
render("02_spec_off")

group.rim_enable = False
core.apply_group(bpy.context, group)
render("03_spec_rim_off")

group.metal_enable = False
core.apply_group(bpy.context, group)
render("04_spec_rim_metal_off")

group.lightmap_smoothstep = True
core.apply_group(bpy.context, group)
render("05_plus_smoothstep")
print("DONE")
