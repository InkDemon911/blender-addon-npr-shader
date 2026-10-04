# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Studio — 数据模型（PropertyGroup）。

数据分层：
  Scene.npr_settings  →  NprSettings
                          ├─ groups : CollectionProperty(NprMaterialGroup)   材质组
                          └─ log_entries : CollectionProperty(NprLogEntry)    日志

每个参数都标注了它在参考文件 OdetteV3.blend 中对应的节点与取值，
默认值 = 参考文件实测值，因此"应用整个组"后不调任何滑杆，渲染结果与参考文件一致。
"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from . import utils

# --------------------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------------------

APPLY_MODE_ITEMS = (
    ('REPLACE', "替换现有材质",
     "把每个材质槽的材质替换为 NPR 材质（原材质保留在 .blend 里但不被引用）"),
    ('APPEND', "追加新材质",
     "在每个物体末尾追加一个 NPR 材质槽，并设为活动槽，原有材质全部保留"),
    ('OUTLINE_ONLY', "仅添加描边",
     "不改动任何材质，只为选中物体添加/更新描边对象"),
    ('REPLACE_KEEP_TEX', "替换材质并保留原贴图连接",
     "替换材质，同时自动扫描原材质里的贴图并按用途填入新 NPR 材质的贴图槽"),
)

SLOT_MODE_ITEMS = (
    ('REPLACE_FIRST', "替换第一个槽位", "只处理每个物体的第一个材质槽"),
    ('ALL_SLOTS', "替换全部槽位", "每个材质槽各生成一个 NPR 材质"),
    ('APPEND', "在末尾追加", "保留原有槽位，在末尾追加 NPR 材质"),
)

OUTLINE_MODE_ITEMS = (
    ('OBJECT', "独立描边对象（推荐）", "复制网格生成独立描边对象，可逐组控制粗细与颜色，随时整体删除"),
    ('MODIFIER', "源物体修改器", "直接在源物体上加 Solidify 修改器，不新增对象，但无法逐槽位控制"),
)


def _part_items(self=None, context=None):
    """部位枚举项（顺序与 utils.PART_ITEMS 一致）。"""
    return list(utils.PART_ITEMS)


# 说明：Blender 规定 EnumProperty 的 items 为函数/lambda 时，default 只能用整数索引。
# 这里直接给出索引常量，并与 utils.PART_NAMES 的顺序严格绑定（Body 是第 3 项 → 2）。
PART_INDEX = {name: index for index, name in enumerate(utils.PART_NAMES)}
PART_DEFAULT_INDEX = PART_INDEX["Body"]


# --------------------------------------------------------------------------------------
# 材质引用
# --------------------------------------------------------------------------------------

class NprMaterialRef(PropertyGroup):
    """组内的一条材质引用。"""

    material: PointerProperty(
        name="材质",
        description="组内材质。材质被删除时此项自动失效",
        type=bpy.types.Material,
        options={'SKIP_SAVE'} if False else set(),
    )

    name: StringProperty(
        name="名称",
        description="组内显示名（可留空，自动取材质名）",
        default="",
    )

    def display_name(self) -> str:
        if self.name:
            return self.name
        return self.material.name if self.material else "<已删除>"


# --------------------------------------------------------------------------------------
# 材质挑选器（"把选中物体的材质加入组"用）
# --------------------------------------------------------------------------------------

class NprPickerItem(PropertyGroup):
    """材质挑选器里的一条候选材质。

    存在的意义：Blender 5.2 的 ``bpy.types.Material`` **没有** ``select`` 属性
    （旧版本有，5.x 已移除），所以无法询问"材质编辑器里当前选中了哪些材质"。
    这里自己维护一份候选列表 + 勾选状态，把选择权明确交给用户。
    """

    material: PointerProperty(
        name="材质",
        description="候选材质",
        type=bpy.types.Material,
    )

    selected: BoolProperty(
        name="选择",
        description="勾选后会被「加入当前组」",
        default=True,
    )

    source: StringProperty(
        name="来源",
        description="记录这个材质是从哪个物体/槽位收集来的，便于用户辨认",
        default="",
    )

    def display_name(self) -> str:
        return self.material.name if self.material else "<已删除>"


# --------------------------------------------------------------------------------------
# 材质组
# --------------------------------------------------------------------------------------

class NprMaterialGroup(PropertyGroup):
    """一个 NPR 材质组：一组材质 + 一套共享的着色/描边参数。"""

    # ---- 基本 ----
    name: StringProperty(
        name="组名",
        description="材质组名称，同时用于生成 NPR 材质名（NPR_<组名>_<部位>）",
        default="新建组",
    )
    part: EnumProperty(
        name="部位",
        description="对应参考文件 Shader 组的部位 mask 输入（Face / Body01 / Body / Hair / Eyes）",
        items=_part_items,
        default=PART_DEFAULT_INDEX,
    )
    enabled: BoolProperty(
        name="启用",
        description="关闭后「应用整个组」会跳过该组，但不会删除已有材质",
        default=True,
    )

    # ---- 组内材质 ----
    materials: CollectionProperty(type=NprMaterialRef)
    materials_index: IntProperty(name="当前材质", default=0)

    # ------------------------------------------------------------------
    # 贴图输入（参考文件里内嵌在节点组内部，此处提升为组接口）
    # ------------------------------------------------------------------
    tex_base_color: PointerProperty(
        name="基础色贴图",
        description="对应参考文件 Base Color 组的部位 Diffuse 贴图（色彩空间 sRGB）",
        type=bpy.types.Image,
    )
    tex_lightmap: PointerProperty(
        name="阴影 / 光照贴图",
        description="对应参考文件 Lightmap 组。R=高光分支阈值, G=AO/阴影, B=金属切换, A=Ramp 条数遮罩。色彩空间 Non-Color",
        type=bpy.types.Image,
    )
    tex_normal: PointerProperty(
        name="法线贴图",
        description="对应参考文件 Normalmap 组。B 通道会作为 DiffuseBias 叠加到 NoL 上。色彩空间 Non-Color",
        type=bpy.types.Image,
    )
    tex_ramp: PointerProperty(
        name="阴影 Ramp 贴图",
        description="对应参考文件 Ramp 组，推荐 256×20 的 Shadow_Ramp。采样方式 Closest + EXTEND，色彩空间 sRGB",
        type=bpy.types.Image,
    )
    tex_metal: PointerProperty(
        name="金属 / 高光蒙版",
        description="对应参考文件 Shader 组的 MetalMap 贴图（图像纹理.001）。色彩空间 Non-Color",
        type=bpy.types.Image,
    )
    tex_sdf: PointerProperty(
        name="面部 SDF 贴图",
        description="对应参考文件 SDF 帧使用的面部光照贴图（Alpha 通道为 SDF 遮罩）。色彩空间 sRGB",
        type=bpy.types.Image,
    )
    tex_emission: PointerProperty(
        name="自发光贴图",
        description="自发光叠加（参考文件中通过额外 Emission + ShaderToRGB + ADD 实现）",
        type=bpy.types.Image,
    )
    tex_alpha: PointerProperty(
        name="Alpha 贴图",
        description="透明度贴图；同时会把材质的混合模式设为 BLENDED / DITHERED",
        type=bpy.types.Image,
    )
    tex_specular: PointerProperty(
        name="高光贴图",
        description="高光蒙版贴图（与 tex_metal 二选一，优先级低于金属蒙版）",
        type=bpy.types.Image,
    )
    tex_matcap: PointerProperty(
        name="MatCap 贴图",
        description="MatCap 叠加，采样方式为相机空间法线映射",
        type=bpy.types.Image,
    )
    tex_pupil_a: PointerProperty(name="瞳孔贴图 A", description="对应参考文件 Eyes Shader 组第一张", type=bpy.types.Image)
    tex_pupil_b: PointerProperty(name="瞳孔贴图 B", description="对应参考文件 Eyes Shader 组第二张", type=bpy.types.Image)
    tex_pupil_c: PointerProperty(name="瞳孔贴图 C", description="对应参考文件 Eyes Shader 组第三张", type=bpy.types.Image)
    tex_detail_1: PointerProperty(name="花纹叠加 1", description="对应参考文件 NodeGroup 组第一张（如裙_菱形s.png）", type=bpy.types.Image)
    tex_detail_2: PointerProperty(name="花纹叠加 2", description="对应参考文件 NodeGroup 组第二张（如裙_菱形sp.png）", type=bpy.types.Image)
    tex_detail_3: PointerProperty(name="花纹叠加 3", description="对应参考文件 NodeGroup 组第三张（如裙_多边形s.png）", type=bpy.types.Image)
    tex_detail_4: PointerProperty(name="花纹叠加 4", description="对应参考文件 NodeGroup 组第四张（如裙_三角形s.png）", type=bpy.types.Image)

    # ------------------------------------------------------------------
    # 基础色 / 光照
    # ------------------------------------------------------------------
    base_color: FloatVectorProperty(
        name="基础色 / 色调",
        description="乘到基础色贴图上的色调：白色 = 不改动贴图，其它颜色 = 整体染色。"
                    "没有基础色贴图时，这里就是最终基础色",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0),
    )
    base_brightness: FloatProperty(
        name="基础色亮度",
        description="参考文件映射：Base Color 组 · 自发光.Strength",
        min=0.0, max=4.0, default=1.0,
    )
    base_color_gain: FloatProperty(
        name="基础色增益",
        description="对基础色再乘一个系数（1.0 = 不改变）。"
                    "需要把「增益强度」调到 1 才会生效，默认 0 表示不做增益",
        min=0.0, max=4.0, default=1.0,
    )
    base_color_gain_strength: FloatProperty(
        name="增益强度",
        description="0 = 不做增益（乘 1）；1 = 完整乘上「基础色增益」",
        min=0.0, max=1.0, default=0.0,
    )
    light_euler: FloatVectorProperty(
        name="主光方向（欧拉）",
        description="参考文件映射：Light Vecter 组 · 合并 XYZ 的旋转。默认值与参考文件完全一致",
        size=3, subtype='EULER', default=(-0.34177, 0.67079, -140.36),
    )
    light_intensity: FloatProperty(
        name="光照强度",
        description="缩放 Light Vecter 输出向量，用于整体加深/减弱阴影对比",
        min=0.0, max=4.0, default=1.0,
    )

    # ------------------------------------------------------------------
    # 阴影 / AO（参考文件 AO 帧）
    # ------------------------------------------------------------------
    ao_bias: FloatProperty(
        name="AO 偏置",
        description="参考文件映射：Shader · 运算.004（+0.1）与 运算.005（−0.1）",
        min=0.0, max=1.0, default=0.1,
    )
    ao_smooth_lo: FloatProperty(
        name="AO 软边下限",
        description="参考文件映射：LightmapSmoothStep · Smoothstep.t1",
        min=0.0, max=1.0, default=0.2,
    )
    ao_smooth_hi: FloatProperty(
        name="AO 软边上限",
        description="参考文件映射：LightmapSmoothStep · Smoothstep.t2",
        min=0.0, max=1.0, default=0.3,
    )
    ao_add: FloatProperty(
        name="AO 提亮",
        description="参考文件映射：Shader AO 帧中在归一化结果上叠加的 +0.1",
        min=0.0, max=1.0, default=0.1,
    )
    shadow_threshold: FloatProperty(
        name="阴影阈值",
        description="只影响阴影 Ramp 的取样位置上限（映射范围.002 · To Max）",
        min=0.0, max=1.0, default=0.35,
    )

    # ------------------------------------------------------------------
    # 高光（参考文件 Specular 帧）
    # ------------------------------------------------------------------
    specular_enable: BoolProperty(
        name="启用高光",
        description="关闭后高光分支（金属蒙版 / 阈值高光）整体关闭",
        default=True,
    )
    spec_gloss: FloatProperty(
        name="高光指数 Gloss",
        description="参考文件映射：Shader · 群组.014 · Blinn-Phong 的 Gloss",
        min=0.0, max=256.0, default=5.0,
    )
    spec_darken: FloatProperty(
        name="高光压暗常数",
        description="参考文件映射：Shader · 运算.006 的被减数（1.04 − s）",
        min=0.0, max=4.0, default=1.04,
    )
    spec_threshold: FloatProperty(
        name="高光阈值",
        description="参考文件映射：Shader · 运算.016（高光贴图红通道 > 0.7 时走压暗分支）",
        min=0.0, max=1.0, default=0.7,
    )
    metal_threshold: FloatProperty(
        name="金属蒙版阈值",
        description="参考文件映射：Shader · 运算.011（光照贴图红通道 > 0.55 时切换到金属蒙版高光）",
        min=0.0, max=1.0, default=0.55,
    )
    metal_enable: BoolProperty(
        name="启用金属蒙版高光",
        description="关闭后高光只走阈值分支",
        default=True,
    )
    spec_crystal_threshold: FloatProperty(
        name="Crystal 高光阈值",
        description="参考文件映射：Shader · 运算.020",
        min=0.0, max=1.0, default=0.2,
    )
    crystal: BoolProperty(
        name="Crystal 分支",
        description="参考文件映射：Shader 组的 Crystal 输入（0/1），控制 Blinn-Phong 参与与高光混合因子",
        default=False,
    )

    # ------------------------------------------------------------------
    # 边缘光（参考文件 Rim 帧）
    # ------------------------------------------------------------------
    rim_enable: BoolProperty(
        name="启用边缘光",
        description="关闭后跳过 Rim 帧（等价于参考文件该分支输出黑色）",
        default=True,
    )
    rim_color: FloatVectorProperty(
        name="边缘光颜色",
        description="参考文件映射：Rim 帧 · Base Color.001 结果（此处提供纯色替代）",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0),
    )
    rim_intensity: FloatProperty(
        name="边缘光强度",
        description="边缘光颜色增益",
        min=0.0, max=8.0, default=1.0,
    )
    rim_power: FloatProperty(
        name="边缘光指数",
        description="参考文件映射：Shader · 运算.019",
        min=0.0, max=32.0, default=4.8,
    )
    rim_looseness: FloatProperty(
        name="边缘光软边",
        description="参考文件映射：Shader · 运算.015 的 Value_002",
        min=0.0, max=1.0, default=0.2,
    )
    rim_lo: FloatProperty(
        name="边缘光阈值下限",
        description="参考文件映射：Shader · SmoothStep.t1",
        min=0.0, max=2.0, default=0.423,
    )
    rim_hi: FloatProperty(
        name="边缘光阈值上限",
        description="参考文件映射：Shader · SmoothStep.t2",
        min=0.0, max=2.0, default=0.45,
    )

    # ------------------------------------------------------------------
    # 面部 SDF（参考文件 SDF 帧）
    # ------------------------------------------------------------------
    sdf_enable: BoolProperty(
        name="启用面部 SDF",
        description="关闭后不参与面部阴影 Ramp 的 X 取样（等价于恒定取样）",
        default=False,
    )
    head_o: FloatVectorProperty(
        name="头部原点 O",
        description="参考文件映射：Head Vector · 合并 XYZ.002",
        size=3, default=(0.0, -0.011286, 1.51312),
    )
    head_front: FloatVectorProperty(
        name="头部前方点",
        description="参考文件映射：Head Vector · Front",
        size=3, default=(0.0, -1.01129, 1.51312),
    )
    head_right: FloatVectorProperty(
        name="头部右方点",
        description="参考文件映射：Head Vector · Right",
        size=3, default=(-1.0, -0.011286, 1.51312),
    )

    # ------------------------------------------------------------------
    # 阴影 Ramp（参考文件 Ramp 帧）
    # ------------------------------------------------------------------
    ramp_enable: BoolProperty(
        name="启用阴影 Ramp",
        description="关闭后阴影 Ramp 不再与基础色相乘（等价于 rampStrength = 1）",
        default=False,
    )
    ramp_strength: FloatProperty(
        name="Ramp 强度",
        description="参考文件 Ramp 结果与基础色的乘算系数。"
                    "没有 Shadow_Ramp 贴图时 Ramp 结果是白色、乘上去会整体提亮，"
                    "因此默认「启用阴影 Ramp」关闭（不参与乘算）",
        min=0.0, max=1.0, default=0.65,
    )
    ramp_band_0: FloatProperty(
        name="Ramp 条数 A0",
        description="参考文件映射：Ramp Select · A0（作为 Ramp 坐标 Y 的下限基准）",
        min=-4.0, max=16.0, default=0.0,
    )
    ramp_band_1: FloatProperty(name="Ramp 条数 A1", description="参考文件映射：Ramp Select · A1", min=-4.0, max=16.0, default=4.0)
    ramp_band_2: FloatProperty(name="Ramp 条数 A2", description="参考文件映射：Ramp Select · A2", min=-4.0, max=16.0, default=3.0)
    ramp_band_3: FloatProperty(name="Ramp 条数 A3", description="参考文件映射：Ramp Select · A3", min=-4.0, max=16.0, default=5.0)
    ramp_band_4: FloatProperty(name="Ramp 条数 A4", description="参考文件映射：Ramp Select · A4", min=-4.0, max=16.0, default=2.0)
    ramp_band_scale: FloatProperty(
        name="Ramp 坐标倍率",
        description="参考文件映射：Ramp条数 组里的 0.1 步进系数（越大条带越密）",
        min=0.0, max=1.0, default=0.1,
    )
    ramp_band_base: FloatProperty(
        name="Ramp 坐标基址",
        description="参考文件映射：Ramp条数 组里的 1.05 基址常数",
        min=0.0, max=4.0, default=1.05,
    )

    # ------------------------------------------------------------------
    # 材质 / 渲染
    # ------------------------------------------------------------------
    surface_render_method: EnumProperty(
        name="混合模式",
        description="参考文件实测：不透明用 DITHERED，半透明（眼透/金属）用 BLENDED",
        items=(('DITHERED', "DITHERED（镂空 / 不透明）", "参考文件默认值，性能最好"),
               ('BLENDED', "BLENDED（半透明混合）", "真正透明的排序混合，用于眼睛、玻璃")),
        default='DITHERED',
    )
    halo_brightness: FloatProperty(
        name="高光整体增益",
        description="对最终发光结果再乘一个系数，用于统一提亮/压暗整套材质",
        min=0.0, max=8.0, default=1.0,
    )
    detail_strength: FloatProperty(
        name="花纹叠加倍率",
        description="参考文件映射：Lightmap · 运算（×8），作用于裙摆花纹等叠加贴图。"
                    "默认 0（无花纹贴图时不参与运算，避免把颜色加爆成纯白）",
        min=0.0, max=32.0, default=0.0,
    )
    emission_color: FloatVectorProperty(
        name="自发光颜色",
        description="自发光贴图的颜色增益",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0),
    )
    emission_strength: FloatProperty(
        name="自发光强度",
        description="自发光叠加强度（参考文件通过额外 Emission + ADD 实现）",
        min=0.0, max=16.0, default=1.0,
    )
    alpha_threshold: FloatProperty(
        name="Alpha 阈值",
        description="DITHERED 模式下的镂空阈值（材质 alpha_threshold）",
        min=0.0, max=1.0, default=0.5,
    )

    # ------------------------------------------------------------------
    # 描边（参考文件无描边，按"倒角外壳"路线实现）
    # ------------------------------------------------------------------
    outline_enable: BoolProperty(
        name="启用描边",
        description="「一键添加/更新描边」是否处理该组",
        default=True,
    )
    outline_color: FloatVectorProperty(
        name="描边颜色",
        description="描边颜色（若开启「描边用物体颜色」则被物体颜色覆盖）",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.05, 0.05, 0.06, 1.0),
    )
    outline_thickness: FloatProperty(
        name="描边粗细",
        description="Solidify 修改器的 thickness",
        min=0.0, max=0.5, default=0.008,
    )
    outline_offset: FloatProperty(
        name="描边偏移",
        description="参考用法为 1.0（完全向外扩张）；调小会向内侵蚀模型",
        min=-1.0, max=1.0, default=1.0,
    )
    outline_threshold: FloatProperty(
        name="描边阈值",
        description="按视角控制描边显隐的阈值（对 Fresnel 面具做 smoothstep）",
        min=0.0, max=1.0, default=0.0,
    )
    outline_alpha: FloatProperty(
        name="描边不透明度",
        description="描边材质的不透明度（小于 1 会把混合模式设为 BLENDED）",
        min=0.0, max=1.0, default=1.0,
    )
    outline_emission: FloatProperty(
        name="描边自发光强度",
        description="描边 Emission 的 Strength",
        min=0.0, max=16.0, default=1.0,
    )
    outline_use_texture: BoolProperty(
        name="描边使用贴图",
        description="用描边贴图调制描边颜色",
        default=False,
    )
    outline_tex: PointerProperty(
        name="描边贴图",
        description="描边颜色贴图（按主 UV 采样）",
        type=bpy.types.Image,
    )
    outline_even: BoolProperty(
        name="均匀粗细",
        description="Solidify 的 use_even_offset，避免尖角处描边变细",
        default=True,
    )
    outline_mode: EnumProperty(
        name="描边方式",
        description="描边的对象组织方式",
        items=OUTLINE_MODE_ITEMS,
        default='OBJECT',
    )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def material_list(self):
        """返回有效的材质对象列表（过滤掉已删除的引用）。"""
        return [ref.material for ref in self.materials if ref.material is not None]

    def has_material(self, material) -> bool:
        return any(ref.material == material for ref in self.materials)

    def add_material(self, material):
        """把材质加入组；已在组内则不重复添加。返回是否新增。"""
        if material is None or self.has_material(material):
            return False
        ref = self.materials.add()
        ref.material = material
        return True

    def remove_material_at(self, index: int) -> bool:
        if 0 <= index < len(self.materials):
            self.materials.remove(index)
            return True
        return False

    def part_index(self) -> int:
        try:
            return utils.PART_NAMES.index(self.part)
        except ValueError:
            return 2


# --------------------------------------------------------------------------------------
# 日志
# --------------------------------------------------------------------------------------

class NprLogEntry(PropertyGroup):
    message: StringProperty(name="消息", default="")
    level: EnumProperty(
        name="级别",
        items=(('INFO', "信息", ""), ('WARN', "警告", ""), ('ERROR', "错误", "")),
        default='INFO',
    )


# --------------------------------------------------------------------------------------
# 场景设置
# --------------------------------------------------------------------------------------

class NprSettings(PropertyGroup):
    groups: CollectionProperty(
        name="材质组",
        type=NprMaterialGroup,
        description="模块化材质组列表（衣服 / 头发 / 身体 / 眼睛 …）",
    )
    active_group_index: IntProperty(
        name="当前组",
        description="当前选中的材质组",
        default=0,
        min=0,
    )

    apply_mode: EnumProperty(
        name="应用模式",
        description="「一键应用三渲二」的行为",
        items=APPLY_MODE_ITEMS,
        default='REPLACE_KEEP_TEX',
    )
    slot_mode: EnumProperty(
        name="槽位策略",
        description="材质槽的处理范围",
        items=SLOT_MODE_ITEMS,
        default='ALL_SLOTS',
    )

    auto_texture_detect: BoolProperty(
        name="自动识别贴图",
        description="扫描原材质里已有的图像纹理，按用途（Diffuse/Lightmap/Normalmap/Ramp/Metal/SDF）自动填入新组的贴图槽",
        default=True,
    )
    auto_create_group: BoolProperty(
        name="自动建组",
        description="当没有可用组时，自动按物体名创建一个材质组",
        default=True,
    )
    recursive: BoolProperty(
        name="包含子物体",
        description="批量处理时把选中物体的子物体一起处理",
        default=False,
    )
    sync_viewport: BoolProperty(
        name="同步视口色彩管理",
        description="把场景 View Transform 设为 Standard（参考文件的设置，避免 Filmic/AgX 冲淡三渲二颜色）",
        default=False,
    )
    enable_compositor_bloom: BoolProperty(
        name="启用 Bloom（合成器）",
        description="按参考文件「合成器节点」的写法创建 RenderLayer → Glare(Bloom) → AlphaOver 合成器节点组。EEVEE 5.x 已移除内置 Bloom",
        default=False,
    )
    outline_use_object_color: BoolProperty(
        name="描边使用物体颜色",
        description="描边颜色优先取物体的 color（object.color），便于逐物体快速区分",
        default=False,
    )
    outline_use_backface_culling: BoolProperty(
        name="描边背面剔除",
        description="必须开启（倒角外壳只显示背面），关闭会导致描边覆盖整个模型",
        default=True,
    )
    delete_source_outlines: BoolProperty(
        name="清理旧描边",
        description="重建描边前先删除同一源对象已有的 NPR 描边对象",
        default=True,
    )
    keep_original_materials: BoolProperty(
        name="保留原材质数据块",
        description="替换材质时给原材质加上 use_fake_user，避免被 Blender 自动清理，便于随时还原",
        default=True,
    )

    # ---- 材质挑选器 ----
    #: 候选材质列表：由「从选中物体收集材质」填充，用户逐条勾选后再加入组。
    #: 之所以用**独立集合**而不是复用材质自身的 select 标记：Blender 5.2 的
    #: bpy.types.Material 已经没有 .select 属性了（旧版本有），无法询问
    #: "材质编辑器里选中了哪些"。自带勾选状态还能跨物体合并去重。
    picker_items: CollectionProperty(name="候选材质", type=NprPickerItem)
    picker_index: IntProperty(name="当前候选", default=0)

    log_entries: CollectionProperty(name="日志", type=NprLogEntry)
    log_entries_index: IntProperty(name="当前日志", default=0)
    show_advanced: BoolProperty(name="展开高级面板", default=False)

    # ---- 材质挑选器辅助 ----
    def picker_clear(self) -> None:
        self.picker_items.clear()
        self.picker_index = 0

    def picker_fill(self, slots, keep_selection: bool = False) -> int:
        """用 ``[(object, slot_index, material), ...]`` 填充候选列表（按材质去重）。

        Args:
            slots: :func:`utils.mesh_material_slots` 的返回值。
            keep_selection: True 时保留同名材质原有的勾选状态（刷新时用）。

        Returns:
            实际加入候选的数量。
        """
        previous = {}
        if keep_selection:
            for item in self.picker_items:
                if item.material is not None:
                    previous[item.material.name] = item.selected
        self.picker_clear()
        seen = set()
        for obj, index, material in slots:
            if material is None or material.name in seen:
                continue
            seen.add(material.name)
            item = self.picker_items.add()
            item.material = material
            item.selected = previous.get(material.name, True)
            item.source = "%s[%d]" % (obj.name, index)
        return len(self.picker_items)

    def picker_select_all(self, value: bool = True) -> int:
        count = 0
        for item in self.picker_items:
            item.selected = value
            count += 1
        return count

    def picker_selected_materials(self):
        """返回被勾选且仍然有效的材质（按候选顺序去重）。"""
        result = []
        for item in self.picker_items:
            material = item.material
            if item.selected and material is not None and material not in result:
                result.append(material)
        return result

    def picker_contains(self, material) -> bool:
        return any(item.material == material for item in self.picker_items)

    def active_group(self):
        """返回当前选中的组，越界时返回 None。"""
        if 0 <= self.active_group_index < len(self.groups):
            return self.groups[self.active_group_index]
        return None

    def group_by_name(self, name: str):
        for group in self.groups:
            if group.name == name:
                return group
        return None

    def group_by_material(self, material):
        """通过材质上的 npr_group 元数据反查所属组。"""
        name = utils.material_group_name(material)
        if name:
            group = self.group_by_name(name)
            if group is not None:
                return group
        for group in self.groups:
            if group.has_material(material):
                return group
        return None

    def unique_group_name(self, base: str) -> str:
        existing = {group.name for group in self.groups}
        return utils.unique_name(base, existing)

    def new_group(self, name: str = "新建组", part: str = 'Body'):
        """新建一个组并返回它（名称自动唯一化）。"""
        group = self.groups.add()
        group.name = self.unique_group_name(name)
        group.part = part
        self.active_group_index = len(self.groups) - 1
        return group

    def move_group(self, index: int, delta: int) -> bool:
        """上下移动组。CollectionProperty 提供了 move()。"""
        target = index + delta
        if not (0 <= index < len(self.groups)) or not (0 <= target < len(self.groups)):
            return False
        self.groups.move(index, target)
        self.active_group_index = target
        return True


# --------------------------------------------------------------------------------------
# 注册
# --------------------------------------------------------------------------------------

classes = (
    NprMaterialRef,
    NprPickerItem,
    NprLogEntry,
    NprMaterialGroup,
    NprSettings,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.npr_settings = PointerProperty(
        name="NPR 设置",
        description="NPR Studio 的材质组与参数（随 .blend 保存）",
        type=NprSettings,
    )


def unregister():
    try:
        del bpy.types.Scene.npr_settings
    except AttributeError:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
