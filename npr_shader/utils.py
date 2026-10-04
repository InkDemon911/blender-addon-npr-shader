# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Shader — 通用工具层。

本模块只依赖 bpy / bl_math / mathutils，不依赖插件内其他模块，可被任意层导入。

职责：
  * 版本检测与降级
  * 节点树 / 节点组的创建与幂等查找
  * 材质与节点组之间的 NPR 元数据（存放在 ID 自定义属性里，不污染命名空间）
  * 贴图用途识别（基础色 / 光照 / 法线 / Ramp / 金属 / SDF …）
  * 轻量日志（写入场景设置，供 UI 显示）
"""

from __future__ import annotations

import re

import bpy
from mathutils import Vector

# --------------------------------------------------------------------------------------
# 版本
# --------------------------------------------------------------------------------------

#: 插件版本（与 bl_info["version"] 保持一致）
VERSION = (1, 0, 0)
VERSION_STR = ".".join(str(v) for v in VERSION)

#: 节点组内部结构版本。改变内部节点拓扑时必须 +1，以便已保存的文件触发重建。
NODE_GROUP_VERSION = 1

#: 所有插件创建的节点组统一前缀
NODE_GROUP_PREFIX = "NPR_"

#: 材质元数据键
KEY_GROUP = "npr_group"
KEY_PART = "npr_part"
KEY_NODE_VERSION = "npr_ng_version"
KEY_GENERATED = "npr_generated"

#: 参考文件（OdetteV3.blend）里固定的部位枚举，接口名必须逐字一致
PART_ITEMS = (
    ("Face", "Face（脸部）", "对应参考文件 Shader 组的 Face 输入"),
    ("Body01", "Body01（身体 01 / 裙装）", "对应参考文件 Shader 组的 Body01 输入"),
    ("Body", "Body（身体）", "对应参考文件 Shader 组的 Body 输入"),
    ("Hair", "Hair（头发）", "对应参考文件 Shader 组的 Hair 输入"),
    ("Eyes", "Eyes（眼睛）", "对应参考文件 Shader 组的 Eyes 输入"),
    ("Crystal", "Crystal（晶体 / 高光分支）", "对应参考文件 Shader 组的 Crystal 输入"),
)
PART_NAMES = tuple(item[0] for item in PART_ITEMS)

#: 非部位参数（Crystal 走单独接口）
MASK_PARTS = ("Face", "Body01", "Body", "Hair", "Eyes")


def blender_version() -> tuple:
    """返回 (major, minor, patch)。"""
    return tuple(bpy.app.version)


def is_52_or_newer() -> bool:
    return bpy.app.version >= (5, 2, 0)


def require_engine(scene=None) -> bool:
    """确保场景使用 EEVEE。参考文件的工作流完全依赖 EEVEE。"""
    scene = scene or bpy.context.scene
    try:
        if scene.render.engine != 'BLENDER_EEVEE':
            scene.render.engine = 'BLENDER_EEVEE'
            return True
    except TypeError:
        # 极端情况下枚举里没有 BLENDER_EEVEE（非 EEVEE 构建）
        return False
    return False


# --------------------------------------------------------------------------------------
# 元数据
# --------------------------------------------------------------------------------------

def material_group_name(material) -> str:
    """材质所属的组名；不属于任何组时返回空串。"""
    if material is None:
        return ""
    try:
        return material.get(KEY_GROUP, "")
    except (AttributeError, TypeError):
        return ""


def set_material_group(material, group_name: str, part: str = "") -> None:
    if material is None:
        return
    if group_name:
        material[KEY_GROUP] = group_name
    elif KEY_GROUP in material:
        del material[KEY_GROUP]
    if part:
        material[KEY_PART] = part
    elif KEY_PART in material:
        del material[KEY_PART]
    material[KEY_GENERATED] = VERSION_STR


def is_npr_material(material) -> bool:
    """判断材质是否由本插件生成（或已被本插件接管）。"""
    if material is None or not material.use_nodes or material.node_tree is None:
        return False
    if KEY_GROUP in material:
        return True
    for node in material.node_tree.nodes:
        if node.bl_idname == 'ShaderNodeGroup' and node.node_tree is not None:
            if node.node_tree.name.startswith(NODE_GROUP_PREFIX):
                return True
    return False


# --------------------------------------------------------------------------------------
# 节点树工具
# --------------------------------------------------------------------------------------

def get_node(node_tree, name: str, bl_idname: str | None = None):
    """按名称精确查找节点，可选同时校验类型。"""
    if node_tree is None:
        return None
    node = node_tree.nodes.get(name)
    if node is None:
        return None
    if bl_idname is not None and node.bl_idname != bl_idname:
        return None
    return node


def find_node(node_tree, bl_idname: str, label: str | None = None):
    """按类型 + 可选 label 查找第一个匹配节点（参考文件用 label 标注部位）。"""
    if node_tree is None:
        return None
    for node in node_tree.nodes:
        if node.bl_idname != bl_idname:
            continue
        if label is not None and node.label != label:
            continue
        return node
    return None


def clear_node_tree(node_tree) -> None:
    """清空节点树。"""
    if node_tree is None:
        return
    for node in list(node_tree.nodes):
        node_tree.nodes.remove(node)


def socket_ids_by_name(interface) -> dict:
    """把接口里每个输入/输出插槽的 **identifier** 按名称记下来。

    用途：``ShaderNodeMix`` 这类节点有多个同名不同类型的输出（四个 ``Result``），
    实例上的 identifier 与"名称"完全对不上（``Result`` 的 identifier 可能是
    ``Result_Float``，而名称为 ``Result`` 的插槽 identifier 又是 ``Result_Color``）。
    构建节点组时先记下这张对照表，之后按名称连线就能精确定位，不会连错类型。

    节点组接口插槽的 ``identifier`` 通常是自动编号（``Socket_0``），而 Group Input /
    Group Output **节点上的插槽** 会沿用接口插槽的 ``identifier``，因此这张表
    正是"接口名 → 节点插槽 identifier"的桥梁；同时把 ``name`` 也登记一份，
    以兼容某些版本里节点插槽沿用接口名称的情况。
    """
    mapping = {}
    for item in interface.items_tree:
        if getattr(item, "item_type", "") != 'SOCKET':
            continue
        side = item.in_out
        for key in {item.name, item.identifier}:
            if key:
                entry = "%s:%s" % (side, item.identifier)
                bucket = mapping.setdefault(key, [])
                if entry not in bucket:
                    bucket.append(entry)
    return mapping


def _connected_type(sock):
    """由插槽已有的连线推断它所属的"数据通路类型"。

    ``ShaderNodeMix`` 把 A/B/Result 各做了 4 个同名变体，Blender 用插槽上的
    数据类型成员位来过滤：一旦某个变体被连成 Color，其余变体就不可用了。
    因此"按名称 + 已有连线类型"能唯一确定要连哪一个变体。
    """
    try:
        for link in sock.links:
            other = link.to_socket if link.from_socket == sock else link.from_socket
            return other.bl_idname
    except (AttributeError, TypeError, ReferenceError):
        pass
    return None


def _normalize_ref(ref):
    """把 ``wire`` 的端点统一成"节点名或节点对象"。

    允许三种写法：
      * 节点对象（``hasattr(outputs)``）
      * 节点名字符串
      * 自己包装的 ``(节点名或对象, 插槽索引)`` 二元组
    早先允许直接传插槽对象，结果插槽对象会被当成"节点名"查表查不到，
    产生一条条无效连线——所以这里统一收口。
    """
    if isinstance(ref, tuple) and len(ref) == 2:
        return ref[0]
    return ref


def _effective_input(node, name_or_id):
    """按名称解析输入插槽，并利用已有连线把同名多类型插槽定到正确的变体上。"""
    if node is None or name_or_id is None:
        return None
    if not isinstance(name_or_id, str):
        return name_or_id
    candidates = [sock for sock in node.inputs if sock.name == name_or_id]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    for sock in candidates:
        if _connected_type(sock):
            return sock
    wanted = None
    for sock in candidates:
        other = node.inputs.get(sock.identifier)
        del other
    # 尚未连接的复合输入：只在同组内挑一个代表（wire() 之后会按源类型纠正）
    groups = {}
    for sock in candidates:
        groups.setdefault(sock.bl_idname, []).append(sock)
    if wanted and wanted in groups:
        return groups[wanted][0]
    return candidates[0]


def _effective_output(node, name_or_id):
    """按名称解析输出插槽，并利用已有连线把同名多类型插槽定到正确的变体上。"""
    if node is None or name_or_id is None:
        return None
    if not isinstance(name_or_id, str):
        return name_or_id
    candidates = [sock for sock in node.outputs if sock.name == name_or_id]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    for sock in candidates:
        if _connected_type(sock):
            return sock
    return candidates[0]


def _resolve_socket(collection, name_or_id, index: int):
    """在输入/输出插槽集合里定位插槽。

    解析顺序（每一步都是踩坑换来的，不要随意调整）：

      1. **identifier 精确匹配**。这是唯一不会歧义的键
         （``Socket_1`` / ``Value_001`` / ``A_Color`` / ``Result_Float`` …）。
         必须放在最前面：否则传 ``"Socket_1"`` 时会先按"名称"匹配到名字叫
         ``Result`` 的那个插槽，把两条连线都接到同一点上。
      2. **名称匹配**，取第一个同名插槽：``ShaderNodeMix`` 的 A / B / Result
         各有 4 个同名变体，连接代码通常只写 ``"A"`` / ``"Result"``，
         此时按声明顺序取第一个（FLOAT 变体），由调用方按另一端类型纠正。
      3. ``index`` 序号兜底；传负数表示"找不到就返回 None"，让调用方立刻发现
         写错了名字，而不是静默连到别的插槽上。

    注意：``collection._index()`` 匹配的是 identifier 而不是 UI 名称，
    例如 ``_index("x")`` 会命中 identifier 为 ``x`` 的插槽，而不是名为 ``x`` 的插槽，
    因此这里全部手写遍历，不依赖 ``_index()``。
    """
    if name_or_id is None:
        return collection[index] if 0 <= index < len(collection) else None
    # 1) identifier 精确匹配
    for sock in collection:
        if sock.identifier == name_or_id:
            return sock
    # 2) 名称匹配（同名多类型时优先取"已经有连线"的那个变体，否则取声明顺序第一个）
    if isinstance(name_or_id, str):
        matches = [sock for sock in collection if sock.name == name_or_id]
        if matches:
            for sock in matches:
                if _connected_type(sock):
                    return sock
            return matches[0]
        # Blender 自带的按键查找（按 identifier），可能抛 KeyError
        try:
            return collection[name_or_id]
        except (KeyError, TypeError, IndexError, ValueError):
            pass
    # 3) 序号兜底
    if index < 0:
        return None
    return collection[index] if 0 <= index < len(collection) else None


def get_input(node, name_or_id, index: int = 0):
    """按 identifier / 名称（声明顺序）取输入插槽。

    输入插槽基本都有稳定 identifier（``Value_001`` / ``A_Color`` …），
    但**节点组接口生成的插槽 identifier 是自动编号**（``Socket_0`` / ``Socket_1``），
    所以这里保留按名称、按声明顺序的兜底（``index=0``）。

    注意：绝不回退到"任意第 0 个插槽"去猜——曾经因为按 identifier 字母序查找，
    把两个同名 ``Result`` 插槽搞混，导致 BaseColor 组的颜色输出被接到了 Alpha 链上。
    """
    if node is None:
        return None
    return _resolve_socket(node.inputs, name_or_id, index)


def get_output(node, name_or_id=None, index: int = 0):
    """按 identifier / 名称 / 序号取输出插槽。

    identifier 优先（见 :func:`_resolve_socket`），因此 ``"Result_Color"`` 这类
    带类型后缀的 identifier 一定能命中正确插槽，而 ``"Result"`` 会命中第一个
    同名插槽（通常是 FLOAT），调用方可按需传入 identifier。
    """
    if node is None:
        return None
    return _resolve_socket(node.outputs, name_or_id, index)


def link(node_tree, from_node, from_socket, to_node, to_socket, index: int = 0):
    """建立连接。

    Args:
        from_socket / to_socket: 插槽 identifier、名称或插槽对象。
        index: 名称解析失败时的回退索引；传 -1 表示"解析失败就不要连"，
               用于避免静默连到同名但类型不符的插槽（如 Mix 节点的 4 个 Result）。
    """
    if node_tree is None or from_node is None or to_node is None:
        return None
    out = get_output(from_node, from_socket, index)
    inp = get_input(to_node, to_socket)
    if out is None or inp is None:
        return None
    for existing in list(inp.links):
        node_tree.links.remove(existing)
    return node_tree.links.new(out, inp)


def remove_links_to(node_tree, node, socket=None) -> None:
    if node_tree is None or node is None:
        return
    targets = [socket] if socket is not None else list(node.inputs)
    for sock in targets:
        for existing in list(sock.links):
            node_tree.links.remove(existing)


def unlink_input(node_tree, node, socket) -> None:
    """断开某个输入的连接（保留节点默认值）。"""
    if node_tree is None or node is None:
        return
    sock = get_input(node, socket)
    if sock is None:
        return
    for existing in list(sock.links):
        node_tree.links.remove(existing)


def set_default(node, socket, value) -> None:
    """安全设置输入默认值（插槽不存在或类型不符时忽略）。"""
    sock = get_input(node, socket)
    if sock is None:
        return
    try:
        if isinstance(value, (tuple, list, Vector)):
            sock.default_value = tuple(value)
        else:
            sock.default_value = value
    except (AttributeError, TypeError, ValueError):
        pass


def set_prop(node, name: str, value) -> None:
    """安全设置节点属性（不同版本缺属性时忽略）。"""
    if node is None:
        return
    try:
        if hasattr(node, name):
            setattr(node, name, value)
    except (AttributeError, TypeError, ValueError):
        pass


def mix_node(node_tree, label: str = "", blend_type: str = "MIX",
             data_type: str = "RGBA", location=(0.0, 0.0), factor: float = None):
    """创建 ShaderNodeMix 并设置参考文件里固定的属性组合。

    参考文件中所有 Mix 节点均为 ``clamp_factor=True`` / ``factor_mode=UNIFORM``。

    ``factor`` 用于把 Factor 显式写死。**这非常关键**：Factor 是"混合权重"，
    Blender 默认 0.5，会让 MULTIPLY / ADD 这类运算只生效一半
    （实测：基础色 0.1 被稀释成 0.55，整片偏白）。
    因此凡是"该运算必须完全生效"的场合（MULTIPLY / ADD）都要传 ``factor=1.0``；
    由接口或上游连线驱动 Factor 的场合不要传，保持未连接。
    """
    node = node_tree.nodes.new('ShaderNodeMix')
    # 顺序很重要：先定 data_type，再定 blend_type。
    # data_type 决定存在哪些插槽（FLOAT 下没有 A_Color/B_Color/Result_Color）；
    # 若先设 blend_type 再设 data_type，部分版本会出现"节点属性是 RGBA、
    # 插槽却仍是 FLOAT 集合"的不一致状态，导致颜色连线静默失效。
    set_prop(node, "data_type", data_type)
    set_prop(node, "blend_type", blend_type)
    set_prop(node, "clamp_factor", True)
    set_prop(node, "factor_mode", "UNIFORM")
    # 复核一次：确保插槽集合与 data_type 匹配（不一致时补设）
    if data_type == 'RGBA' and not any(
            getattr(s, "identifier", "") == "A_Color" for s in node.inputs):
        try:
            node.data_type = 'FLOAT'
            node.data_type = 'RGBA'
        except (AttributeError, TypeError):
            pass
    if factor is not None:
        set_default(node, "Factor", float(factor))
    node.location = location
    if label:
        node.label = label
    return node


def math_node(node_tree, operation: str, location=(0.0, 0.0), label: str = ""):
    node = node_tree.nodes.new('ShaderNodeMath')
    set_prop(node, "operation", operation)
    node.location = location
    if label:
        node.label = label
    return node


def vector_math_node(node_tree, operation: str, location=(0.0, 0.0), label: str = ""):
    node = node_tree.nodes.new('ShaderNodeVectorMath')
    set_prop(node, "operation", operation)
    node.location = location
    if label:
        node.label = label
    return node


def map_range_node(node_tree, location=(0.0, 0.0), label: str = ""):
    """参考文件中所有 MapRange 节点：data_type=FLOAT, LINEAR, clamp=True, Steps=4。"""
    node = node_tree.nodes.new('ShaderNodeMapRange')
    set_prop(node, "data_type", "FLOAT")
    set_prop(node, "interpolation_type", "LINEAR")
    set_prop(node, "clamp", True)
    set_default(node, "Steps", 4.0)
    node.location = location
    if label:
        node.label = label
    return node


def group_input_node(node_tree):
    return find_node(node_tree, 'NodeGroupInput')


def group_output_node(node_tree):
    return find_node(node_tree, 'NodeGroupOutput')


# --------------------------------------------------------------------------------------
# 节点组
# --------------------------------------------------------------------------------------

def npr_node_group(name: str, create: bool = True):
    """取（或创建）以 NPR_ 为前缀的节点组。"""
    full = name if name.startswith(NODE_GROUP_PREFIX) else NODE_GROUP_PREFIX + name
    tree = bpy.data.node_groups.get(full)
    if tree is None and create:
        tree = bpy.data.node_groups.new(full, 'ShaderNodeTree')
    return tree


def node_group_is_current(tree) -> bool:
    """节点组内部版本是否为当前版本。"""
    if tree is None:
        return False
    try:
        return int(tree.get("npr_ng_version", 0)) == NODE_GROUP_VERSION
    except (TypeError, ValueError):
        return False


def mark_node_group_version(tree, version: int = NODE_GROUP_VERSION) -> None:
    if tree is not None:
        tree["npr_ng_version"] = int(version)


def node_groups_exist() -> bool:
    """插件所需节点组是否齐全（主组存在即认为已构建）。"""
    tree = bpy.data.node_groups.get(NODE_GROUP_PREFIX + "Shader")
    return tree is not None and node_group_is_current(tree)


def new_group_instance(material, tree, location=(0.0, 0.0), label: str = ""):
    """在材质节点树里放置一个节点组实例。"""
    node = material.node_tree.nodes.new('ShaderNodeGroup')
    node.node_tree = tree
    node.location = location
    if label:
        node.label = label
    return node


def find_group_instance(material, tree_name: str):
    """在材质里查找引用了指定节点组的实例。"""
    if material is None or material.node_tree is None:
        return None
    full = tree_name if tree_name.startswith(NODE_GROUP_PREFIX) else NODE_GROUP_PREFIX + tree_name
    for node in material.node_tree.nodes:
        if node.bl_idname == 'ShaderNodeGroup' and node.node_tree is not None:
            if node.node_tree.name == full:
                return node
    return None


def ensure_material_output(material):
    """确保材质存在输出节点，返回输出节点。"""
    tree = material.node_tree
    out = None
    for node in tree.nodes:
        if node.bl_idname == 'ShaderNodeOutputMaterial' and getattr(node, "is_active_output", True):
            out = node
            break
    if out is None:
        out = tree.nodes.new('ShaderNodeOutputMaterial')
        out.location = (400.0, 0.0)
    return out


# --------------------------------------------------------------------------------------
# 贴图
# --------------------------------------------------------------------------------------

#: 色彩空间约定（严格来自参考文件的 packed 图像实测值）
COLORSPACE_SRGB = "sRGB"
COLORSPACE_DATA = "Non-Color"

#: 用途 → (命名关键词, 期望色彩空间, 尺寸特征)
TEXTURE_ROLES = (
    ("base_color", ("diffuse", "albedo", "basecolor", "base_color", "col", "color", "tex_", "皮肤", "颜"), COLORSPACE_SRGB),
    ("lightmap", ("lightmap", "light_map", "shadow", "ao", "光照", "阴影"), COLORSPACE_DATA),
    ("normal", ("normalmap", "normal_map", "normal", "nrm", "法线"), COLORSPACE_DATA),
    ("ramp", ("ramp", "toon", "渐变"), COLORSPACE_SRGB),
    ("metal", ("metal", "metallic", "specular", "spec", "金属", "高光"), COLORSPACE_DATA),
    ("sdf", ("sdf", "facelightmap", "face_shadow", "面部"), COLORSPACE_SRGB),
    ("emission", ("emission", "emissive", "glow", "自发光"), COLORSPACE_SRGB),
    ("alpha", ("alpha", "opacity", "transparency", "透明"), COLORSPACE_DATA),
    ("matcap", ("matcap", "mat_cap"), COLORSPACE_SRGB),
    ("detail", ("裙", "花纹", "trim", "pattern", "detail", "ornament", "lace"), COLORSPACE_SRGB),
)


def set_image_colorspace(image, role: str) -> None:
    """按用途设置色彩空间（None 时忽略）。"""
    if image is None:
        return
    try:
        want = COLORSPACE_DATA if role in ("lightmap", "normal", "metal", "alpha") else COLORSPACE_SRGB
        image.colorspace_settings.name = want
    except (AttributeError, TypeError):
        pass


def classify_texture(node) -> str:
    """根据节点/图像名称与色彩空间猜测贴图用途，返回 role 或空串。"""
    if node is None or node.bl_idname != 'ShaderNodeTexImage':
        return ""
    image = node.image
    if image is None:
        return ""
    haystack = " ".join(filter(None, (
        (node.label or ""), (image.name or ""), (node.name or ""),
    ))).lower()
    if not haystack:
        return ""
    # 名称关键词优先
    for role, keywords, _cs in TEXTURE_ROLES:
        for kw in keywords:
            if kw in haystack:
                return role
    # 名称无信息时按色彩空间 + 尺寸兜底：Non-Color 多为数据贴图
    try:
        if image.colorspace_settings.name == COLORSPACE_DATA:
            w, h = image.size
            if h and w and h <= 32 and w >= 64:
                return "ramp"
            return "lightmap"
    except (AttributeError, TypeError):
        pass
    return ""


def collect_material_textures(material) -> dict:
    """扫描材质里所有图像纹理节点，按用途归类。

    返回 {role: [image, ...]}；同一用途可能有多张（参考文件每个部位一张）。
    会跟随一层 Group 节点向下查找，因此能读回插件自己生成的材质。
    """
    found: dict = {}
    if material is None or material.node_tree is None:
        return found

    seen_trees = set()

    def scan(tree):
        if tree is None or id(tree) in seen_trees:
            return
        seen_trees.add(id(tree))
        for node in tree.nodes:
            if node.bl_idname == 'ShaderNodeTexImage':
                role = classify_texture(node)
                if role and node.image is not None:
                    found.setdefault(role, [])
                    if node.image not in found[role]:
                        found[role].append(node.image)
            elif node.bl_idname == 'ShaderNodeGroup' and node.node_tree is not None:
                # 只向下钻一层自有节点组，避免递归过深
                if node.node_tree.name.startswith(NODE_GROUP_PREFIX):
                    continue
                scan(node.node_tree)

    scan(material.node_tree)
    return found


def pick_texture(textures: dict, role: str, index: int = 0):
    """从归类结果里安全取第 index 张。"""
    images = textures.get(role) or []
    if 0 <= index < len(images):
        return images[index]
    return None


# --------------------------------------------------------------------------------------
# 命名
# --------------------------------------------------------------------------------------

def sanitize_name(name: str, fallback: str = "Group") -> str:
    """把用户输入变成安全的 ID 名称片段。"""
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", (name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip("_")
    return cleaned[:48] or fallback


def unique_name(base: str, existing) -> str:
    """在 existing 集合里生成不冲突的名称。"""
    if base not in existing:
        return base
    index = 1
    while "%s.%03d" % (base, index) in existing:
        index += 1
    return "%s.%03d" % (base, index)


def npr_material_name(group_name: str, part: str) -> str:
    return "NPR_%s_%s" % (sanitize_name(group_name), part)


def outline_material_name(group_name: str) -> str:
    return "NPR_Outline_%s" % sanitize_name(group_name)


# --------------------------------------------------------------------------------------
# 日志
# --------------------------------------------------------------------------------------

def log(message: str, level: str = 'INFO') -> None:
    """写入场景日志（UI 显示）。没有场景设置时退化为控制台输出。"""
    print("[NPR Shader] %s: %s" % (level, message))
    try:
        settings = getattr(bpy.context.scene, "npr_settings", None)
    except AttributeError:
        settings = None
    if settings is None:
        return
    try:
        entry = settings.log_entries.add()
        entry.message = message
        entry.level = level
        while len(settings.log_entries) > 200:
            settings.log_entries.remove(0)
        settings.log_entries_index = len(settings.log_entries) - 1
    except (AttributeError, TypeError, ReferenceError):
        pass


def clear_log() -> None:
    try:
        settings = bpy.context.scene.npr_settings
    except AttributeError:
        return
    settings.log_entries.clear()


# --------------------------------------------------------------------------------------
# 选择与物体
# --------------------------------------------------------------------------------------

def selected_meshes(context):
    """当前选中的网格物体（含进入编辑模式时的对象）。"""
    objects = [ob for ob in context.selected_objects if ob.type == 'MESH']
    if not objects and context.active_object is not None:
        active = context.active_object
        if active.type == 'MESH':
            objects = [active]
    return objects


def mesh_material_slots(objects, recursive: bool = False, include_linked: bool = True):
    """收集物体上的材质槽。

    返回 [(object, slot_index, material), ...]，保持顺序且去重。
    """
    result = []
    seen = set()
    stack = list(objects)
    visited = set()
    while stack:
        ob = stack.pop(0)
        if ob is None or ob.name in visited:
            continue
        visited.add(ob.name)
        if ob.type == 'MESH':
            for index, slot in enumerate(ob.material_slots):
                material = slot.material
                if material is None:
                    continue
                key = (ob.name, index)
                if key in seen:
                    continue
                seen.add(key)
                result.append((ob, index, material))
        if recursive and include_linked:
            for child in ob.children:
                stack.append(child)
    return result


def unique_materials_from_slots(slots):
    """从槽位列表里取出不重复材质并保持顺序。"""
    result = []
    for _ob, _index, material in slots:
        if material is not None and material not in result:
            result.append(material)
    return result
