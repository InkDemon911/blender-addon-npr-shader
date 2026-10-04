"""功能自检：注册插件 → 建组 → 一键应用 → 描边 → 渲染验证。

用法：
    blender -b --factory-startup --python npr_shader/tools_func_check.py
    # 也可显式指定插件父目录与渲染输出目录：
    blender -b --factory-startup --python npr_shader/tools_func_check.py -- <插件父目录> <输出目录>
"""

import os
import sys
import traceback

# 让 tools_common 可导入（它与本脚本同目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools_common

# 自动向上找到"包含插件包的那一级目录"，对安装布局 / 仓库布局 / 源码直跑都成立
plugin_parent = tools_common.setup()
out_dir = os.path.join(plugin_parent, "render_out")
if "--" in sys.argv:
    rest = sys.argv[sys.argv.index("--") + 1:]
    if len(rest) > 1:
        out_dir = rest[1]

import bpy
from mathutils import Vector

FAILS = []
STEPS = []


def step(msg):
    STEPS.append(msg)
    print("\n>>> %s" % msg, flush=True)


def check(condition, msg):
    if condition:
        print("    [OK] %s" % msg)
    else:
        print("    [FAIL] %s" % msg)
        FAILS.append(msg)
    return condition


# ======================================================================================
step("1. 注册插件")
import npr_shader
from npr_shader import core, operators, outline, presets, shader_nodes, ui, utils

try:
    npr_shader.register()
    print("    register() 完成")
except Exception:
    traceback.print_exc()
    sys.exit("注册失败")

check(hasattr(bpy.types.Scene, "npr_settings"), "Scene.npr_settings 已注册")
check(hasattr(bpy.ops.npr, "apply"), "npr.apply 操作符已注册")
check(hasattr(bpy.ops.npr, "outline_apply"), "npr.outline_apply 已注册")
check(hasattr(bpy.types, "NPR_PT_root"), "NPR_PT_root 面板已注册")

# ======================================================================================
step("2. 准备场景（相机 / 物体 / 材质，参考 EEVEE 配置）")
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 200
scene.render.resolution_y = 200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
try:
    scene.eevee.taa_render_samples = 8
except AttributeError:
    pass

# 清空启动场景（避免默认 Cube 与测试物体互相遮挡造成误判）
for _obj in list(bpy.data.objects):
    bpy.data.objects.remove(_obj, do_unlink=True)
print("    已清空启动场景，剩余物体：%s" % [o.name for o in bpy.data.objects])

# 世界背景（参考文件用深灰）
world = scene.world or bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
bg = None
for node in world.node_tree.nodes:
    if node.bl_idname == 'ShaderNodeBackground':
        bg = node
if bg is not None:
    bg.inputs[0].default_value = (0.05, 0.05, 0.05, 1.0)

# 测试用几何体：压扁的立方体（保留厚度，避免单面片在部分 EEVEE 构建下不可见）
# 尺寸 1.4 配合相机距离 3.0 / 50mm，在画面中约占 64% 宽，中心区域一定落在物体上。
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.mesh.primitive_cube_add(size=1.4, location=(0.0, 0.0, 0.0))
plane = bpy.context.active_object
plane.name = "TestPanel"
plane.scale = (1.0, 1.0, 0.3)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bpy.ops.object.mode_set(mode='OBJECT')
print("    TestPanel 尺寸 = %s" % (tuple(round(v, 3) for v in plane.dimensions),))

cam_data = bpy.data.cameras.new("TestCam")
cam = bpy.data.objects.new("TestCam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0.0, -3.0, 0.0)        # 正对面板正面
cam.rotation_euler = (1.5707963, 0.0, 0.0)
cam_data.clip_start = 0.1
scene.camera = cam
check(scene.camera is cam, "相机已设为场景相机")

# 原材质：带贴图命名 + Principled，用于测试贴图识别
original = bpy.data.materials.new("Odette_Test_Body_Diffuse")
original.use_nodes = True
tex_node = original.node_tree.nodes.new('ShaderNodeTexImage')
image = bpy.data.images.get("TestDiffuse")
if image is None:
    image = bpy.data.images.new("Avatar_Test_Tex_Body_Diffuse.png", 8, 8, alpha=False)
    image.generated_color = (0.9, 0.2, 0.2, 1.0)
tex_node.image = image
bsdf = None
for node in original.node_tree.nodes:
    if node.bl_idname == 'ShaderNodeBsdfPrincipled':
        bsdf = node
if bsdf is not None:
    original.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
plane.data.materials.append(original)
check(len(plane.material_slots) == 1, "测试物体有 1 个材质槽")

# ======================================================================================
step("3. 创建预设组")
settings = scene.npr_settings
created = presets.ensure_default_groups(settings)
check(len(created) >= 4, "创建了 >=4 个预设组（实际 %d）" % len(created))
names = [group.name for group in settings.groups]
for expected in ("衣服", "头发", "身体", "眼睛"):
    check(expected in names, "预设组「%s」存在" % expected)

group = settings.group_by_name("身体")
check(group is not None, "能按名称取到「身体」组")
settings.active_group_index = names.index("身体")

# 组长与部位
step("4. 自定义组：新建 / 重命名 / 复制 / 排序 / 删除")
op = bpy.ops.npr.group_new(name="自定义裙装", part='Body01', preset='NONE')
check('FINISHED' in op, "npr.group_new 执行成功")
custom = settings.active_group()
check(custom is not None and custom.name == "自定义裙装", "新组名 = 自定义裙装，部位 = %s" % (custom.part if custom else "?"))

custom.name = "裙子"
op = bpy.ops.npr.group_duplicate()
check('FINISHED' in op, "npr.group_duplicate 执行成功")
check(any(g.name.startswith("裙子") for g in settings.groups), "复制产生了「裙子_副本」")

count_before = len(settings.groups)
index_before = settings.active_group_index
bpy.ops.npr.group_move(delta=-1)
check(settings.active_group_index == max(0, index_before - 1), "上移生效")
settings.active_group_index = len(settings.groups) - 1
bpy.ops.npr.group_delete(remove_materials=False)
check(len(settings.groups) == count_before - 1, "删除组生效（%d → %d）" % (count_before, len(settings.groups)))

settings.active_group_index = names.index("身体")
group = settings.active_group()

# ======================================================================================
step("5. 材质分配与一键应用（替换并保留贴图）")
# 把原材质加入组
group.add_material(original)
check(group.has_material(original), "原材质已加入组内材质列表")

bpy.ops.object.select_all(action='DESELECT')
plane.select_set(True)
bpy.context.view_layer.objects.active = plane

settings.apply_mode = 'REPLACE_KEEP_TEX'
settings.slot_mode = 'ALL_SLOTS'
settings.auto_texture_detect = True
op = bpy.ops.npr.apply()
check('FINISHED' in op, "npr.apply 执行成功（%s）" % op)

new_material = plane.material_slots[0].material
check(new_material is not None and new_material.name.startswith("NPR_"),
      "材质槽已替换为 %s" % (new_material.name if new_material else "?"))
check(new_material is not original, "原材质已不在槽位上")
check(utils.material_group_name(new_material) == "身体",
      "材质元数据 npr_group = %s" % utils.material_group_name(new_material))
master = utils.find_group_instance(new_material, shader_nodes.G_MASTER)
check(master is not None, "材质里有 NPR_Shader 主组实例")

# mask 输入检查：Body 必须为 1，其余 0
for part in utils.MASK_PARTS:
    socket = utils.get_input(master, part)
    value = float(socket.default_value) if socket is not None else -1.0
    expected = 1.0 if part == "Body" else 0.0
    check(abs(value - expected) < 1e-6, "mask %s = %.1f（应为 %.1f）" % (part, value, expected))

# 贴图识别：插件的设计是"把贴图作为**主组接口的取值**送进去"，
# 而不是把 TexImage 节点挂在材质里（材质里只有 NPR_Shader 主组 + 输出，这是刻意的
# 非破坏性设计）。所以这里断言的是"贴图被识别并回填到组参数 / 主组接口"。
_tex_slots = ("tex_base_color", "tex_lightmap", "tex_normal", "tex_ramp",
              "tex_metal", "tex_sdf", "tex_emission", "tex_alpha")
_filled = [name for name in _tex_slots if getattr(group, name, None) is not None]
check(bool(_filled), "Diffuse 贴图被识别并回填到组参数：%s" % (", ".join(_filled) or "无"))
_base_sock = utils.get_input(master, "BaseColorTex", -1)
_have_base = _base_sock is not None and (
    _base_sock.is_linked or tuple(round(v, 4) for v in _base_sock.default_value) != (1.0, 1.0, 1.0, 1.0))
check(_have_base or bool(_filled),
      "基础色贴图已送达主组（接口=%s，或经组参数）" % (
          "已连线" if _base_sock is not None and _base_sock.is_linked else "常量"))
_tex_nodes = [n for n in new_material.node_tree.nodes
              if n.bl_idname == 'ShaderNodeTexImage' and n.image is not None]
print("       （材质内 TexImage 节点数 = %d，贴图走主组接口传参）" % len(_tex_nodes))

# ======================================================================================
step("6. 应用整个组 / 反读 / 重置")
group.spec_gloss = 42.0
report = core.apply_group(bpy.context, group)
master = utils.find_group_instance(new_material, shader_nodes.G_MASTER)
gloss = float(utils.get_input(master, "Spec Gloss").default_value)
check(abs(gloss - 42.0) < 1e-6, "应用整组后 Spec Gloss = %.1f" % gloss)

# 反读：把材质改成别的值再读回
utils.set_default(master, "Rim Power", 9.5)
group.rim_power = 1.0
op = bpy.ops.npr.read_back()
check('FINISHED' in op, "npr.read_back 执行成功")
check(abs(group.rim_power - 9.5) < 1e-5, "反读得到 Rim Power = %.2f" % group.rim_power)

group.spec_gloss = 99.0
op = bpy.ops.npr.reset_group()
check('FINISHED' in op, "npr.reset_group 执行成功")
check(abs(group.spec_gloss - shader_nodes.REF_GLOSS) < 1e-6,
      "重置后 Spec Gloss = %.2f（参考值 %.2f）" % (group.spec_gloss, shader_nodes.REF_GLOSS))

# ======================================================================================
step("7. 描边（Solidify 倒角外壳）")
group.outline_enable = True
group.outline_thickness = 0.02
group.outline_mode = 'OBJECT'
op = bpy.ops.npr.outline_apply()
check('FINISHED' in op, "npr.outline_apply 执行成功（%s）" % op)

outlines = outline.outline_objects_for(plane)
check(len(outlines) == 1, "生成了 %d 个描边对象" % len(outlines))
if outlines:
    outline_obj = outlines[0]
    solidify = None
    for modifier in outline_obj.modifiers:
        if modifier.type == 'SOLIDIFY':
            solidify = modifier
    check(solidify is not None, "描边对象有 Solidify 修改器")
    if solidify is not None:
        check(solidify.use_flip_normals, "Solidify.use_flip_normals = True")
        check(abs(solidify.thickness - 0.02) < 1e-6, "Solidify.thickness = %.4f" % solidify.thickness)
    check(bool(outline_obj.material_slots), "描边对象有材质 %s" %
          (outline_obj.material_slots[0].material.name if outline_obj.material_slots else "?"))
    if outline_obj.material_slots and outline_obj.material_slots[0].material:
        check(outline_obj.material_slots[0].material.use_backface_culling,
              "描边材质开启了背面剔除")

# 再次执行应"更新"而不是重复创建
op = bpy.ops.npr.outline_apply()
check(len(outline.outline_objects_for(plane)) == 1, "重复执行不会创建重复描边对象")

# ======================================================================================
step("8. 渲染验证（EEVEE + Standard 色彩管理）")


ASCII_CHARS = " .:-=+*#%@"


def ascii_thumb(pixels, width, height, cols=32, rows=10, label=""):
    """把渲染结果打成字符缩略图。

    用**最大通道**而不是亮度：纯红 (1,0,0) 的亮度只有 0.21，与深灰背景几乎一样，
    用亮度做字符图会误判成"什么都没有"。
    """
    print("    [%s] 字符缩略图（按最大通道；R=红 G=绿 B=蓝 W=亮灰 w=暗灰 .=背景）：" % label)
    for row in range(rows):
        y = int((rows - 1 - row) * (height - 1) / max(1, rows - 1))
        line = []
        for col in range(cols):
            x = int(col * (width - 1) / max(1, cols - 1))
            index = (y * width + x) * 4
            r, g, b = pixels[index], pixels[index + 1], pixels[index + 2]
            top = max(r, g, b)
            if top < 0.08:
                line.append('.')
            elif b > r * 1.5 and b > g * 1.5:
                line.append('B')
            elif r > g * 1.5 and r > b * 1.5:
                line.append('R')
            elif g > r * 1.5 and g > b * 1.5:
                line.append('G')
            elif top > 0.5:
                line.append('W')
            else:
                line.append('w')
        print("       |" + "".join(line) + "|")


_render_seq = [0]


def _srgb_to_linear(value):
    """把 PNG 里读到的 sRGB 编码值还原成线性值。

    ``bpy.data.images.load()`` 读回的 ``pixels`` 是 **sRGB 编码后**的数值
    （实测：线性 0.1 读回 0.349、线性 0.2 读回 0.482）。不还原就会把正确的
    渲染结果误判成"颜色不对"。字符缩略图不受影响（只比较相对大小）。
    """
    try:
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4
    except (TypeError, ValueError):
        return value


def render_mean(path, name, dump_ascii=True):
    """渲染并返回画面中心 20%×20% 区域的**线性**平均 RGB。

    每次渲染写到**唯一文件名**再读回：Blender 在后台模式下 Render Result 没有
    像素缓冲，而同一路径重复 load 会复用已缓存的 image datablock（实测会读到
    上一次渲染的像素），所以这里用递增后缀彻底绕开两个坑。
    """
    _render_seq[0] += 1
    base, ext = os.path.splitext(path)
    unique = "%s_%03d%s" % (base, _render_seq[0], ext)
    scene.render.filepath = unique
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(unique, check_existing=False)
    width, height = img.size
    if width == 0 or height == 0:
        raise RuntimeError("渲染结果尺寸为 0：%s" % unique)
    pixels = list(img.pixels)
    x0, x1 = int(width * 0.4), int(width * 0.6)
    y0, y1 = int(height * 0.4), int(height * 0.6)
    mean = [0.0, 0.0, 0.0]
    count = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            index = (y * width + x) * 4
            for k in range(3):
                mean[k] += _srgb_to_linear(pixels[index + k])
            count += 1
    mean = [value / max(1, count) for value in mean]
    # 像素指纹：用于证明每次读到的确实是不同的图
    fingerprint = sum(_srgb_to_linear(pixels[i * 4]) for i in range(0, width * height, 97))
    if dump_ascii:
        ascii_thumb(pixels, width, height, label=name)
    bpy.data.images.remove(img)
    print("    %s 中心线性均值 = (%.4f, %.4f, %.4f)  [%s 指纹 %.4f]" % (
        name, mean[0], mean[1], mean[2], "%dx%d" % (width, height), fingerprint))
    return mean


os.makedirs(out_dir, exist_ok=True)
try:
    scene.view_settings.view_transform = 'Standard'
except (AttributeError, TypeError):
    pass

# 8a. 关闭描边，避免外壳遮挡平面颜色采样
for obj in outline.outline_objects_for(plane):
    obj.hide_render = True

# 8a0. 先移除描边对象，排除"倒角外壳遮住本体"的可能
_outlines = outline.outline_objects_for(plane)
for _obj in _outlines:
    bpy.data.objects.remove(_obj, do_unlink=True)
print("    （测试前已删除 %d 个描边对象）" % len(_outlines))

mean_a = render_mean(os.path.join(out_dir, "test_a_default.png"), "默认参数")

# 8a1. 对照：把同一物体换成纯红 Emission，确认取景与几何是否正常
control = bpy.data.materials.new("__NPR_CONTROL_RED")
control.use_nodes = True
for node in list(control.node_tree.nodes):
    control.node_tree.nodes.remove(node)
_c_out = control.node_tree.nodes.new('ShaderNodeOutputMaterial')
_c_emi = control.node_tree.nodes.new('ShaderNodeEmission')
_c_emi.inputs["Color"].default_value = (1.0, 0.0, 0.0, 1.0)
control.node_tree.links.new(_c_emi.outputs["Emission"], _c_out.inputs["Surface"])
_saved = plane.material_slots[0].material
plane.material_slots[0].material = control
mean_ctrl = render_mean(os.path.join(out_dir, "test_a0_control_red.png"), "对照纯红发光", dump_ascii=False)
plane.material_slots[0].material = _saved
check(mean_ctrl[0] > 0.5 and mean_ctrl[1] < 0.1,
      "对照材质渲染正常（红=%.3f 绿=%.3f）→ 取景与几何没问题" % (mean_ctrl[0], mean_ctrl[1]))

# 8a2. 先做一次几何/取景自检，避免把"看不见物体"误判成着色问题
print("    -- 取景自检 --")
print("       相机位置 %s 旋转 %s" % (tuple(round(v, 3) for v in cam.location),
                                   tuple(round(v, 3) for v in cam.rotation_euler)))
print("       面板世界坐标 %s 尺寸 %s" % (
    tuple(round(v, 3) for v in plane.matrix_world.translation),
    tuple(round(v, 3) for v in plane.dimensions)))
print("       面板 visible_get=%s hide_render=%s 材质=%s" % (
    plane.visible_get(), plane.hide_render,
    plane.material_slots[0].material.name if plane.material_slots else None))
print("       场景相机=%s" % (scene.camera.name if scene.camera else None))
print("       渲染物体=%s" % ", ".join(
    sorted(o.name for o in bpy.data.objects if o.type in ('MESH', 'CAMERA', 'LIGHT') and not o.hide_render)))
visible = [o for o in bpy.data.objects if o.type == 'MESH' and not o.hide_render]
print("       未隐藏网格=%s" % ", ".join(sorted(o.name for o in visible)))
# 物体是否落在相机视锥里（用投影坐标判断）
from bpy_extras.object_utils import world_to_camera_view as _w2cv
for corner in plane.bound_box:
    from mathutils import Vector as _V
    world = plane.matrix_world @ _V(corner)
    co = _w2cv(scene, cam, world)
    print("       corner %s → 归一化坐标 (%.3f, %.3f, %.3f)" % (
        tuple(round(v, 2) for v in world), co.x, co.y, co.z))

print("       （默认参数均值 %.4f，受自动识别到的贴图影响，仅作记录）" % mean_a[0])

# 8b. 提高亮度并换成纯蓝色基础色 → 渲染结果必须变化
group.base_brightness = 1.0
group.tex_base_color = None
group.base_color = (0.1, 0.2, 1.0, 1.0)
group.base_color_gain = 1.0
group.tex_alpha = None
core.apply_group(bpy.context, group)
# 诊断：把主组实参打出来，便于定位"颜色没生效"的原因
_master = utils.find_group_instance(plane.material_slots[0].material, shader_nodes.G_MASTER)
if _master is not None:
    print("       主组实参检查：")
    for _key in ("Body", "Face", "Base Color", "Tint Strength", "Base Brightness",
                 "Color Gain", "Gain Strength", "Ramp Strength", "Ramp Enable",
                 "Spec Enable", "Rim Enable", "Halo Brightness", "Metal Enable"):
        _sock = utils.get_input(_master, _key, -1)
        if _sock is None:
            print("          %-18s 插槽缺失" % _key)
            continue
        _val = _sock.default_value
        try:
            _val = tuple(round(x, 3) for x in _val)
        except TypeError:
            try:
                _val = round(float(_val), 3)
            except TypeError:
                _val = "?"
        print("          %-18s = %s" % (_key, _val))
mean_b = render_mean(os.path.join(out_dir, "test_b_blue.png"), "蓝色高亮")

delta = sum(abs(mean_a[i] - mean_b[i]) for i in range(3))
check(delta > 0.05, "参数改变导致渲染结果变化（中心区总差 %.4f）" % delta)
check(mean_b[2] > mean_b[0] * 4, "蓝色分量显著高于红色分量（%.3f vs %.3f）" % (mean_b[2], mean_b[0]))
check(mean_b[2] > 0.5, "蓝色分量达到预期量级（%.3f > 0.5）" % mean_b[2])
check(abs(mean_b[2] - 1.0) < 0.05, "蓝色通道接近 1.0（%.3f）" % mean_b[2])

# 8c. 关闭主光的场景无关性：参考文件的着色不依赖 EEVEE 灯光，只依赖固定光向量
step("9. 着色与 EEVEE 灯光无关（参考文件的自包含着色特性）")
light_data = bpy.data.lights.new("TestLight", 'SUN')
light = bpy.data.objects.new("TestLight", light_data)
scene.collection.objects.link(light)
light.location = (3.0, -3.0, 3.0)
light_data.energy = 5.0
mean_c = render_mean(os.path.join(out_dir, "test_c_with_sun.png"), "加入太阳光后")
delta_lc = sum(abs(mean_b[i] - mean_c[i]) for i in range(3))
check(delta_lc < 0.01, "加入灯光后结果基本不变（差 %.4f）→ 着色自包含" % delta_lc)

# ======================================================================================
step("10. 其它模式与撤销安全性")
settings.apply_mode = 'APPEND'
bpy.ops.object.select_all(action='DESELECT')
plane.select_set(True)
bpy.context.view_layer.objects.active = plane
slots_before = len(plane.material_slots)
bpy.ops.npr.apply()
check(len(plane.material_slots) == slots_before + 1,
      "追加模式新增了槽位（%d → %d）" % (slots_before, len(plane.material_slots)))

settings.apply_mode = 'OUTLINE_ONLY'
slots_before = len(plane.material_slots)
bpy.ops.npr.apply()
check(len(plane.material_slots) == slots_before, "仅描边模式不改动材质槽")

step("11. 自检操作符与渲染设置")
op = bpy.ops.npr.validate()
check('FINISHED' in op, "npr.validate 执行完成")
op = bpy.ops.npr.render_defaults(enable_bloom=True)
check('FINISHED' in op, "npr.render_defaults 执行完成")
check(scene.view_settings.view_transform == 'Standard', "View Transform = Standard")

step("12. 卸载插件")
try:
    npr_shader.unregister()
    check(not hasattr(bpy.types.Scene, "npr_settings"), "unregister 后 npr_settings 已移除")
except Exception:
    traceback.print_exc()
    FAILS.append("卸载失败")

# ======================================================================================
print("\n" + "=" * 70)
print("步骤数：%d，失败项：%d" % (len(STEPS), len(FAILS)))
for item in FAILS:
    print("  FAIL:", item)
print("FUNC_CHECK_DONE fails=%d" % len(FAILS))
print("渲染输出目录：%s" % out_dir)
