# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Shader — 描边（倒角外壳 / Inverted Hull）模块。

参考文件 OdetteV3.blend 中**没有任何描边实现**（已核实：0 个 Solidify 修改器、
Freestyle 关闭、无 Line Art 材质、无 Grease Pencil、合成器只有 Bloom）。
因此本模块按用户确认的技术路线实现：

    复制网格 → Solidify（外扩 + 翻转法线）→ 背面剔除 → 纯色/贴图 Emission 描边材质

为什么用独立描边对象而不是直接给源物体加修改器：
  * 一个物体常有多个材质槽，各自需要不同的描边颜色与粗细；
  * 直接加修改器会改变源网格的渲染状态（法线、材质槽索引）；
  * 独立对象可以整体开关/删除/重建，不污染原始资产。

全部参数映射见 docs/REFERENCE_MAPPING.md 的「描边」章节。
"""

from __future__ import annotations

import bpy

from . import shader_nodes, utils
from .utils import get_input as IN

#: 描边对象上记录的源对象名称
KEY_SOURCE = "npr_outline_of"
#: 描边对象上记录的材质组名
KEY_GROUP = "npr_outline_group"


# --------------------------------------------------------------------------------------
# 材质
# --------------------------------------------------------------------------------------

def _ensure_outline_material(group, source_material=None):
    """创建 / 更新一条描边材质，返回材质对象。

    描边材质结构（与参考文件主组同样的"节点组 → Emission"风格）：
        NPR_OutlineShader 节点组 ── Outline(Shader) ──→ 材质输出.Surface
    另有一个 ShaderNodeAttribute 取物体颜色（object.color），
    以及一个图像纹理驱动描边贴图。
    """
    name = utils.outline_material_name(group.name)
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    utils.clear_node_tree(tree)

    group_tree = utils.npr_node_group(shader_nodes.G_OUTLINE, create=True)
    node = tree.nodes.new('ShaderNodeGroup')
    node.node_tree = group_tree
    node.name = "描边着色"
    node.label = group.name
    node.location = (0.0, 0.0)

    output = utils.ensure_material_output(material)
    output.location = (320.0, 0.0)
    utils.link(tree, node, "Outline", output, "Surface")

    # 物体颜色（bpy.types.Object.color）→ 节点组
    attr = tree.nodes.new('ShaderNodeAttribute')
    attr.name = "物体颜色"
    attr.attribute_type = 'GEOMETRY'
    try:
        attr.attribute_name = "Color"
    except (AttributeError, TypeError):
        pass
    attr.location = (-320.0, -200.0)

    # 描边贴图
    image_node = tree.nodes.new('ShaderNodeTexImage')
    image_node.name = "描边贴图"
    image_node.location = (-320.0, 120.0)
    image_node.image = group.outline_tex if group.outline_use_texture else None
    uv_node = tree.nodes.new('ShaderNodeUVMap')
    uv_node.name = "UV"
    uv_node.location = (-520.0, 120.0)
    utils.link(tree, uv_node, "UV", image_node, "Vector")

    # 参数写入
    utils.set_default(node, "Color", tuple(group.outline_color))
    utils.set_default(node, "Use Object Color", 1.0 if _use_object_color() else 0.0)
    utils.set_default(node, "Texture Mix", 1.0 if group.outline_use_texture else 0.0)
    utils.set_default(node, "Threshold", group.outline_threshold)
    utils.set_default(node, "Alpha", group.outline_alpha)
    utils.set_default(node, "Emission Strength", group.outline_emission)
    utils.set_default(node, "Texture", (1.0, 1.0, 1.0, 1.0))

    utils.link(tree, attr, "Color", node, "Object Color")
    if group.outline_use_texture:
        utils.link(tree, image_node, "Color", node, "Texture")

    # 材质级设置
    material.use_backface_culling = _use_backface_culling()
    if group.outline_alpha < 1.0:
        utils.set_prop(material, "surface_render_method", 'BLENDED')
    else:
        utils.set_prop(material, "surface_render_method", 'DITHERED')
    utils.set_prop(material, "use_transparent_shadow", False)
    try:
        material.diffuse_color = tuple(group.outline_color)
    except (AttributeError, TypeError):
        pass
    material[utils.KEY_GENERATED] = utils.VERSION_STR
    material[KEY_GROUP] = group.name
    if source_material is not None:
        material["npr_outline_source_material"] = source_material.name
    return material


def _use_object_color() -> bool:
    settings = _settings()
    return bool(settings and settings.outline_use_object_color)


def _use_backface_culling() -> bool:
    settings = _settings()
    if settings is None:
        return True
    return bool(settings.outline_use_backface_culling)


def _settings():
    try:
        return bpy.context.scene.npr_settings
    except AttributeError:
        return None


# --------------------------------------------------------------------------------------
# 对象
# --------------------------------------------------------------------------------------

def outline_objects_for(source_object):
    """返回某个源对象对应的所有 NPR 描边对象。"""
    result = []
    for obj in bpy.data.objects:
        if obj.get(KEY_SOURCE, "") == source_object.name and obj.type == 'MESH':
            result.append(obj)
    return result


def is_outline_object(obj) -> bool:
    return bool(obj.get(KEY_SOURCE, ""))


def find_outline(source_object, group=None):
    """查找某个源对象 + 某个材质组对应的描边对象。"""
    for obj in outline_objects_for(source_object):
        if group is None or obj.get(KEY_GROUP, "") == group.name:
            return obj
    return None


def _link_like_source(obj, source) -> None:
    """把描边对象放进与源对象相同的集合，便于一起显示 / 隐藏。"""
    linked = False
    for collection in source.users_collection:
        try:
            collection.objects.link(obj)
            linked = True
        except RuntimeError:
            continue
    if not linked:
        bpy.context.scene.collection.objects.link(obj)


def _sync_transform(obj, source) -> None:
    obj.parent = source.parent
    obj.parent_type = source.parent_type
    try:
        obj.matrix_parent_inverse = source.matrix_parent_inverse.copy()
    except (AttributeError, ValueError):
        pass
    obj.matrix_basis = source.matrix_basis.copy()
    obj.matrix_world = source.matrix_world.copy()


def _material_slots_for(source_object, group):
    """找出源对象上属于该组的材质槽索引。

    Returns:
        [(slot_index, material), ...]；若物体上没有任何该组材质，
        则返回 [(0, None)] 表示"整物体使用该组的描边设置"。
    """
    slots = []
    for index, slot in enumerate(source_object.material_slots):
        material = slot.material
        if material is None:
            continue
        if group.has_material(material) or utils.material_group_name(material) == group.name:
            slots.append((index, material))
    if not slots:
        return [(0, None)]
    return slots


def _configure_solidify(modifier, group, scale) -> None:
    thickness = max(0.0, float(group.outline_thickness)) * scale
    utils.set_prop(modifier, "thickness", thickness)
    utils.set_prop(modifier, "offset", float(group.outline_offset))
    utils.set_prop(modifier, "use_flip_normals", True)
    utils.set_prop(modifier, "use_rim", True)
    utils.set_prop(modifier, "use_rim_only", False)
    utils.set_prop(modifier, "use_even_offset", bool(group.outline_even))
    utils.set_prop(modifier, "use_quality_normals", True)
    utils.set_prop(modifier, "use_angle_limit", False)
    utils.set_prop(modifier, "nonmanifold_thickness_mode", 'FIXED')


def _mesh_scale(obj) -> float:
    """取物体缩放的平均值，用于把"世界粗细"换算成局部厚度。"""
    try:
        scale = obj.matrix_world.to_scale()
    except (AttributeError, ValueError):
        return 1.0
    average = (abs(scale.x) + abs(scale.y) + abs(scale.z)) / 3.0
    return average if average > 1e-9 else 1.0


def apply_outline(objects, group, mode: str = 'OBJECT', report=None):
    """为一批物体添加 / 更新属于某个材质组的描边。

    Args:
        objects: 源物体列表（网格类型）。
        group:   :class:`~npr_shader.properties.NprMaterialGroup`。
        mode:    ``'OBJECT'`` 独立描边对象 / ``'MODIFIER'`` 直接加在源物体上。
        report:  可选列表，用于收集人类可读的操作记录。

    Returns:
        dict(created=[...], updated=[...], skipped=[...])
    """
    log = report if report is not None else []
    result = {"created": [], "updated": [], "skipped": []}
    if group is None or not group.outline_enable:
        log.append("组「%s」未启用描边，跳过" % (group.name if group else "?"))
        return result

    settings = _settings()
    cleanup = bool(settings.delete_source_outlines) if settings else True

    for source in objects:
        if source is None or source.type != 'MESH':
            continue
        material = source.data
        if material is None:
            continue

        if cleanup:
            for stale in outline_objects_for(source):
                if stale.get(KEY_GROUP, "") == group.name:
                    continue
                _remove_object(stale)

        if mode == 'MODIFIER':
            modifier = None
            for existing in source.modifiers:
                if existing.type == 'SOLIDIFY' and existing.name.startswith("NPR_Outline"):
                    modifier = existing
                    break
            if modifier is None:
                modifier = source.modifiers.new("NPR_Outline_%s" % utils.sanitize_name(group.name), 'SOLIDIFY')
                created = True
            else:
                created = False
            _configure_solidify(modifier, group, _mesh_scale(source))
            material = _ensure_outline_material(group)
            if material.name not in [slot.material.name for slot in source.material_slots if slot.material]:
                source.data.materials.append(material)
            modifier.material_offset = _solidify_material_offset(source, material)
            modifier.material_offset_rim = modifier.material_offset
            source["npr_outline_group"] = group.name
            (result["created"] if created else result["updated"]).append(source.name)
            continue

        # ---- 独立描边对象 ----
        outline = find_outline(source, group)
        created = outline is None
        if outline is None:
            mesh_copy = source.data.copy()
            mesh_copy.name = "%s_NPROutline_%s" % (source.data.name, utils.sanitize_name(group.name))
            outline = bpy.data.objects.new(
                "NPR_Outline_%s_%s" % (utils.sanitize_name(group.name), source.name), mesh_copy)
            _link_like_source(outline, source)
            outline[KEY_SOURCE] = source.name
            outline[KEY_GROUP] = group.name
            outline.hide_select = False
            outline.display_type = source.display_type

        _sync_transform(outline, source)

        # 只保留属于该组的材质槽；不匹配时整物体使用该组设置
        wanted = _material_slots_for(source, group)
        target_material = _ensure_outline_material(group, wanted[0][1] if wanted else None)
        mesh = outline.data
        mesh.materials.clear()
        for _index, packed in wanted:
            mesh.materials.append(target_material)
        if not mesh.materials:
            mesh.materials.append(target_material)

        # Solidify
        modifier = None
        for existing in outline.modifiers:
            if existing.type == 'SOLIDIFY':
                modifier = existing
                break
        if modifier is None:
            modifier = outline.modifiers.new("NPR_Outline", 'SOLIDIFY')
        _configure_solidify(modifier, group, _mesh_scale(outline))
        modifier.material_offset = 0
        modifier.material_offset_rim = 0
        outline["npr_outline_thickness"] = float(group.outline_thickness)

        (result["created"] if created else result["updated"]).append(source.name)

    log.append("描边：新增 %d 个 / 更新 %d 个" % (len(result["created"]), len(result["updated"])))
    return result


def _solidify_material_offset(obj, material) -> int:
    """找到材质在物体上的槽位索引，供修改器的 material_offset 使用。"""
    for index, slot in enumerate(obj.material_slots):
        if slot.material == material:
            return index
    return 0


def _remove_object(obj) -> None:
    mesh = obj.data
    name = obj.name
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    utils.log("已删除旧描边对象 %s" % name)


def remove_outlines(objects=None, group=None) -> int:
    """删除描边对象。

    Args:
        objects: 限定这些源对象；None 表示全部。
        group:   限定该材质组；None 表示全部组。

    Returns:
        删除的描边对象数量。
    """
    source_names = {obj.name for obj in objects} if objects else None
    removed = 0
    for obj in list(bpy.data.objects):
        if obj.type != 'MESH':
            continue
        owner = obj.get(KEY_SOURCE, "")
        if not owner:
            continue
        if source_names is not None and owner not in source_names:
            continue
        if group is not None and obj.get(KEY_GROUP, "") != group.name:
            continue
        _remove_object(obj)
        removed += 1
    return removed


def remove_modifier_outlines(objects) -> int:
    """移除源物体上的 NPR Solidify 修改器。"""
    removed = 0
    for obj in objects or []:
        for modifier in list(obj.modifiers):
            if modifier.type == 'SOLIDIFY' and modifier.name.startswith("NPR_Outline"):
                obj.modifiers.remove(modifier)
                removed += 1
        if "npr_outline_group" in obj:
            del obj["npr_outline_group"]
    return removed


def cleanup_all() -> int:
    """清空所有 NPR 描边对象与修改器（供"清理旧描边"按钮使用）。"""
    total = remove_outlines()
    meshes = 0
    for mesh in list(bpy.data.meshes):
        if mesh.name.endswith("_NPROutline") or "_NPROutline_" in mesh.name:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
                meshes += 1
    return total + meshes


def update_group_outlines(group, objects=None) -> dict:
    """按组内最新参数刷新描边（粗细 / 颜色 / 贴图 / 混合模式）。"""
    targets = list(objects) if objects else _objects_using_group(group)
    if not targets:
        return {"created": [], "updated": [], "skipped": []}
    return apply_outline(targets, group, mode=group.outline_mode)


def _objects_using_group(group):
    """找出所有使用了该组材质的物体。"""
    materials = set(group.material_list())
    if not materials:
        return []
    result = []
    seen = set()
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.name in seen:
            continue
        for slot in obj.material_slots:
            if slot.material in materials:
                result.append(obj)
                seen.add(obj.name)
                break
    return result


def selftest(objects, group) -> list:
    """描边自检：返回人类可读的问题列表（为空表示通过）。"""
    issues = []
    if group is None:
        return ["没有选中任何材质组"]
    if group.outline_thickness <= 0.0:
        issues.append("描边粗细为 0，描边不可见")
    if not _use_backface_culling():
        issues.append("未开启描边背面剔除：倒角外壳会覆盖整个模型（建议开启）")
    if group.outline_mode == 'OBJECT':
        if not objects:
            return issues + ["没有可用于描边的物体"]
        for source in objects:
            outline = find_outline(source, group)
            if outline is None:
                issues.append("物体 %s 尚无描边对象" % source.name)
                continue
            if not any(m.type == 'SOLIDIFY' for m in outline.modifiers):
                issues.append("描边对象 %s 缺少 Solidify 修改器" % outline.name)
            if not outline.material_slots:
                issues.append("描边对象 %s 没有材质" % outline.name)
    return issues
