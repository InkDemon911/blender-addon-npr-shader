# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Studio — 3D 视图侧边栏（N 面板）UI。

面板结构（与 docs/PANEL_FLOW.md 一一对应）：

    三渲二 NPR                     ← NprRootPanel
      ├─ 一键应用                   ← NprApplyPanel
      ├─ 材质组管理                 ← NprGroupsPanel（含 NPR_UL_groups）
      ├─ 材质分配                   ← NprAssignPanel
      ├─ 组设置                     ← NprSettingsPanel
      │    ├─ 贴图输入
      │    ├─ 基础色与光照
      │    ├─ 阴影与 AO
      │    ├─ 高光
      │    ├─ 边缘光
      │    ├─ 面部 SDF
      │    ├─ 阴影 Ramp
      │    ├─ 描边
      │    └─ 材质与渲染
      └─ 高级 / 调试                ← NprAdvancedPanel
"""

from __future__ import annotations

import bpy
from bpy.types import Panel, UIList

from . import shader_nodes, utils

CATEGORY = "三渲二"


# --------------------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------------------

def _settings(context):
    return getattr(context.scene, "npr_settings", None)


def _active_group(context):
    settings = _settings(context)
    if settings is None:
        return None
    return settings.active_group()


def _slot_count(context) -> int:
    total = 0
    for obj in utils.selected_meshes(context):
        total += len(obj.material_slots)
    return total


def _draw_texture_row(layout, group, attr: str, label: str) -> None:
    """一行贴图槽：图标 + 名称 + 图像选择器 + 清空按钮。"""
    row = layout.row(align=True)
    image = getattr(group, attr, None)
    row.label(text=label, icon='IMAGE_DATA' if image else 'IMAGE_REFERENCE')
    row.prop(group, attr, text="")
    if image is not None:
        op = row.operator("npr.texture_clear", text="", icon='X')
        op.slot = attr


def _draw_group_header(layout, group) -> None:
    if group is None:
        layout.label(text="没有可用的材质组", icon='INFO')
        return
    box = layout.box()
    row = box.row()
    row.label(text=group.name, icon='MATERIAL')
    row.label(text="部位：%s" % group.part)
    box.label(text="组内材质：%d 个" % len(group.materials), icon='MATERIAL_DATA')


# --------------------------------------------------------------------------------------
# UIList：材质组
# --------------------------------------------------------------------------------------

class NPR_UL_groups(UIList):
    """材质组列表。"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        settings = _settings(context)
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="")
            row.label(text=item.name, icon='GROUP')
            row.label(text=item.part)
            row.label(text="%d" % len(item.materials), icon='MATERIAL_DATA')
            if settings is not None and index == settings.active_group_index:
                row.label(text="", icon='CHECKMARK')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.name, icon='GROUP')


class NPR_UL_group_materials(UIList):
    """组内材质列表。"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        material = item.material
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            if material is None:
                row.label(text="<已删除>", icon='ERROR')
                row.label(text=item.name or "")
                return
            # 显示**材质名**；``item.name`` 是可选的备注名，绝大多数时候为空，
            # 曾经因为直接显示它而导致列表里全是空白行（用户看不到材质名）。
            row.label(text=material.name, icon='MATERIAL')
            if item.name:
                row.label(text="(%s)" % item.name)
            if material.users == 0:
                row.label(text="0 用户", icon='INFO')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=material.name if material else "?", icon='MATERIAL')


class NPR_UL_picker(UIList):
    """候选材质列表（带勾选框，供"材质分配"面板使用）。"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        material = item.material
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "selected", text="")
            if material is None:
                row.label(text="<已删除>", icon='ERROR')
                return
            row.label(text=material.name, icon='MATERIAL')
            if item.source:
                row.label(text=item.source)
            # 已在当前组里时给个提示，避免用户重复添加
            settings = _settings(context)
            group = settings.active_group() if settings is not None else None
            if group is not None and group.has_material(material):
                row.label(text="已在组内", icon='CHECKMARK')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=material.name if material else "?", icon='MATERIAL')


class NPR_UL_log(UIList):
    """日志列表。"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        icons = {'INFO': 'INFO', 'WARN': 'ERROR', 'ERROR': 'CANCEL'}
        row = layout.row(align=True)
        row.label(text=item.message, icon=icons.get(item.level, 'INFO'))


# --------------------------------------------------------------------------------------
# 主面板
# --------------------------------------------------------------------------------------

class NprRootPanel(Panel):
    """三渲二 NPR 插件主入口。"""

    bl_idname = "NPR_PT_root"
    bl_label = "三渲二 NPR"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = _settings(context)
        if settings is None:
            layout.label(text="插件未初始化，请重新启用", icon='ERROR')
            return

        col = layout.column(align=True)
        col.label(text="NPR Studio v%s" % utils.VERSION_STR, icon='SHADERFX')
        engine = context.scene.render.engine
        if engine == 'BLENDER_EEVEE':
            col.label(text="渲染引擎：EEVEE", icon='CHECKMARK')
        else:
            col.label(text="渲染引擎：%s（建议 EEVEE）" % engine, icon='ERROR')

        if not shader_nodes.group_exists(shader_nodes.G_MASTER):
            box = layout.box()
            box.label(text="Shader 节点组尚未构建", icon='ERROR')
            box.operator("npr.rebuild_node_groups", icon='FILE_REFRESH')
        else:
            rows = shader_nodes.group_summary()
            total_nodes = sum(row[1] for row in rows)
            layout.label(text="节点组：%d 个 / %d 节点" % (len(rows), total_nodes), icon='NODETREE')


class NprApplyPanel(Panel):
    """选中模型 → 一键应用三渲二 / 一键描边。"""

    bl_idname = "NPR_PT_apply"
    bl_label = "一键应用"
    bl_parent_id = "NPR_PT_root"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY

    def draw(self, context):
        layout = self.layout
        settings = _settings(context)
        if settings is None:
            return

        meshes = utils.selected_meshes(context)
        box = layout.box()
        if meshes:
            box.label(text="已选中 %d 个网格物体" % len(meshes), icon='OBJECT_DATA')
            box.label(text="材质槽共 %d 个" % _slot_count(context), icon='MATERIAL')
        else:
            box.label(text="未选中网格物体", icon='ERROR')

        group = _active_group(context)
        if group is not None:
            box.label(text="当前组：%s（%s）" % (group.name, group.part), icon='GROUP')
        else:
            box.label(text="未选择材质组", icon='ERROR')

        col = layout.column(align=True)
        col.prop(settings, "apply_mode", text="")
        row = col.row(align=True)
        row.prop(settings, "slot_mode", text="")
        col.prop(settings, "auto_texture_detect")

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("npr.apply", icon='SHADERFX')
        row = layout.row(align=True)
        row.operator("npr.outline_apply", icon='MOD_SOLIDIFY')
        row.operator("npr.outline_remove", icon='TRASH')

        row = layout.row(align=True)
        row.operator("npr.apply_group", icon='CHECKMARK')
        row.operator("npr.outline_selftest", text="描边自检", icon='INFO')

        col = layout.column(align=True)
        col.prop(settings, "auto_create_group")
        col.prop(settings, "keep_original_materials")


class NprGroupsPanel(Panel):
    """材质组的增删改查与排序。"""

    bl_idname = "NPR_PT_groups"
    bl_label = "材质组管理"
    bl_parent_id = "NPR_PT_root"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY

    def draw(self, context):
        layout = self.layout
        settings = _settings(context)
        if settings is None:
            return

        if not settings.groups:
            layout.label(text="尚无材质组", icon='INFO')
            layout.operator("npr.presets_create", text="创建预设组（衣服/头发/身体/眼睛）", icon='ADD')
            return

        row = layout.row()
        row.template_list("NPR_UL_groups", "", settings, "groups",
                          settings, "active_group_index", rows=5)

        col = row.column(align=True)
        col.operator("npr.group_new", text="", icon='ADD')
        col.operator("npr.group_duplicate", text="", icon='DUPLICATE')
        col.operator("npr.group_rename", text="", icon='SORTALPHA')
        col.operator("npr.group_delete", text="", icon='REMOVE')
        col.separator()
        op = col.operator("npr.group_move", text="", icon='TRIA_UP')
        op.delta = -1
        op = col.operator("npr.group_move", text="", icon='TRIA_DOWN')
        op.delta = 1

        group = settings.active_group()
        if group is not None:
            box = layout.box()
            box.prop(group, "name", text="组名")
            box.prop(group, "part", text="部位")
            box.prop(group, "enabled", text="启用（应用整组时生效）")
            box.label(text="材质名：%s" % utils.npr_material_name(group.name, group.part),
                      icon='MATERIAL')

        row = layout.row(align=True)
        row.operator("npr.presets_create", text="创建预设组", icon='PRESET')
        row.operator("npr.batch_apply", text="批量处理", icon='MOD_MULTIRESOLVE')


class NprAssignPanel(Panel):
    """把材质分配进当前组。

    流程：**收集候选 → 逐条勾选 → 加入当前组**。
    候选列表是插件自己维护的（不依赖材质自身的选中状态，因为 Blender 5.2 的
    ``bpy.types.Material`` 已经没有 ``select`` 属性），所以用户可以自由勾选
    "选中物体上的哪一个材质"要加入组。
    """

    bl_idname = "NPR_PT_assign"
    bl_label = "材质分配"
    bl_parent_id = "NPR_PT_root"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY

    def draw(self, context):
        layout = self.layout
        settings = _settings(context)
        if settings is None:
            return
        group = _active_group(context)

        # ---- 选中物体的材质槽（概览） ----
        box = layout.box()
        row = box.row()
        row.label(text="选中物体的材质槽", icon='MATERIAL')
        slots = utils.mesh_material_slots(utils.selected_meshes(context))
        row.label(text="共 %d 个" % len(slots))
        if slots:
            for obj, index, material in slots[:8]:
                line = box.row(align=True)
                line.label(text="%s[%d]" % (obj.name, index), icon='OBJECT_DATA')
                line.label(text=material.name)
            if len(slots) > 8:
                box.label(text="…还有 %d 个" % (len(slots) - 8))
        else:
            box.label(text="选中的物体上没有材质槽", icon='INFO')

        # ---- 收集候选 ----
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("npr.picker_collect", text="收集选中物体的材质", icon='IMPORT')
        row.operator("npr.picker_collect_all", text="收集场景全部", icon='MATERIAL')
        row = col.row(align=True)
        op = row.operator("npr.picker_toggle", text="全选", icon='CHECKBOX_HLT')
        op.value = True
        op = row.operator("npr.picker_toggle", text="全不选", icon='CHECKBOX_DEHLT')
        op.value = False
        row.operator("npr.picker_clear", text="", icon='TRASH')

        # ---- 候选列表（勾选） ----
        count = len(settings.picker_items)
        picked = len(settings.picker_selected_materials())
        box = layout.box()
        row = box.row()
        row.label(text="候选材质", icon='PRESET')
        row.label(text="已勾选 %d / %d" % (picked, count))

        if count:
            row = box.row()
            row.template_list("NPR_UL_picker", "", settings, "picker_items",
                              settings, "picker_index", rows=6)
            side = row.column(align=True)
            op = side.operator("npr.picker_add_one", text="", icon='ADD')
            op.index = settings.picker_index
            side.operator("npr.picker_collect", text="", icon='FILE_REFRESH')

            col = box.column(align=True)
            col.operator("npr.picker_add",
                         text="把勾选的 %d 个材质加入当前组" % picked,
                         icon='ADD')
            col.operator("npr.material_add", text="或：把选中物体全部材质加入组",
                         icon='DUPLICATE').scope = 'SLOTS'
        else:
            box.label(text="点「收集选中物体的材质」把材质收进来", icon='INFO')

        if group is None:
            layout.label(text="未选择材质组（先在「材质组管理」里选一个）", icon='ERROR')
            return

        # ---- 组内材质 ----
        box = layout.box()
        row = box.row()
        row.label(text="组「%s」内的材质" % group.name, icon='GROUP')
        row.label(text="%d 个" % len(group.materials))
        row = box.row()
        row.template_list("NPR_UL_group_materials", "", group, "materials",
                          group, "materials_index", rows=5)
        col = row.column(align=True)
        op = col.operator("npr.material_remove", text="", icon='REMOVE')
        op.index = group.materials_index
        col.operator("npr.material_clear", text="", icon='TRASH')

        col = layout.column(align=True)
        col.operator("npr.material_select", icon='RESTRICT_SELECT_OFF')
        col.operator("npr.material_sync_part", icon='FILE_REFRESH')


class NprSettingsPanel(Panel):
    """当前组的完整参数面板。"""

    bl_idname = "NPR_PT_settings"
    bl_label = "组设置"
    bl_parent_id = "NPR_PT_root"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            layout.label(text="请先在「材质组管理」里选择一个组", icon='INFO')
            return

        _draw_group_header(layout, group)

        col = layout.column(align=True)
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("npr.apply_group", icon='CHECKMARK')
        row = col.row(align=True)
        row.operator("npr.read_back", icon='IMPORT')
        row.operator("npr.reset_group", icon='LOOP_BACK')


class NprTexturePanel(Panel):
    """贴图输入（对应参考文件内嵌在各子组里的贴图节点）。"""

    bl_idname = "NPR_PT_textures"
    bl_label = "贴图输入"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            return

        box = layout.box()
        box.label(text="基础（参考文件 Base Color / Lightmap 组）", icon='TEXTURE')
        _draw_texture_row(box, group, "tex_base_color", "基础色 Diffuse")
        _draw_texture_row(box, group, "tex_lightmap", "光照 / 阴影 Lightmap")
        _draw_texture_row(box, group, "tex_normal", "法线 Normalmap")
        _draw_texture_row(box, group, "tex_ramp", "阴影 Ramp（256×20）")

        box = layout.box()
        box.label(text="高光与面部（参考文件 Specular / SDF 帧）", icon='TEXTURE')
        _draw_texture_row(box, group, "tex_metal", "金属 / 高光蒙版")
        _draw_texture_row(box, group, "tex_specular", "高光贴图")
        _draw_texture_row(box, group, "tex_sdf", "面部 SDF")

        box = layout.box()
        box.label(text="附加（参考文件 Eyes Shader / NodeGroup 组）", icon='TEXTURE')
        _draw_texture_row(box, group, "tex_emission", "自发光")
        _draw_texture_row(box, group, "tex_alpha", "Alpha")
        _draw_texture_row(box, group, "tex_matcap", "MatCap")
        row = box.row(align=True)
        row.label(text="瞳孔叠加（Eyes Shader）", icon='IMAGE_DATA')
        row = box.row(align=True)
        row.prop(group, "tex_pupil_a", text="")
        row.prop(group, "tex_pupil_b", text="")
        row.prop(group, "tex_pupil_c", text="")
        row = box.row(align=True)
        row.label(text="花纹叠加（NodeGroup）", icon='IMAGE_DATA')
        row = box.row(align=True)
        row.prop(group, "tex_detail_1", text="")
        row.prop(group, "tex_detail_2", text="")

        col = layout.column(align=True)
        col.prop(group, "base_color", text="基础色（无贴图时）")
        col.prop(group, "alpha_threshold", text="Alpha 阈值")


class NprShadingPanel(Panel):
    """基础色与光照（参考文件 Base Color 帧 + Light Vecter 组）。"""

    bl_idname = "NPR_PT_shading"
    bl_label = "基础色与光照"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            return
        col = layout.column(align=True)
        col.prop(group, "base_brightness")
        col.prop(group, "base_color_gain")
        col.prop(group, "halo_brightness")
        col.prop(group, "detail_strength")
        col.prop(group, "emission_strength")
        col.prop(group, "emission_color", text="自发光颜色")

        box = layout.box()
        box.label(text="主光方向（Light Vecter 组）", icon='LIGHT_SUN')
        box.prop(group, "light_euler", text="")
        box.prop(group, "light_intensity")
        box.label(text="默认值 = 参考文件：-0.34177 / 0.67079 / -140.36", icon='INFO')


class NprShadowPanel(Panel):
    """阴影与 AO（参考文件 AO 帧）。"""

    bl_idname = "NPR_PT_shadow"
    bl_label = "阴影与 AO"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            return
        col = layout.column(align=True)
        col.prop(group, "ao_bias")
        row = col.row(align=True)
        row.prop(group, "ao_smooth_lo")
        row.prop(group, "ao_smooth_hi")
        col.prop(group, "ao_add")
        col.prop(group, "shadow_threshold")


class NprSpecularPanel(Panel):
    """高光（参考文件 Specular 帧 + Blinn-Phong 组）。"""

    bl_idname = "NPR_PT_specular"
    bl_label = "高光"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            return
        col = layout.column(align=True)
        col.prop(group, "specular_enable")
        sub = col.column(align=True)
        sub.enabled = group.specular_enable
        sub.prop(group, "spec_gloss")
        sub.prop(group, "spec_darken")
        sub.prop(group, "spec_threshold")
        sub.prop(group, "spec_crystal_threshold")
        sub.prop(group, "crystal")

        box = layout.box()
        box.label(text="金属蒙版分支", icon='MATERIAL')
        box.prop(group, "metal_enable")
        row = box.row()
        row.enabled = group.metal_enable
        row.prop(group, "metal_threshold")


class NprRimPanel(Panel):
    """边缘光（参考文件 Rim 帧）。"""

    bl_idname = "NPR_PT_rim"
    bl_label = "边缘光"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            return
        col = layout.column(align=True)
        col.prop(group, "rim_enable")
        sub = col.column(align=True)
        sub.enabled = group.rim_enable
        sub.prop(group, "rim_color", text="边缘光颜色")
        sub.prop(group, "rim_intensity")
        sub.prop(group, "rim_power")
        sub.prop(group, "rim_looseness")
        row = sub.row(align=True)
        row.prop(group, "rim_lo")
        row.prop(group, "rim_hi")


class NprSdfPanel(Panel):
    """面部 SDF（参考文件 SDF 帧 + Head Vector 组）。"""

    bl_idname = "NPR_PT_sdf"
    bl_label = "面部 SDF"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            return
        layout.prop(group, "sdf_enable")
        box = layout.box()
        box.enabled = group.sdf_enable
        box.label(text="头部坐标系（Head Vector 组）", icon='ORIENTATION_GLOBAL')
        box.prop(group, "head_o", text="原点 O")
        box.prop(group, "head_front", text="前方点")
        box.prop(group, "head_right", text="右方点")
        box.label(text="默认值 = 参考文件实测坐标", icon='INFO')


class NprRampPanel(Panel):
    """阴影 Ramp（参考文件 Ramp 帧 + Ramp Select 组）。"""

    bl_idname = "NPR_PT_ramp"
    bl_label = "阴影 Ramp"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            return
        col = layout.column(align=True)
        col.prop(group, "ramp_enable")
        sub = col.column(align=True)
        sub.enabled = group.ramp_enable
        sub.prop(group, "ramp_strength")
        sub.prop(group, "ramp_band_scale")
        row = sub.row(align=True)
        row.prop(group, "ramp_band_0")
        row.prop(group, "ramp_band_1")
        row = sub.row(align=True)
        row.prop(group, "ramp_band_2")
        row.prop(group, "ramp_band_3")
        row = sub.row(align=True)
        row.prop(group, "ramp_band_4")
        sub.label(text="默认 4 / 3 / 5 / 2 = 参考文件 Ramp Select A1..A4", icon='INFO')
        sub.label(text="Ramp 强度 1.0 = 参考文件原样，0 = 关闭 Ramp", icon='INFO')


class NprOutlinePanel(Panel):
    """描边设置。

    参考文件没有描边实现，本面板按"倒角外壳（Solidify + 翻转法线 + 背面剔除）"路线，
    参数含义见 docs/REFERENCE_MAPPING.md。
    """

    bl_idname = "NPR_PT_outline"
    bl_label = "描边"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        group = _active_group(context)
        if group is None:
            return
        col = layout.column(align=True)
        col.prop(group, "outline_enable")
        col.prop(group, "outline_mode")

        sub = col.column(align=True)
        sub.enabled = group.outline_enable
        sub.prop(group, "outline_color", text="描边颜色")
        sub.prop(group, "outline_thickness")
        row = sub.row(align=True)
        row.prop(group, "outline_offset")
        row.prop(group, "outline_alpha")
        sub.prop(group, "outline_emission")
        sub.prop(group, "outline_threshold")
        sub.prop(group, "outline_even")
        sub.prop(group, "outline_use_texture")
        if group.outline_use_texture:
            _draw_texture_row(sub, group, "outline_tex", "描边贴图")

        row = layout.row(align=True)
        row.operator("npr.outline_apply", icon='MOD_SOLIDIFY')
        row.operator("npr.outline_remove", text="删除", icon='TRASH')


class NprMaterialPanel(Panel):
    """材质与渲染（参考文件实测的材质设置）。"""

    bl_idname = "NPR_PT_material"
    bl_label = "材质与渲染"
    bl_parent_id = "NPR_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = _settings(context)
        group = _active_group(context)
        if group is None or settings is None:
            return
        col = layout.column(align=True)
        col.prop(group, "surface_render_method", text="混合模式")

        box = layout.box()
        box.label(text="场景渲染（参考文件实测配置）", icon='SCENE_DATA')
        box.prop(settings, "sync_viewport")
        box.prop(settings, "enable_compositor_bloom")
        box.operator("npr.render_defaults", icon='RENDER_STILL')


class NprAdvancedPanel(Panel):
    """高级 / 调试：节点组、批量处理、日志、版本信息。"""

    bl_idname = "NPR_PT_advanced"
    bl_label = "高级 / 调试"
    bl_parent_id = "NPR_PT_root"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = _settings(context)
        if settings is None:
            return

        box = layout.box()
        box.label(text="Shader 节点组", icon='NODETREE')
        rows = shader_nodes.group_summary()
        total_nodes = sum(row[1] for row in rows)
        total_links = sum(row[2] for row in rows)
        box.label(text="共 %d 组 / %d 节点 / %d 连线" % (len(rows), total_nodes, total_links))
        stale = [row[0] for row in rows if row[1] and not row[3]]
        if stale:
            box.label(text="版本过旧：%s" % ", ".join(stale[:3]), icon='ERROR')
        row = box.row(align=True)
        row.operator("npr.rebuild_node_groups", icon='FILE_REFRESH')
        row.operator("npr.validate", text="自检", icon='CHECKMARK')

        box = layout.box()
        box.label(text="批量处理", icon='MOD_MULTIRESOLVE')
        row = box.row(align=True)
        row.operator("npr.batch_apply", icon='PLAY')
        box.prop(settings, "recursive")
        box.prop(settings, "delete_source_outlines")
        box.prop(settings, "outline_use_object_color")
        box.prop(settings, "outline_use_backface_culling")

        box = layout.box()
        row = box.row(align=True)
        row.label(text="日志", icon='TEXT')
        row.operator("npr.clear_log", text="", icon='TRASH')
        box.template_list("NPR_UL_log", "", settings, "log_entries",
                          settings, "log_entries_index", rows=5)

        box = layout.box()
        box.label(text="关于", icon='INFO')
        box.label(text="NPR Studio v%s" % utils.VERSION_STR)
        box.label(text="节点组内部版本：%d" % utils.NODE_GROUP_VERSION)
        box.label(text="Blender %s" % ".".join(str(v) for v in bpy.app.version))
        box.label(text="自包含：所有节点组由插件代码生成", icon='CHECKMARK')
        box.label(text="不收集任何用户数据", icon='CHECKMARK')


# --------------------------------------------------------------------------------------
# 注册
# --------------------------------------------------------------------------------------

classes = (
    NPR_UL_groups,
    NPR_UL_group_materials,
    NPR_UL_log,
    NPR_UL_picker,
    NprRootPanel,
    NprApplyPanel,
    NprGroupsPanel,
    NprAssignPanel,
    NprSettingsPanel,
    NprTexturePanel,
    NprShadingPanel,
    NprShadowPanel,
    NprSpecularPanel,
    NprRimPanel,
    NprSdfPanel,
    NprRampPanel,
    NprOutlinePanel,
    NprMaterialPanel,
    NprAdvancedPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
