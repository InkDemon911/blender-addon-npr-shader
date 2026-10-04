# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Shader — 材质应用引擎。

职责：
  * 扫描选中物体的材质槽
  * 按四种模式（替换 / 追加 / 仅描边 / 替换并保留贴图）生成或更新 NPR 材质
  * 把材质组的每个参数（含参考文件里的全部常量）写进顶层 NPR_Shader 实例
  * 组级批量操作：应用整个组 / 从材质反读 / 重置参数
  * 贴图用途自动识别（Diffuse / Lightmap / Normalmap / Ramp / Metal / SDF …）

参考文件的"多部位合一"结构在这里的处理方式：每个材质组带一个 ``part`` 属性，
应用时把对应 mask 输入设为 1.0，其余为 0.0；同一个 NPR_Shader 节点组因此可以
服务任意数量的材质组，节点拓扑与参考文件保持一致。
"""

from __future__ import annotations

import bpy

from . import shader_nodes, utils
from .outline import apply_outline

# --------------------------------------------------------------------------------------
# 贴图槽 → NPR_Shader 接口 / 辅助节点
# --------------------------------------------------------------------------------------

#: (组属性名, NPR_Shader 接口名, 色彩空间用途)
MASTER_TEXTURE_SLOTS = (
    ("tex_base_color", "BaseColorTex", "base_color"),
    ("tex_lightmap", "LightmapTex", "lightmap"),
    ("tex_normal", "NormalTex", "normal"),
    ("tex_ramp", "RampTex", "ramp"),
    ("tex_metal", "MetalTex", "metal"),
    ("tex_sdf", "SdfTex", "sdf"),
    ("tex_emission", "EmissionTex", "emission"),
)

#: 组属性名 → 数值接口名（默认值均为参考文件常量）
MASTER_VALUE_SLOTS = (
    ("base_brightness", "Base Brightness"),
    ("base_color_gain", "Color Gain"),
    ("detail_strength", "Detail Strength"),
    ("emission_strength", "Emission Strength"),
    ("ao_bias", "AO Bias"),
    ("ao_smooth_lo", "AO Smooth Lo"),
    ("ao_smooth_hi", "AO Smooth Hi"),
    ("ao_add", "AO Add"),
    ("shadow_threshold", "Shadow Threshold"),
    ("ramp_strength", "Ramp Strength"),
    ("ramp_band_0", "Ramp Band A0"),
    ("ramp_band_1", "Ramp Band A1"),
    ("ramp_band_2", "Ramp Band A2"),
    ("ramp_band_3", "Ramp Band A3"),
    ("ramp_band_4", "Ramp Band A4"),
    ("ramp_band_scale", "Ramp Band Step"),
    ("ramp_band_base", "Ramp Band Base"),
    ("spec_gloss", "Spec Gloss"),
    ("spec_darken", "Spec Darken"),
    ("spec_threshold", "Spec Threshold"),
    ("metal_threshold", "Metal Threshold"),
    ("spec_crystal_threshold", "Spec Crystal Threshold"),
    ("rim_power", "Rim Power"),
    ("rim_looseness", "Rim Looseness"),
    ("rim_lo", "Rim Lo"),
    ("ramp_hi", "Rim Hi"),
    ("halo_brightness", "Halo Brightness"),
    ("emission_strength", "Emission Strength"),
    ("base_color_gain_strength", "Gain Strength"),
)

MASTER_COLOR_SLOTS = (
    ("base_color", "Base Color"),
    ("rim_color", "Rim Color"),
)

MASTER_FLAG_SLOTS = (
    ("specular_enable", "Spec Enable"),
    ("metal_enable", "Metal Enable"),
    ("rim_enable", "Rim Enable"),
    ("sdf_enable", "SDF Enable"),
    ("crystal", "Crystal"),
)


# --------------------------------------------------------------------------------------
# 材质内容构建
# --------------------------------------------------------------------------------------

def _configure_master_inputs(master, group) -> None:
    """把组参数写进 NPR_Shader 实例。默认值 = 参考文件常量。"""
    # 部位 mask：参考文件用 Face/Body01/Body/Hair/Eyes 五个 Float 输入选部位
    for part in utils.MASK_PARTS:
        utils.set_default(master, part, 1.0 if group.part == part else 0.0)
    utils.set_default(master, "Crystal", 1.0 if group.crystal else 0.0)

    for attr, socket in MASTER_VALUE_SLOTS:
        utils.set_default(master, socket, float(getattr(group, attr, 0.0)))
    for attr, socket in MASTER_COLOR_SLOTS:
        utils.set_default(master, socket, tuple(getattr(group, attr)))
    for attr, socket in MASTER_FLAG_SLOTS:
        utils.set_default(master, socket, 1.0 if getattr(group, attr, False) else 0.0)

    # 光源方向与头部坐标系（参考文件里的固定常量）
    utils.set_default(master, "Light Euler", tuple(group.light_euler))
    utils.set_default(master, "Light Intensity", float(group.light_intensity))
    utils.set_default(master, "Rim Intensity", float(group.rim_intensity))
    utils.set_default(master, "SdfTexAlpha", 1.0)
    # 基础色作为"色调"乘到贴图上：非白色 → 自动把色调强度设为 1；
    # 白色（默认）→ 强度 0。这样"设了颜色就生效、没设就完全不染色"，
    # 不依赖用户再去手动拨一个强度。
    tint = tuple(group.base_color)
    is_white = all(abs(tint[i] - 1.0) < 1e-4 for i in range(3))
    utils.set_default(master, "Base Color", tint)
    utils.set_default(master, "Tint Strength", 0.0 if is_white else 1.0)

    # ---- 未接线贴图的"单位元"处理 ----
    # MetalTex 走 MULTIPLY：没金属贴图时必须给黑色，否则高光分支会整片变白。
    # **alpha 一律给 0**：Mix 节点按 RGBA 计算，alpha=1 会在加法链里累积成 1，
    # 把后续 MULTIPLY 的常量拉成白色（表现就是整片纯白，很难查）。
    utils.set_default(master, "MetalTex", (1.0, 1.0, 1.0, 0.0) if group.tex_metal is not None
                      else (0.0, 0.0, 0.0, 0.0))
    # 花纹叠加走 ADD：没贴图时给黑色（含 alpha=0）
    for index in range(1, 5):
        image = getattr(group, "tex_detail_%d" % index, None)
        utils.set_default(master, "Detail %d" % index,
                          (0.0, 0.0, 0.0, 0.0) if image is None else (1.0, 1.0, 1.0, 0.0))
    # 基础色作为"色调"（Base Tint）乘到贴图上：白色 = 不改动贴图，其它颜色 = 整体染色。
    # 没有基础色贴图时贴图链输出白色，乘上色调正好得到纯色本身，语义自洽。
    utils.set_default(master, "Base Color", tuple(group.base_color))


def _configure_auxiliary_nodes(material, group, master):
    """在材质层补齐主组之外的辅助效果：瞳孔/花纹叠加、Alpha、MatCap。

    这些在参考文件里分散在 Eyes Shader / NodeGroup 组与若干 Principled 材质里，
    这里统一用插件自建的节点组 + Mix(ADD) 合成到最终 Emission，
    **不改动 NPR_Shader 内部拓扑**。
    """
    tree = material.node_tree
    sources = []

    # ---- Eyes Shader（3 张瞳孔贴图 ADD）----
    pupils = (group.tex_pupil_a, group.tex_pupil_b, group.tex_pupil_c)
    if any(pupils):
        node = utils.new_group_instance(material, utils.npr_node_group(shader_nodes.G_EYES, True),
                                        location=(-100.0, -700.0), label="Eyes Shader")
        for index, image in enumerate(pupils):
            socket = "Pupil %s" % "ABC"[index]
            if image is None:
                utils.set_default(node, socket, (0.0, 0.0, 0.0, 1.0))
                continue
            tex = _make_uv_texture(material, image, (-520.0, -600.0 - index * 220.0),
                                   label="瞳孔 %s" % "ABC"[index], role="base_color", solo=True)
            utils.link(tree, tex, "Color", node, socket)
        sources.append(node)

    # ---- 花纹叠加（4 张 ADD）----
    details = (group.tex_detail_1, group.tex_detail_2, group.tex_detail_3, group.tex_detail_4)
    if any(details):
        node = utils.new_group_instance(material, utils.npr_node_group(shader_nodes.G_DETAIL, True),
                                        location=(-100.0, -1400.0), label="花纹叠加")
        for index, image in enumerate(details):
            socket = "Detail %d" % (index + 1)
            if image is None:
                utils.set_default(node, socket, (0.0, 0.0, 0.0, 1.0))
                continue
            tex = _make_uv_texture(material, image, (-520.0, -1300.0 - index * 220.0),
                                   label="花纹 %d" % (index + 1), role="detail", solo=True)
            utils.link(tree, tex, "Color", node, socket)
        sources.append(node)

    # ---- 自发光贴图（单独一条，避免与主组内的 EmissionTex 重复采样）----
    if group.tex_emission is not None:
        tex = _make_uv_texture(material, group.tex_emission, (-520.0, -900.0),
                               label="自发光贴图", role="emission", solo=True)
        sources.append(tex)

    # ---- MatCap（相机空间法线映射，参考文件没有此项，属插件扩展）----
    if group.tex_matcap is not None:
        tex_coord = tree.nodes.new('ShaderNodeTexCoord')
        tex_coord.name = "纹理坐标"
        tex_coord.location = (-1000.0, -1800.0)
        sep = tree.nodes.new('ShaderNodeSeparateXYZ')
        sep.name = "分离 XYZ"
        sep.location = (-820.0, -1800.0)
        utils.link(tree, tex_coord, "Normal", sep, "Vector")
        comb = tree.nodes.new('ShaderNodeCombineXYZ')
        comb.name = "合并 XYZ"
        comb.location = (-640.0, -1800.0)
        m_madd = tree.nodes.new('ShaderNodeVectorMath')
        m_madd.name = "矢量运算"
        utils.set_prop(m_madd, "operation", 'MULTIPLY_ADD')
        m_madd.location = (-460.0, -1800.0)
        utils.set_default(m_madd, "Vector_001", (0.5, 0.5, 0.5))
        utils.set_default(m_madd, "Vector_002", (0.5, 0.5, 0.5))
        utils.link(tree, sep, "X", comb, "X")
        utils.link(tree, sep, "Y", comb, "Y")
        utils.set_default(comb, "Z", 0.0)
        utils.link(tree, comb, "Vector", m_madd, "Vector")
        matcap = _make_uv_texture(material, group.tex_matcap, (-240.0, -1800.0),
                                  label="MatCap", role="matcap", solo=True)
        utils.link(tree, m_madd, "Vector", matcap, "Vector")
        sources.append(matcap)

    if not sources:
        return None

    # ---- 把辅助来源 ADD 到最终发光 ----
    accumulated = None
    for index, node in enumerate(sources):
        socket = "Result" if node.bl_idname == 'ShaderNodeGroup' else "Color"
        mix = utils.mix_node(tree, blend_type="ADD", data_type="RGBA",
                             location=(160.0 + index * 180.0, -900.0))
        mix.name = "辅助叠加.%03d" % index
        if accumulated is None:
            utils.link(tree, master, "Emission", mix, "A")
        else:
            utils.link(tree, accumulated, "Result", mix, "A")
        utils.link(tree, node, socket, mix, "B")
        accumulated = mix
    return accumulated


def _make_uv_texture(material, image, location, label="", role="base_color", solo=False):
    """创建一个图像纹理节点并接到主 UV 上。

    ``solo=True`` 时只有一个材质会引用该图像，Blender 不会把它折叠成共享节点，
    因此每个贴图槽都能拿到独立的节点实例。
    """
    tree = material.node_tree
    node = tree.nodes.new('ShaderNodeTexImage')
    node.name = label or (image.name if image else "图像纹理")
    node.label = label
    node.location = location
    node.image = image
    utils.set_prop(node, "interpolation", 'Linear')
    utils.set_prop(node, "extension", 'REPEAT')
    if image is not None:
        utils.set_image_colorspace(image, role)
    uv = tree.nodes.new('ShaderNodeUVMap')
    uv.name = "UV 贴图"
    uv.location = (location[0] - 220.0, location[1])
    utils.link(tree, uv, "UV", node, "Vector")
    return node


def ensure_shader_groups(force: bool = False):
    """确保 18 个 Shader 节点组存在（自愈）。

    **为什么必须在"用到节点组之前"调用**：``ensure_all()`` 是按名字检查存在性的，
    如果某个名字下已经躺着一个**空组**（例如启动期 ``bpy.data`` 受限、构建被跳过时
    留下了同名占位），后续重建会认为"已存在"而跳过，材质里挂上的就是一个没有接口的
    空组 —— 表现为插件"装了但没效果"。这里先补齐，避免任何入口产生空组。

    Returns:
        dict: ``ensure_all()`` 的构建报告。
    """
    from . import shader_nodes
    try:
        return shader_nodes.ensure_all(force=force)
    except AttributeError:
        # 启动期 bpy.data 受限：调用方（通常是 Operator）稍后会被再次触发，
        # 这里安静返回，不打断注册流程。
        return {"built": [], "skipped": [], "errors": [], "wiring": []}


def _build_material_content(material, group, textures=None):
    """在材质里搭建完整 NPR 节点结构（清空后重建，保证幂等）。"""
    material.use_nodes = True
    tree = material.node_tree
    utils.clear_node_tree(tree)

    # 先自愈：避免把空组当成"已存在的节点组"
    ensure_shader_groups()
    master_tree = utils.npr_node_group(shader_nodes.G_MASTER, create=True)
    master = utils.new_group_instance(material, master_tree, location=(-40.0, 120.0),
                                      label=group.name)
    master.name = "NPR_Shader 主组"

    output = utils.ensure_material_output(material)
    output.location = (760.0, 120.0)

    # ---- 主组贴图接口 ----
    textures = textures or {}
    for attr, socket, role in MASTER_TEXTURE_SLOTS:
        image = getattr(group, attr, None)
        if image is None:
            image = utils.pick_texture(textures, role, 0)
        if image is None:
            continue
        if attr == "tex_base_color":
            # 基础色贴图在主组内部被 5 个部位接口共享，这里只需一个节点
            node = _make_uv_texture(material, image, (-620.0, 620.0),
                                    label="基础色贴图", role=role)
            utils.link(tree, node, "Color", master, socket)
            continue
        node = _make_uv_texture(material, image, (-620.0, 620.0 - len(socket) * 6.0),
                                label=attr, role=role)
        utils.link(tree, node, "Color", master, socket)
        if attr == "tex_sdf":
            utils.link(tree, node, "Alpha", master, "SdfTexAlpha")

    # ---- Alpha ----
    alpha_image = group.tex_alpha
    if alpha_image is None:
        alpha_image = utils.pick_texture(textures, "alpha", 0)
    if alpha_image is None and group.tex_base_color is not None:
        alpha_image = group.tex_base_color
    if alpha_image is not None:
        alpha_node = _make_uv_texture(material, alpha_image, (-620.0, -400.0),
                                      label="Alpha 贴图", role="alpha")
        utils.link(tree, alpha_node, "Alpha", master, "AlphaTex")
        utils.set_default(master, "Alpha Enable", 1.0)
    else:
        utils.set_default(master, "Alpha Enable", 0.0)

    # ---- 参数 ----
    _configure_master_inputs(master, group)

    # ---- 辅助叠加 ----
    extra = _configure_auxiliary_nodes(material, group, master)

    if extra is not None:
        final = tree.nodes.new('ShaderNodeMixShader')
        final.name = "最终输出"
        final.location = (480.0, 120.0)
        emission = tree.nodes.new('ShaderNodeEmission')
        emission.name = "合成自发光"
        emission.location = (280.0, 320.0)
        utils.link(tree, extra, "Result", emission, "Color")
        transparent = tree.nodes.new('ShaderNodeBsdfTransparent')
        transparent.name = "透明 BSDF"
        transparent.location = (280.0, -140.0)
        utils.link(tree, master, "Emission", final, "Shader")
        utils.link(tree, emission, "Emission", final, "Shader_001")
        utils.link(tree, transparent, "BSDF", final, "Shader")
        utils.link(tree, extra, "Result", final, "Fac")
        utils.link(tree, final, "Shader", output, "Surface")
    else:
        utils.link(tree, master, "Emission", output, "Surface")

    _apply_material_settings(material, group, has_alpha=alpha_image is not None)
    return master


def _apply_material_settings(material, group, has_alpha: bool = False) -> None:
    """材质级 EEVEE 设置（参考文件实测：DITHERED / BLENDED）。"""
    method = group.surface_render_method
    if has_alpha and method == 'DITHERED':
        method = 'DITHERED'   # 镂空透明，保持参考文件默认
    utils.set_prop(material, "surface_render_method", method)
    utils.set_prop(material, "alpha_threshold", float(group.alpha_threshold))
    utils.set_prop(material, "use_transparent_shadow", False)
    utils.set_prop(material, "use_backface_culling", False)
    material.diffuse_color = tuple(group.base_color)
    try:
        material.roughness = 1.0
        material.metallic = 0.0
    except AttributeError:
        pass
    material[utils.KEY_GENERATED] = utils.VERSION_STR


# --------------------------------------------------------------------------------------
# 材质创建 / 更新
# --------------------------------------------------------------------------------------

def ensure_group_material(group, textures=None, force_rebuild: bool = False):
    """创建或更新一个组对应的 NPR 材质，返回材质对象。

    材质名 = ``NPR_<组名>_<部位>``，重复调用会原地重建节点，不会产生副本。
    """
    name = utils.npr_material_name(group.name, group.part)
    material = bpy.data.materials.get(name)
    created = material is None
    if material is None:
        material = bpy.data.materials.new(name)
    elif not force_rebuild and utils.is_npr_material(material) and \
            material.get(utils.KEY_GROUP, "") == group.name and \
            material.get(utils.KEY_PART, "") == group.part and \
            utils.find_group_instance(material, shader_nodes.G_MASTER) is not None:
        # 已存在且结构正确：只刷新参数，不做整树重建（性能更好）
        master = utils.find_group_instance(material, shader_nodes.G_MASTER)
        _configure_master_inputs(master, group)
        _apply_material_settings(material, group, has_alpha=group.tex_alpha is not None)
        utils.set_material_group(material, group.name, group.part)
        return material, False

    _build_material_content(material, group, textures)
    utils.set_material_group(material, group.name, group.part)
    return material, created


def update_material_parameters(material, group) -> bool:
    """只更新已有材质的参数（不重建节点），用于"应用整个组"。"""
    master = utils.find_group_instance(material, shader_nodes.G_MASTER)
    if master is None:
        return False
    _configure_master_inputs(master, group)
    # 贴图槽可能在面板里被改过，逐个同步
    for attr, socket, role in MASTER_TEXTURE_SLOTS:
        image = getattr(group, attr, None)
        existing = _find_texture_node(material, socket)
        if image is None:
            if existing is not None and existing.get("npr_slot") == socket:
                material.node_tree.nodes.remove(existing)
            continue
        if existing is not None and existing.image == image:
            continue
        if existing is not None:
            existing.image = image
            utils.set_image_colorspace(image, role)
        else:
            node = _make_uv_texture(material, image, (-620.0, 0.0), label=attr, role=role)
            utils.link(material.node_tree, node, "Color", master, socket)
    _apply_material_settings(material, group, has_alpha=group.tex_alpha is not None)
    return True


def _find_texture_node(material, slot_name):
    """找到某个贴图槽对应的图像纹理节点（按节点 name/label 匹配）。"""
    for node in material.node_tree.nodes:
        if node.bl_idname == 'ShaderNodeTexImage':
            if node.get("npr_slot", "") == slot_name or node.name == slot_name or node.label == slot_name:
                return node
    return None


# --------------------------------------------------------------------------------------
# 一键应用
# --------------------------------------------------------------------------------------

def apply_to_objects(context, objects, group, mode: str = 'REPLACE', slot_mode: str = 'ALL_SLOTS',
                     auto_texture: bool = True, out_report=None):
    """对一批物体执行 NPR 材质应用。

    Args:
        mode: ``REPLACE`` / ``APPEND`` / ``OUTLINE_ONLY`` / ``REPLACE_KEEP_TEX``
        slot_mode: ``REPLACE_FIRST`` / ``ALL_SLOTS`` / ``APPEND``
        auto_texture: 是否自动扫描原材质贴图并归类填入

    Returns:
        dict(materials=[...], slots=[...], textures={...}, outline=..., notes=[...])
    """
    report = out_report if out_report is not None else []
    summary = {"materials": [], "slots": 0, "outline": None, "notes": []}

    if group is None:
        report.append("没有可用的材质组")
        return summary

    # 1) 收集原材质贴图：REPLACE_KEEP_TEX 模式直接用于新材质；
    #    其它模式在开启 auto_texture 时顺便填进组的贴图槽（便于后续微调）。
    detected = {}
    if mode == 'REPLACE_KEEP_TEX' or auto_texture:
        detected = detect_textures_for_group(context, objects, group, report,
                                             write_slots=bool(auto_texture))

    # 2) 生成组的 NPR 材质
    material, created = ensure_group_material(group, textures=detected)
    summary["materials"].append(material)

    if mode == 'OUTLINE_ONLY':
        if group.outline_enable:
            summary["outline"] = apply_outline(objects, group, mode=group.outline_mode, report=report)
        else:
            report.append("组「%s」未启用描边" % group.name)
        return summary

    # 3) 处理材质槽
    slots_touched = 0
    for obj in objects:
        if obj is None or obj.type != 'MESH':
            continue
        slots = list(obj.material_slots)
        if not slots:
            # 没有材质槽：直接追加
            obj.data.materials.append(material)
            slots_touched += 1
            continue

        if mode == 'APPEND' or slot_mode == 'APPEND':
            obj.data.materials.append(material)
            _set_active_slot(obj, len(obj.material_slots) - 1)
            slots_touched += 1
            continue

        if slot_mode == 'REPLACE_FIRST':
            targets = [0]
        else:
            targets = list(range(len(slots)))

        for index in targets:
            if index >= len(obj.material_slots):
                continue
            original = obj.material_slots[index].material
            if original is not None and original == material:
                continue
            if original is not None and _settings_keep_original():
                original.use_fake_user = True
            obj.material_slots[index].material = material
            slots_touched += 1

    summary["slots"] = slots_touched
    report.append("已把 %d 个材质槽替换/追加为 %s" % (slots_touched, material.name))

    # 4) 描边
    if group.outline_enable:
        summary["outline"] = apply_outline(objects, group, mode=group.outline_mode, report=report)
    else:
        report.append("组「%s」未启用描边，跳过" % group.name)

    return summary


def _set_active_slot(obj, index: int) -> None:
    try:
        obj.active_material_index = index
    except (AttributeError, TypeError):
        pass


def _settings_keep_original() -> bool:
    try:
        return bool(bpy.context.scene.npr_settings.keep_original_materials)
    except AttributeError:
        return True


# --------------------------------------------------------------------------------------
# 贴图自动识别
# --------------------------------------------------------------------------------------

def detect_textures_for_group(context, objects, group, report=None, write_slots: bool = True) -> dict:
    """扫描物体原有材质，按用途归类贴图。

    Args:
        write_slots: True 时把识别结果写进组里仍为空的贴图槽（便于面板微调）；
                     False 时只返回结果（供"保留原贴图连接"直接使用）。

    Returns:
        {role: [image, ...]} 识别结果
    """
    log = report if report is not None else []
    found = {}
    for _obj, _index, material in utils.mesh_material_slots(objects):
        if material is None or utils.material_group_name(material) == group.name:
            continue
        for role, images in utils.collect_material_textures(material).items():
            found.setdefault(role, [])
            for image in images:
                if image not in found[role]:
                    found[role].append(image)

    mapping = (
        ("tex_base_color", "base_color"),
        ("tex_lightmap", "lightmap"),
        ("tex_normal", "normal"),
        ("tex_ramp", "ramp"),
        ("tex_metal", "metal"),
        ("tex_sdf", "sdf"),
    )
    assigned = []
    for attr, role in mapping:
        images = found.get(role) or []
        if not images:
            continue
        # Ramp 优先选"又宽又扁"的那张；其余取第一张
        choice = images[0]
        if role == "ramp":
            for image in images:
                try:
                    width, height = image.size
                except (AttributeError, TypeError):
                    continue
                if height and width >= height * 4:
                    choice = image
                    break
        if write_slots and getattr(group, attr, None) is None:
            setattr(group, attr, choice)
            utils.set_image_colorspace(choice, role)
            assigned.append("%s=%s" % (attr, choice.name))

    # 瞳孔 / 花纹贴图不参与自动识别（命名过于自由），保持用户手动指定
    if assigned:
        log.append("自动识别贴图：%s" % ", ".join(assigned))
    return found


# --------------------------------------------------------------------------------------
# 组级操作
# --------------------------------------------------------------------------------------

def apply_group(context, group, force_rebuild: bool = False):
    """把整个组应用到组内全部材质（"应用整个组"）。"""
    report = []
    materials = group.material_list()
    if not materials:
        # 组里没有材质时，至少保证组材质本身被创建出来
        material, created = ensure_group_material(group, force_rebuild=force_rebuild)
        report.append("组内没有材质，已生成 %s" % material.name)
        return report

    # 组的主材质（用于"应用整个组"时同步参数）
    canonical, created = ensure_group_material(group, force_rebuild=force_rebuild)
    for material in materials:
        if material == canonical:
            continue
        master = utils.find_group_instance(material, shader_nodes.G_MASTER)
        if master is None:
            # 不是 NPR 材质：把它替换成组的主材质（保持槽位不变）
            _replace_material_everywhere(material, canonical)
            report.append("%s 不是 NPR 材质，已替换为 %s" % (material.name, canonical.name))
            continue
        _configure_master_inputs(master, group)
        _apply_material_settings(material, group, has_alpha=group.tex_alpha is not None)
        utils.set_material_group(material, group.name, group.part)
        report.append("已更新 %s" % material.name)

    if group.outline_enable:
        apply_outline(_objects_using_materials(group.material_list()), group,
                      mode=group.outline_mode, report=report)
    report.append("已应用整个组「%s」（%d 个材质）" % (group.name, len(materials) + 1))
    return report


def _replace_material_everywhere(old, new) -> int:
    count = 0
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for slot in obj.material_slots:
            if slot.material == old:
                slot.material = new
                count += 1
    return count


def _objects_using_materials(materials):
    wanted = set(materials)
    result = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for slot in obj.material_slots:
            if slot.material in wanted:
                result.append(obj)
                break
    return result


def read_back_group(group, material=None) -> list:
    """从材质实例反读参数回组（"从材质反读"）。"""
    report = []
    materials = [material] if material is not None else group.material_list()
    master = None
    for candidate in materials:
        if candidate is None:
            continue
        master = utils.find_group_instance(candidate, shader_nodes.G_MASTER)
        if master is not None:
            break
    if master is None:
        report.append("没有找到 NPR_Shader 实例，无法反读")
        return report

    def read(name, default=None):
        socket = utils.get_input(master, name)
        if socket is None:
            return default
        try:
            return socket.default_value
        except AttributeError:
            return default

    for attr, socket in MASTER_VALUE_SLOTS:
        value = read(socket)
        if value is None:
            continue
        try:
            setattr(group, attr, float(value))
        except (TypeError, ValueError):
            continue
    for attr, socket in MASTER_COLOR_SLOTS:
        value = read(socket)
        if value is None:
            continue
        try:
            setattr(group, attr, tuple(value))
        except (TypeError, ValueError):
            continue
    for attr, socket in MASTER_FLAG_SLOTS:
        value = read(socket)
        if value is None:
            continue
        try:
            setattr(group, attr, bool(round(float(value))))
        except (TypeError, ValueError):
            continue

    # 部位：取被置 1 的 mask
    for part in utils.MASK_PARTS:
        value = read(part, 0.0)
        try:
            if float(value) >= 0.5:
                group.part = part
                break
        except (TypeError, ValueError):
            continue

    euler = read("Light Euler")
    if euler is not None:
        try:
            group.light_euler = tuple(euler)
        except (TypeError, ValueError):
            pass
    rim_intensity = read("Rim Intensity")
    if rim_intensity is not None:
        try:
            group.rim_intensity = float(rim_intensity)
        except (TypeError, ValueError):
            pass

    # 贴图：从材质里的图像纹理节点反查
    owner = None
    for candidate in materials:
        if candidate is not None and utils.find_group_instance(candidate, shader_nodes.G_MASTER) is not None:
            owner = candidate
            break
    if owner is not None:
        images = utils.collect_material_textures(owner)
        if images:
            report.append("材质内识别到贴图用途：%s" % ", ".join(sorted(images.keys())))
    report.append("已从 %s 反读参数" % master.id_data.name)
    return report


def reset_group(group) -> None:
    """把组参数恢复为参考文件默认值（保留组名、部位与贴图）。

    ``base_brightness`` 恢复成 **1.0**（中性）而不是参考文件的 0.2：
    参考文件的 0.2 是"基础色贴图已经存在时的整体压暗系数"，而插件在**没有贴图**
    时让贴图链输出白色占位，若沿用 0.2 会把整幅画面压成近黑（实测默认参数渲染
    为 0,0,0）。1.0 让"没贴图 → 显示你设的基础色"这一直觉行为成立；
    想复刻参考文件的压暗效果时把这个值调回 0.2 即可。
    """
    defaults = {
        "base_color": (1.0, 1.0, 1.0, 1.0),
        "base_brightness": 1.0,
        "base_color_gain": 1.0,
        "light_euler": shader_nodes.REF_LIGHT_EULER,
        "light_intensity": 1.0,
        "ao_bias": 0.1,
        "ao_smooth_lo": shader_nodes.REF_AO_SMOOTH_LO,
        "ao_smooth_hi": shader_nodes.REF_AO_SMOOTH_HI,
        "ao_add": 0.1,
        "shadow_threshold": 0.35,
        "specular_enable": True,
        "spec_gloss": shader_nodes.REF_GLOSS,
        "spec_darken": shader_nodes.REF_SPEC_DARKEN,
        "spec_threshold": shader_nodes.REF_SPEC_THRESHOLD,
        "metal_threshold": shader_nodes.REF_METAL_THRESHOLD,
        "metal_enable": True,
        "spec_crystal_threshold": shader_nodes.REF_SPEC_CRYSTAL,
        "crystal": False,
        "rim_enable": True,
        "rim_color": (1.0, 1.0, 1.0, 1.0),
        "rim_intensity": 1.0,
        "rim_power": shader_nodes.REF_RIM_POWER,
        "rim_looseness": 0.2,
        "rim_lo": shader_nodes.REF_RIM_LO,
        "rim_hi": shader_nodes.REF_RIM_HI,
        "sdf_enable": False,
        "head_o": shader_nodes.REF_HEAD_O,
        "head_front": shader_nodes.REF_HEAD_FRONT,
        "head_right": shader_nodes.REF_HEAD_RIGHT,
        "ramp_enable": False,
        "ramp_strength": 0.35,
        "ramp_band_0": shader_nodes.REF_RAMP_BANDS[0],
        "ramp_band_1": shader_nodes.REF_RAMP_BANDS[1],
        "ramp_band_2": shader_nodes.REF_RAMP_BANDS[2],
        "ramp_band_3": shader_nodes.REF_RAMP_BANDS[3],
        "ramp_band_4": shader_nodes.REF_RAMP_BANDS[4],
        "ramp_band_scale": shader_nodes.REF_RAMP_STEP,
        "ramp_band_base": shader_nodes.REF_RAMP_BASE,
        "surface_render_method": 'DITHERED',
        "halo_brightness": 1.0,
        "detail_strength": 0.0,
        "emission_color": (1.0, 1.0, 1.0, 1.0),
        "emission_strength": 1.0,
        "alpha_threshold": 0.5,
    }
    for attr, value in defaults.items():
        try:
            setattr(group, attr, value)
        except (AttributeError, TypeError, ValueError):
            continue
