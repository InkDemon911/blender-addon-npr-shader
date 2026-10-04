# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Shader — 预设材质组。

需求里的四个预设组（衣服 / 头发 / 身体 / 眼睛）在这里落地；另外补充了
「脸部 / 睫眉 / 口齿」三个参考文件里实际存在的部位分组，以及一个通用兜底组。

每个预设的 ``part`` 直接对应参考文件 ``Shader`` 节点组的 mask 输入
（Face / Body01 / Body / Hair / Eyes），因此预设之间可以共用同一套节点拓扑。
"""

from __future__ import annotations

import bpy

from . import shader_nodes, utils

#: 预设定义：name / part / 说明 / 参数覆盖
PRESETS = (
    {
        "name": "衣服",
        "part": "Body01",
        "description": "服装、裙装、装饰。参考文件里对应 Body01 系列贴图（Tex_Body01_Diffuse/Lightmap/Normalmap）",
        "values": {
            "ramp_band_1": 4.0, "ramp_band_2": 3.0, "ramp_band_3": 5.0, "ramp_band_4": 2.0,
            "ramp_strength": 0.85,
            "spec_gloss": 12.0,
            "shadow_threshold": 0.35,
            "outline_thickness": 0.006,
            # 参考文件里裙摆花纹叠加倍率为 8（Lightmap · 运算）
            "detail_strength": 8.0,
        },
    },
    {
        "name": "头发",
        "part": "Hair",
        "description": "头发、发饰。参考文件里对应 Hair 系列贴图，通常带较窄的阴影 Ramp 与较强的高光",
        "values": {
            "ramp_band_1": 5.0, "ramp_band_2": 4.0, "ramp_band_3": 6.0, "ramp_band_4": 3.0,
            "ramp_strength": 1.0,
            "spec_gloss": 40.0,
            "spec_threshold": 0.6,
            "outline_thickness": 0.005,
        },
    },
    {
        "name": "身体",
        "part": "Body",
        "description": "皮肤、四肢。参考文件里对应 Body 系列贴图，AO 与阴影过渡最柔和",
        "values": {
            "ramp_band_1": 3.0, "ramp_band_2": 2.0, "ramp_band_3": 4.0, "ramp_band_4": 1.0,
            "ramp_strength": 0.65,
            "spec_gloss": 6.0,
            "ao_smooth_lo": 0.15,
            "ao_smooth_hi": 0.28,
            "outline_thickness": 0.005,
        },
    },
    {
        "name": "眼睛",
        "part": "Eyes",
        "description": "眼白、瞳孔、高光。参考文件里配合 Eyes Shader 组（3 张瞳孔贴图 ADD 叠加）",
        "values": {
            "specular_enable": False,
            "rim_enable": True,
            "rim_power": 3.0,
            "ramp_strength": 0.25,
            "base_brightness": 1.0,
            "surface_render_method": 'DITHERED',
            "outline_thickness": 0.003,
        },
    },
    {
        "name": "脸部",
        "part": "Face",
        "description": "面部本体。参考文件里对应 Face 贴图与 SDF 面部阴影（SDF 帧）",
        "values": {
            "sdf_enable": True,
            "ramp_strength": 0.9,
            "ramp_band_1": 4.0, "ramp_band_2": 3.0, "ramp_band_3": 5.0, "ramp_band_4": 2.0,
            "spec_gloss": 6.0,
            "outline_thickness": 0.004,
        },
    },
    {
        "name": "睫眉",
        "part": "Face",
        "description": "睫毛与眉毛。参考文件里的 睫眉 材质，通常需要镂空透明",
        "values": {
            "sdf_enable": False,
            "base_brightness": 1.0,
            "ramp_strength": 0.3,
            "specular_enable": False,
            "alpha_threshold": 0.35,
            "outline_thickness": 0.0,
            "outline_enable": False,
        },
    },
    {
        "name": "口齿",
        "part": "Face",
        "description": "口腔与牙齿。参考文件里的 口舌 / 齿 材质",
        "values": {
            "base_brightness": 1.0,
            "ramp_strength": 0.4,
            "spec_gloss": 20.0,
            "outline_thickness": 0.003,
        },
    },
    {
        "name": "金属",
        "part": "Body",
        "description": "金属与宝石。参考文件里启用金属蒙版高光分支并切换为半透明混合",
        "values": {
            "metal_enable": True,
            "metal_threshold": 0.5,
            "spec_gloss": 60.0,
            "crystal": True,
            "surface_render_method": 'BLENDED',
            "outline_thickness": 0.004,
        },
    },
)

DEFAULT_PRESET = {
    "name": "通用",
    "part": "Body",
    "description": "兜底预设，参数等于参考文件默认值",
    "values": {},
}


def preset_names() -> tuple:
    return tuple(item["name"] for item in PRESETS) + (DEFAULT_PRESET["name"],)


def get_preset(name: str):
    for item in PRESETS:
        if item["name"] == name:
            return item
    if name == DEFAULT_PRESET["name"]:
        return DEFAULT_PRESET
    return None


def apply_preset_values(group, preset) -> None:
    """把预设的值写进组（只覆盖 ``values`` 里出现的参数）。"""
    if preset is None:
        return
    for attr, value in preset.get("values", {}).items():
        try:
            setattr(group, attr, value)
        except (AttributeError, TypeError, ValueError):
            continue


def create_from_preset(settings, preset_name: str, add_group_material: bool = True):
    """按预设新建一个材质组。

    Args:
        settings: ``Scene.npr_settings``
        add_group_material: 是否把组自己的 NPR 材质也加入组内材质列表

    Returns:
        新建的 :class:`~npr_shader.properties.NprMaterialGroup`（已设为当前组）
    """
    preset = get_preset(preset_name) or DEFAULT_PRESET
    group = settings.new_group(preset["name"], preset["part"])
    apply_preset_values(group, preset)
    if add_group_material:
        from . import core  # 局部导入避免循环依赖
        material, _created = core.ensure_group_material(group)
        group.add_material(material)
    return group


def ensure_default_groups(settings, only_if_empty: bool = True) -> list:
    """建立默认预设组（衣服 / 头发 / 身体 / 眼睛 + 脸部 / 睫眉 / 口齿 / 金属）。

    Returns:
        新建的组名列表
    """
    if only_if_empty and len(settings.groups) > 0:
        return []
    created = []
    for preset in PRESETS:
        group = create_from_preset(settings, preset["name"])
        created.append(group.name)
    settings.active_group_index = 0
    return created


# --------------------------------------------------------------------------------------
# 一键设置：渲染环境（参考文件的实际配置）
# --------------------------------------------------------------------------------------

def apply_render_defaults(context, enable_bloom: bool = False) -> list:
    """按参考文件的实际配置调整场景渲染设置。

    参考文件实测值：
        engine = BLENDER_EEVEE
        view_transform = Standard（三渲二必须，否则 AgX/Filmic 会冲淡颜色）
        taa_render_samples = 16
        use_shadows = True, shadow_pool_size = 1024
        Bloom 由合成器 Glare(Bloom) 提供（EEVEE 5.x 已移除内置 Bloom）
    """
    notes = []
    scene = context.scene
    utils.require_engine(scene)
    notes.append("渲染引擎：BLENDER_EEVEE")

    try:
        scene.view_settings.view_transform = 'Standard'
        notes.append("色彩管理：View Transform = Standard")
    except (AttributeError, TypeError):
        notes.append("色彩管理：无法设置 Standard（当前构建不支持）")

    try:
        if scene.eevee.taa_render_samples < 16:
            scene.eevee.taa_render_samples = 16
    except AttributeError:
        pass
    try:
        scene.eevee.use_shadows = True
    except AttributeError:
        pass

    if enable_bloom:
        notes.extend(_ensure_bloom_compositor(scene))
    return notes


def _ensure_bloom_compositor(scene) -> list:
    """按参考文件「合成器节点」的写法配置 RenderLayer → Glare(Bloom) → AlphaOver。

    Blender 5.2 的合成器改为独立 NodeTree 资源，通过
    ``scene.compositing_node_group`` 挂载。
    """
    notes = []
    node_group = getattr(scene, "compositing_node_group", None)
    tree_name = "NPR_Bloom"
    if node_group is not None and node_group.name != tree_name:
        notes.append("场景已挂载其它合成器节点组（%s），未改动" % node_group.name)
        return notes
    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        tree = bpy.data.node_groups.new(tree_name, 'CompositorNodeTree')
    utils.clear_node_tree(tree)

    rl = tree.nodes.new('CompositorNodeRLayers')
    rl.location = (-400.0, 0.0)
    glare = tree.nodes.new('CompositorNodeGlare')
    glare.location = (-120.0, 120.0)
    utils.set_prop(glare, "glare_type", 'BLOOM')
    utils.set_prop(glare, "quality", 'HIGH')
    utils.set_prop(glare, "mix", 0.0)
    utils.set_prop(glare, "threshold", 10.0)
    utils.set_prop(glare, "size", 7)
    alpha_over = tree.nodes.new('CompositorNodeAlphaOver')
    alpha_over.location = (160.0, 0.0)
    try:
        utils.set_prop(alpha_over, "premul", 1.0)
    except (AttributeError, TypeError):
        pass

    utils.link(tree, rl, "Image", alpha_over, "Background")
    utils.link(tree, glare, "Glare", alpha_over, "Foreground")
    utils.link(tree, rl, "Image", glare, "Image")

    try:
        scene.compositing_node_group = tree
        utils.set_prop(scene, "use_nodes", True)
        notes.append("已启用合成器 Bloom（Glare 节点，参考文件的写法）")
    except (AttributeError, TypeError) as exc:
        notes.append("无法挂载合成器节点组：%s" % exc)
    return notes


def disable_bloom_compositor(scene) -> list:
    notes = []
    node_group = getattr(scene, "compositing_node_group", None)
    if node_group is not None and node_group.name == "NPR_Bloom":
        try:
            scene.compositing_node_group = None
            notes.append("已关闭合成器 Bloom")
        except (AttributeError, TypeError) as exc:
            notes.append("无法关闭合成器：%s" % exc)
    return notes


def build_preset_materials(settings) -> list:
    """为所有预设组生成材质（供"重建预设"按钮使用）。"""
    created = []
    from . import core
    for group in settings.groups:
        material, is_new = core.ensure_group_material(group, force_rebuild=True)
        if not group.has_material(material):
            group.add_material(material)
        created.append(material.name)
    return created
