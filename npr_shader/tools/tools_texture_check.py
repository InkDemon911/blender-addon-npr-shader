"""贴图专项验证：把纯色贴图接到 NPR 材质上，断言渲染结果。

覆盖用户报的场景："添加贴图，贴图不生效"。
每个用例都带**对照**（纯色 Emission）确保取样点可信。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools_common

plugin_parent = tools_common.setup()
import bpy  # noqa: E402

import npr_shader  # noqa: E402
from npr_shader import core, presets, shader_nodes, utils  # noqa: E402

npr_shader.register()
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = scene.render.resolution_y = 16
scene.view_settings.view_transform = 'Standard'
scene.render.film_transparent = False
scene.render.image_settings.file_format = 'OPEN_EXR'
OUT = os.path.join(plugin_parent, "render_out")
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.endswith(".exr"):
        os.remove(os.path.join(OUT, f))

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.mesh.primitive_cube_add(size=1.4)
obj = bpy.context.active_object

cd = bpy.data.cameras.new("C")
cam = bpy.data.objects.new("C", cd)
scene.collection.objects.link(cam)
cam.location = (0, -3, 0)
cam.rotation_euler = (1.5707963, 0, 0)
scene.camera = cam

fails = []
_seq = [0]


def render_raw(tag):
    """渲染到 EXR 读**线性未裁剪**值。"""
    _seq[0] += 1
    path = os.path.join(OUT, "tx_%s_%02d.exr" % (tag, _seq[0]))
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = list(img.pixels)
    samples = []
    for (fx, fy) in ((0.5, 0.5), (0.45, 0.5), (0.55, 0.5), (0.5, 0.45), (0.5, 0.55)):
        x = int(w * fx)
        y = int(h * fy)
        i = (y * w + x) * 4
        samples.append(tuple(px[i + k] for k in range(3)))
    lin = tuple(round(sum(s[k] for s in samples) / len(samples), 4) for k in range(3))
    bpy.data.images.remove(img)
    return lin


def expect(tag, got, want, tol=0.03):
    ok = all(abs(got[i] - want[i]) <= tol for i in range(3))
    mark = "OK  " if ok else "FAIL"
    print("   [%s] %-26s 实测=%s 期望=%s" % (mark, tag, got, want))
    if not ok:
        fails.append("%s: 实测 %s 期望 %s" % (tag, got, want))
    return ok


# ---------------- 对照 ----------------
print("=" * 74)
print("对照（确认取样可信）")
print("=" * 74)
for tag, col in (("CTRL_RED", (1, 0, 0, 1)), ("CTRL_BLUE", (0.1, 0.2, 1.0, 1))):
    m = bpy.data.materials.new("__" + tag)
    m.use_nodes = True
    tr = m.node_tree
    for n in list(tr.nodes):
        tr.nodes.remove(n)
    o = tr.nodes.new('ShaderNodeOutputMaterial')
    e = tr.nodes.new('ShaderNodeEmission')
    e.inputs["Color"].default_value = col
    tr.links.new(e.outputs["Emission"], o.inputs["Surface"])
    obj.data.materials.clear()
    obj.data.materials.append(m)
    expect(tag, render_raw(tag), col[:3], tol=0.02)

# ---------------- 贴图用例 ----------------
print()
print("=" * 74)
print("贴图用例（贴图 = 纯色图，基础色调色 = 白，强度 1）")
print("=" * 74)


def solid_image(name, rgba, size=8):
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.new(name, size, size, alpha=True)
    img.pixels = list(rgba) * (size * size)
    img.update()
    img.pack()
    return img


s = scene.npr_settings
presets.ensure_default_groups(s)
s.active_group_index = [g.name for g in s.groups].index("身体")
g = s.active_group()
for attr in ("tex_alpha", "tex_lightmap", "tex_metal", "tex_normal",
             "tex_ramp", "tex_sdf", "tex_emission"):
    setattr(g, attr, None)
g.base_brightness = 1.0
g.base_color_gain = 1.0
g.specular_enable = False
g.rim_enable = False
g.metal_enable = False
g.detail_strength = 0.0
g.emission_strength = 0.0

CASES = [
    ("RED_TEXTURE", (1.0, 0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    ("GREEN_TEXTURE", (0.0, 1.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    ("BLUE_TEXTURE", (0.0, 0.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
    ("HALFGRAY_TEXTURE", (0.5, 0.5, 0.5, 1.0), (0.5, 0.5, 0.5)),
]
for tag, rgba, want in CASES:
    img = solid_image("TX_%s" % tag, rgba)
    g.tex_base_color = img
    g.base_color = (1.0, 1.0, 1.0, 1.0)   # 不调色，纯看贴图
    name = utils.npr_material_name(g.name, g.part)
    if name in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials[name])
    mat, _ = core.ensure_group_material(g)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    expect(tag, render_raw(tag), want)

# ---------------- 贴图 × 调色 ----------------
print()
print("=" * 74)
print("贴图 × 基础色调色（红贴图 × 蓝调色 = (0.1, 0, 0)）")
print("=" * 74)
img = solid_image("TX_MUL_RED", (1.0, 0.0, 0.0, 1.0))
g.tex_base_color = img
g.base_color = (0.1, 0.2, 1.0, 1.0)
name = utils.npr_material_name(g.name, g.part)
if name in bpy.data.materials:
    bpy.data.materials.remove(bpy.data.materials[name])
mat, _ = core.ensure_group_material(g)
obj.data.materials.clear()
obj.data.materials.append(mat)
expect("RED_TEX_x_BLUE_TINT", render_raw("MUL"), (0.1, 0.0, 0.0))

print()
print("=" * 74)
print("无贴图回落（基础色 = 蓝，应得到精确蓝）")
print("=" * 74)
g.tex_base_color = None
g.base_color = (0.1, 0.2, 1.0, 1.0)
name = utils.npr_material_name(g.name, g.part)
if name in bpy.data.materials:
    bpy.data.materials.remove(bpy.data.materials[name])
mat, _ = core.ensure_group_material(g)
obj.data.materials.clear()
obj.data.materials.append(mat)
expect("NO_TEXTURE_FALLBACK", render_raw("FALLBACK"), (0.1, 0.2, 1.0))

print()
print("=" * 74)
if fails:
    print("失败项 %d：" % len(fails))
    for f in fails:
        print("   -", f)
else:
    print("全部通过")
print("TEXTURE_CHECK_DONE fails=%d" % len(fails))
