# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Studio — 操作符（Operator）层。

所有会修改数据的操作符都带 ``{'UNDO'}``，因此 Ctrl+Z 可以完整回退
（材质替换、描边对象创建、参数批量应用都在单次撤销步内）。

命名约定：``npr.<动作>``。这里只做"取参数 → 调 core/outline → 写日志"，
业务逻辑全部在 core.py / outline.py / presets.py 中，便于测试与扩展。
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from . import core, outline, presets, shader_nodes, utils


# --------------------------------------------------------------------------------------
# 基类
# --------------------------------------------------------------------------------------

class NprOperator(Operator):
    """统一处理日志输出与异常兜底，避免插件报错打断用户操作。

    另外在 **每次执行前自动补齐节点组**：``__init_subclass__`` 会给每个子类
    包一层 ``execute``，先调用 :meth:`ensure_groups` 再执行原逻辑。
    这样任何入口（一键应用 / 仅描边 / 重建 / 反读…）第一次被点到时，
    都会自动修复"节点组缺失或被删坏"的状态，不依赖 Blender 的启动时机
    与 ``load_post`` 回调是否触发。
    """

    bl_options = {'REGISTER', 'UNDO'}

    def __init_subclass__(cls, **kwargs):
        """给每个子类的 ``execute`` 包一层"先补齐节点组"。

        注意不能给包装函数加第三个参数：Blender 校验操作符方法签名时要求
        ``execute(self, context)`` **恰好 2 个参数**，多一个默认参数会直接
        抛 ``ValueError: expected Operator ... to have 2 args, found 3`` 并导致
        注册失败。所以这里用闭包捕获原方法，签名保持 2 个参数。
        """
        super().__init_subclass__(**kwargs)
        original = cls.__dict__.get("execute")
        if original is None:
            return

        def _execute(self, context):
            try:
                self.ensure_groups()
            except Exception as exc:  # noqa: BLE001
                utils.log("节点组自愈失败：%s" % exc, 'WARNING')
            return original(self, context)

        _execute.__name__ = "execute"
        _execute.__doc__ = original.__doc__
        cls.execute = _execute

    @classmethod
    def description(cls, context, properties):
        return cls.__doc__ or ""

    def report_lines(self, lines, level: str = 'INFO') -> None:
        for line in lines or []:
            utils.log(line, level)

    def fail(self, message: str):
        utils.log(message, 'ERROR')
        self.report({'ERROR'}, message)
        return {'CANCELLED'}

    def succeed(self, message: str, lines=None):
        self.report_lines(lines)
        utils.log(message, 'INFO')
        self.report({'INFO'}, message)
        return {'FINISHED'}

    # -- 常用取值 ----------------------------------------------------------------
    def settings(self, context):
        return context.scene.npr_settings

    def active_group(self, context):
        settings = self.settings(context)
        group = settings.active_group()
        if group is None:
            return None
        return group

    def ensure_groups(self, force: bool = False) -> bool:
        """确保 18 个节点组存在且健康（自愈），失败时给出明确提示。

        ``ensure_all()`` 会重建"缺失 / 版本过期 / 不健康（空组或没有输出接口）"的组，
        因此这里可以在每个操作符入口放心调用，用来自动修复被删坏的节点组。
        设计上每个操作符都会在自己的 ``execute`` 里调一次，这样**不依赖**
        Blender 的启动时机或 load_post 回调是否触发 —— 插件在任何状态下被首次使用
        都能自我修复。
        """
        report = shader_nodes.ensure_all(force=force)
        if report["errors"]:
            utils.log("节点组构建失败：%s" % "; ".join(report["errors"]), 'ERROR')
            return False
        if report["built"]:
            utils.log("已补齐 %d 个 Shader 节点组" % len(report["built"]))
        return True


# --------------------------------------------------------------------------------------
# 一键应用
# --------------------------------------------------------------------------------------

class NPR_OT_texture_clear(NprOperator):
    """清空某个贴图槽（不影响贴图数据块本身）"""

    bl_idname = "npr.texture_clear"
    bl_label = "清空贴图槽"
    bl_options = {'REGISTER', 'UNDO'}

    slot: StringProperty(name="槽位", default="")

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        if not self.slot or not hasattr(group, self.slot):
            return self.fail("无效的贴图槽：%s" % self.slot)
        setattr(group, self.slot, None)
        return self.succeed("已清空贴图槽 %s" % self.slot)


class NPR_OT_apply(NprOperator):
    """对选中模型一键应用三渲二材质（按当前应用模式）"""

    bl_idname = "npr.apply"
    bl_label = "一键应用三渲二"

    mode: EnumProperty(
        name="应用模式",
        items=(
            ('SETTING', "使用面板设置", "使用场景设置里的应用模式"),
            ('REPLACE', "替换现有材质", "替换材质槽里的材质"),
            ('APPEND', "追加新材质", "在末尾追加 NPR 材质槽"),
            ('OUTLINE_ONLY', "仅添加描边", "只处理描边，不动材质"),
            ('REPLACE_KEEP_TEX', "替换并保留贴图", "替换材质并自动接管原贴图"),
        ),
        default='SETTING',
    )

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'EDIT_MESH'} or context.selected_objects

    def execute(self, context):
        settings = self.settings(context)
        group = self.active_group(context)
        if group is None:
            if not settings.auto_create_group:
                return self.fail("请先新建或选择一个材质组")
            objects = utils.selected_meshes(context)
            if not objects:
                return self.fail("请先选中至少一个网格物体")
            group = settings.new_group(objects[0].name)
            utils.log("已自动创建材质组「%s」" % group.name)

        if not self.ensure_groups():
            return self.fail("Shader 节点组构建失败，请查看日志")

        objects = utils.selected_meshes(context)
        if not objects:
            return self.fail("请先选中至少一个网格物体")

        mode = settings.apply_mode if self.mode == 'SETTING' else self.mode
        report = []
        try:
            summary = core.apply_to_objects(
                context, objects, group,
                mode=mode,
                slot_mode=settings.slot_mode,
                auto_texture=settings.auto_texture_detect,
                out_report=report,
            )
        except Exception as exc:  # noqa: BLE001
            return self.fail("应用失败：%s: %s" % (type(exc).__name__, exc))

        # 组内材质自动登记
        for material in summary["materials"]:
            group.add_material(material)

        if settings.sync_viewport:
            report.extend(presets.apply_render_defaults(context, settings.enable_compositor_bloom))

        return self.succeed("已应用组「%s」到 %d 个物体" % (group.name, len(objects)), report)


class NPR_OT_apply_group(NprOperator):
    """把当前组的参数统一应用到组内全部材质"""

    bl_idname = "npr.apply_group"
    bl_label = "应用整个组"

    force_rebuild: BoolProperty(
        name="强制重建节点",
        description="勾选后会清除材质节点重新生成（用于修复被手动改乱的材质）",
        default=False,
    )

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        try:
            report = core.apply_group(context, group, force_rebuild=self.force_rebuild)
        except Exception as exc:  # noqa: BLE001
            return self.fail("应用整组失败：%s: %s" % (type(exc).__name__, exc))
        return self.succeed("已应用整个组「%s」" % group.name, report)


class NPR_OT_read_back(NprOperator):
    """从组内材质反读参数回当前组（面板滑杆会同步）"""

    bl_idname = "npr.read_back"
    bl_label = "从材质反读"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        report = core.read_back_group(group)
        return self.succeed("已从材质反读「%s」的参数" % group.name, report)


class NPR_OT_reset_group(NprOperator):
    """把当前组参数重置为参考文件的默认值（保留组名、部位与贴图）"""

    bl_idname = "npr.reset_group"
    bl_label = "重置组参数"

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        core.reset_group(group)
        report = core.apply_group(context, group)
        return self.succeed("已重置组「%s」为参考文件默认值" % group.name, report)


# --------------------------------------------------------------------------------------
# 描边
# --------------------------------------------------------------------------------------

class NPR_OT_outline_apply(NprOperator):
    """为选中物体添加或更新描边（倒角外壳：Solidify + 翻转法线 + 背面剔除）"""

    bl_idname = "npr.outline_apply"
    bl_label = "一键添加 / 更新描边"

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        objects = utils.selected_meshes(context)
        if not objects:
            return self.fail("请先选中至少一个网格物体")
        if not self.ensure_groups():
            return self.fail("Shader 节点组构建失败")

        report = []
        try:
            result = outline.apply_outline(objects, group, mode=group.outline_mode, report=report)
        except Exception as exc:  # noqa: BLE001
            return self.fail("描边失败：%s: %s" % (type(exc).__name__, exc))

        issues = outline.selftest(objects, group)
        if issues:
            report.extend("提示：%s" % item for item in issues)
        return self.succeed(
            "描边完成：新增 %d / 更新 %d" % (len(result["created"]), len(result["updated"])), report)


class NPR_OT_outline_remove(NprOperator):
    """删除描边对象 / 描边修改器"""

    bl_idname = "npr.outline_remove"
    bl_label = "删除描边"

    scope: EnumProperty(
        name="范围",
        items=(
            ('SELECTED', "选中物体", "只删除选中物体的描边"),
            ('GROUP', "当前组", "删除当前组对应的描边"),
            ('ALL', "全部", "删除场景里所有 NPR 描边"),
        ),
        default='SELECTED',
    )

    def execute(self, context):
        settings = self.settings(context)
        if self.scope == 'ALL':
            count = outline.cleanup_all()
            return self.succeed("已删除全部 NPR 描边（%d 项）" % count)

        objects = utils.selected_meshes(context)
        group = self.active_group(context) if self.scope == 'GROUP' else None
        if self.scope == 'SELECTED' and not objects:
            return self.fail("请先选中至少一个网格物体")

        removed = outline.remove_outlines(objects if self.scope == 'SELECTED' else None, group)
        removed += outline.remove_modifier_outlines(objects)
        return self.succeed("已删除 %d 项描边" % removed)


class NPR_OT_outline_selftest(NprOperator):
    """检查当前描边设置是否存在常见问题（粗细为 0、未开背面剔除等）"""

    bl_idname = "npr.outline_selftest"
    bl_label = "描边自检"
    bl_options = {'REGISTER'}

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        issues = outline.selftest(utils.selected_meshes(context), group)
        if not issues:
            return self.succeed("描边自检通过：未发现问题")
        for item in issues:
            utils.log(item, 'WARN')
        return self.succeed("描边自检发现 %d 个问题，详见日志" % len(issues), issues)


# --------------------------------------------------------------------------------------
# 组管理
# --------------------------------------------------------------------------------------

class NPR_OT_group_new(NprOperator):
    """新建材质组"""

    bl_idname = "npr.group_new"
    bl_label = "新建组"

    name: StringProperty(name="组名", default="新建组")
    part: EnumProperty(
        name="部位",
        items=tuple((item[0], item[1], item[2]) for item in utils.PART_ITEMS),
        default='Body',
    )
    preset: EnumProperty(
        name="基于预设",
        items=tuple([('NONE', "空白组", "不套用任何预设")] +
                    [(item["name"], item["name"], item["description"]) for item in presets.PRESETS]),
        default='NONE',
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        settings = self.settings(context)
        if self.preset != 'NONE':
            group = presets.create_from_preset(settings, self.preset)
            return self.succeed("已按预设「%s」创建材质组「%s」" % (self.preset, group.name))
        group = settings.new_group(self.name or "新建组", self.part)
        material, _created = core.ensure_group_material(group)
        group.add_material(material)
        utils.log("已创建材质组「%s」（部位 %s），材质 %s" % (group.name, group.part, material.name))
        return self.succeed("已创建材质组「%s」" % group.name)


class NPR_OT_group_duplicate(NprOperator):
    """复制当前材质组（含全部参数与贴图引用）"""

    bl_idname = "npr.group_duplicate"
    bl_label = "复制组"

    def execute(self, context):
        settings = self.settings(context)
        source = settings.active_group()
        if source is None:
            return self.fail("没有选中的材质组")
        group = settings.new_group("%s_副本" % source.name, source.part)
        skip = {"name", "materials", "materials_index"}
        for prop in source.bl_rna.properties:
            key = prop.identifier
            if key in skip or prop.is_readonly:
                continue
            try:
                setattr(group, key, getattr(source, key))
            except (AttributeError, TypeError, ValueError):
                continue
        for material in source.material_list():
            group.add_material(material)
        return self.succeed("已复制组「%s」→「%s」" % (source.name, group.name))


class NPR_OT_group_rename(NprOperator):
    """重命名当前材质组"""

    bl_idname = "npr.group_rename"
    bl_label = "重命名组"

    name: StringProperty(name="新组名", default="")

    def invoke(self, context, event):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        self.name = group.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        settings = self.settings(context)
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        new_name = (self.name or "").strip()
        if not new_name:
            return self.fail("组名不能为空")
        if new_name != group.name:
            group.name = settings.unique_group_name(new_name)
        return self.succeed("组已重命名为「%s」" % group.name)


class NPR_OT_group_delete(NprOperator):
    """删除当前材质组（可选同时删除其 NPR 材质与描边）"""

    bl_idname = "npr.group_delete"
    bl_label = "删除组"

    remove_materials: BoolProperty(
        name="同时删除 NPR 材质",
        description="删除组生成的 NPR 材质数据块与描边对象（不会动原始材质）",
        default=False,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        settings = self.settings(context)
        index = settings.active_group_index
        group = settings.active_group()
        if group is None:
            return self.fail("没有选中的材质组")
        name = group.name
        if self.remove_materials:
            outline.remove_outlines(group=group)
            for material in group.material_list():
                if utils.is_npr_material(material):
                    bpy.data.materials.remove(material)
        settings.groups.remove(index)
        settings.active_group_index = max(0, min(index, len(settings.groups) - 1))
        return self.succeed("已删除组「%s」" % name)


class NPR_OT_group_move(NprOperator):
    """调整材质组顺序"""

    bl_idname = "npr.group_move"
    bl_label = "移动组"
    bl_options = {'REGISTER', 'UNDO'}

    delta: IntProperty(name="方向", default=-1)

    def execute(self, context):
        settings = self.settings(context)
        if not settings.move_group(settings.active_group_index, self.delta):
            return {'CANCELLED'}
        group = settings.active_group()
        return self.succeed("已移动到第 %d 位（%s）" % (settings.active_group_index + 1, group.name))


class NPR_OT_group_from_presets(NprOperator):
    """一键创建全部预设组（衣服 / 头发 / 身体 / 眼睛 / 脸部 / 睫眉 / 口齿 / 金属）"""

    bl_idname = "npr.presets_create"
    bl_label = "创建预设组"

    replace: BoolProperty(
        name="清空现有组",
        description="勾选后先删除现有全部材质组",
        default=False,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        settings = self.settings(context)
        if self.replace:
            settings.groups.clear()
        created = presets.ensure_default_groups(settings, only_if_empty=False)
        if not created:
            return self.fail("预设组已存在")
        return self.succeed("已创建 %d 个预设组：%s" % (len(created), ", ".join(created)))


class NPR_OT_group_activate(NprOperator):
    """把某个材质组设为当前组"""

    bl_idname = "npr.group_activate"
    bl_label = "选择组"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="索引", default=0)

    def execute(self, context):
        settings = self.settings(context)
        settings.active_group_index = max(0, min(self.index, len(settings.groups) - 1))
        group = settings.active_group()
        return self.succeed("当前组：%s" % (group.name if group else "无"))


# --------------------------------------------------------------------------------------
# 材质分配
# --------------------------------------------------------------------------------------

class NPR_OT_picker_collect(NprOperator):
    """从选中物体收集材质到候选列表（可勾选后加入组）"""

    bl_idname = "npr.picker_collect"
    bl_label = "收集选中物体的材质"

    keep: BoolProperty(
        name="保留勾选",
        description="勾选时保留同名材质原来的勾选状态（适合刷新列表）",
        default=True,
    )

    def execute(self, context):
        settings = self.settings(context)
        slots = utils.mesh_material_slots(utils.selected_meshes(context))
        if not slots:
            settings.picker_clear()
            return self.fail("选中的物体上没有材质槽")
        count = settings.picker_fill(slots, keep_selection=self.keep)
        scene_wide = len(bpy.data.materials)
        return self.succeed(
            "已收集 %d 个材质（场景里共 %d 个材质数据块）" % (count, scene_wide))


class NPR_OT_picker_collect_all(NprOperator):
    """把场景里所有材质都收进候选列表"""

    bl_idname = "npr.picker_collect_all"
    bl_label = "收集场景全部材质"

    def execute(self, context):
        settings = self.settings(context)
        materials = [m for m in bpy.data.materials]
        if not materials:
            return self.fail("场景里没有材质")
        settings.picker_clear()
        for material in materials:
            item = settings.picker_items.add()
            item.material = material
            item.selected = True
            item.source = "场景"
        return self.succeed("已收集场景里全部 %d 个材质" % len(materials))


class NPR_OT_picker_toggle(NprOperator):
    """全选 / 全不选候选材质"""

    bl_idname = "npr.picker_toggle"
    bl_label = "全选或全不选"

    value: BoolProperty(name="勾选", default=True)

    def execute(self, context):
        settings = self.settings(context)
        if not len(settings.picker_items):
            return self.fail("候选列表为空（先点「收集选中物体的材质」）")
        count = settings.picker_select_all(self.value)
        return self.succeed("%s %d 个候选材质" % ("已勾选" if self.value else "已取消", count))


class NPR_OT_picker_clear(NprOperator):
    """清空候选列表（不改动组内材质）"""

    bl_idname = "npr.picker_clear"
    bl_label = "清空候选列表"

    def execute(self, context):
        settings = self.settings(context)
        count = len(settings.picker_items)
        settings.picker_clear()
        return self.succeed("已清空候选列表（%d 条）" % count)


class NPR_OT_picker_add(NprOperator):
    """把候选列表里被勾选的材质加入当前组"""

    bl_idname = "npr.picker_add"
    bl_label = "加入当前组"

    def execute(self, context):
        settings = self.settings(context)
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组（先在「材质组管理」里选一个）")
        if not len(settings.picker_items):
            return self.fail("候选列表为空（先点「收集选中物体的材质」）")

        added, skipped = [], []
        for material in settings.picker_selected_materials():
            if group.add_material(material):
                utils.set_material_group(material, group.name, group.part)
                added.append(material.name)
            else:
                skipped.append(material.name)
        if not added:
            if skipped:
                return self.fail("选中的 %d 个材质都已经在组「%s」里了" % (len(skipped), group.name))
            return self.fail("没有勾选任何候选材质")
        message = "已把 %d 个材质加入组「%s」：%s" % (len(added), group.name, ", ".join(added))
        if skipped:
            message += "（%d 个已在组内，已跳过）" % len(skipped)
        return self.succeed(message)


class NPR_OT_picker_add_one(NprOperator):
    """把候选列表里的第 index 个材质加入当前组"""

    bl_idname = "npr.picker_add_one"
    bl_label = "加入当前组"

    index: IntProperty(name="索引", default=0)

    def execute(self, context):
        settings = self.settings(context)
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        if not (0 <= self.index < len(settings.picker_items)):
            return self.fail("候选索引越界")
        material = settings.picker_items[self.index].material
        if material is None:
            return self.fail("该候选材质已失效")
        if not group.add_material(material):
            return self.fail("材质「%s」已在组「%s」里" % (material.name, group.name))
        utils.set_material_group(material, group.name, group.part)
        return self.succeed("已把「%s」加入组「%s」" % (material.name, group.name))


class NPR_OT_material_add(NprOperator):
    """把材质加入当前组"""

    bl_idname = "npr.material_add"
    bl_label = "加入当前组"

    scope: EnumProperty(
        name="来源",
        items=(
            ('PICKER', "勾选的候选材质", "把「材质分配」面板里勾选的候选材质加入组"),
            ('ACTIVE', "活动材质", "把当前物体的活动材质加入组"),
            ('SLOTS', "全部槽位", "把选中物体的所有材质槽加入组"),
        ),
        default='PICKER',
    )

    def _candidates(self, context):
        settings = self.settings(context)
        if self.scope == 'PICKER':
            return settings.picker_selected_materials()
        if self.scope == 'ACTIVE':
            obj = context.active_object
            if obj is not None and obj.active_material is not None:
                return [obj.active_material]
            return []
        return [material for _obj, _index, material
                in utils.mesh_material_slots(utils.selected_meshes(context))]

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        if self.scope == 'PICKER' and not len(self.settings(context).picker_items):
            return self.fail("候选列表为空（先用「收集选中物体的材质」）")
        added = []
        for material in self._candidates(context):
            if material is None:
                continue
            if group.add_material(material):
                utils.set_material_group(material, group.name, group.part)
                added.append(material.name)
        if not added:
            return self.fail("没有可加入的材质（可能已在组内）")
        return self.succeed("已加入 %d 个材质：%s" % (len(added), ", ".join(added)))


class NPR_OT_material_remove(NprOperator):
    """从当前组移除材质"""

    bl_idname = "npr.material_remove"
    bl_label = "移除材质"

    index: IntProperty(name="索引", default=-1)

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        if self.index < 0:
            return self.fail("请先在列表里选中一个材质")
        ref = group.materials[self.index] if self.index < len(group.materials) else None
        name = ref.display_name() if ref else "?"
        if not group.remove_material_at(self.index):
            return self.fail("移除失败")
        group.materials_index = max(0, min(self.index, len(group.materials) - 1))
        return self.succeed("已从组内移除「%s」" % name)


class NPR_OT_material_clear(NprOperator):
    """清空当前组的材质列表"""

    bl_idname = "npr.material_clear"
    bl_label = "清空组内材质"

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        count = len(group.materials)
        group.materials.clear()
        return self.succeed("已清空组「%s」的 %d 个材质" % (group.name, count))


class NPR_OT_material_select(NprOperator):
    """选中组内材质对应的物体（便于在视口里检查）"""

    bl_idname = "npr.material_select"
    bl_label = "选中组内材质"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        wanted = set(group.material_list())
        if not wanted:
            return self.fail("组内没有材质")
        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        active = None
        for obj in bpy.data.objects:
            if obj.type != 'MESH':
                continue
            if any(slot.material in wanted for slot in obj.material_slots):
                obj.select_set(True)
                active = active or obj
                count += 1
        if active is not None:
            context.view_layer.objects.active = active
        return self.succeed("已选中 %d 个使用该组材质的物体" % count)


class NPR_OT_material_assign_part(NprOperator):
    """把当前组内材质的部位 mask 同步为组的部位设置"""

    bl_idname = "npr.material_sync_part"
    bl_label = "同步部位"

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        count = 0
        for material in group.material_list():
            master = utils.find_group_instance(material, shader_nodes.G_MASTER)
            if master is None:
                continue
            core._configure_master_inputs(master, group)  # noqa: SLF001 - 内部复用
            utils.set_material_group(material, group.name, group.part)
            count += 1
        return self.succeed("已同步 %d 个材质的部位与参数" % count)


# --------------------------------------------------------------------------------------
# 高级 / 调试
# --------------------------------------------------------------------------------------

class NPR_OT_rebuild_node_groups(NprOperator):
    """重建 / 更新插件的全部 Shader 节点组（不依赖任何外部 .blend）"""

    bl_idname = "npr.rebuild_node_groups"
    bl_label = "重建 / 更新节点组"

    force: BoolProperty(
        name="强制重建",
        description="即使版本号一致也重新生成（用于排查问题）",
        default=True,
    )

    def execute(self, context):
        report = shader_nodes.ensure_all(force=self.force)
        if report["errors"]:
            for item in report["errors"]:
                utils.log(item, 'ERROR')
            return self.fail("节点组构建出错 %d 项，详见日志" % len(report["errors"]))
        lines = ["已构建 %d 个节点组" % len(report["built"])]
        if report["skipped"]:
            lines.append("跳过 %d 个（已是最新）" % len(report["skipped"]))
        # 重建后刷新所有 NPR 材质的参数
        count = 0
        settings = self.settings(context)
        for group in settings.groups:
            for material in group.material_list():
                if core.update_material_parameters(material, group):
                    count += 1
        lines.append("已刷新 %d 个 NPR 材质" % count)
        return self.succeed("节点组已重建", lines)


class NPR_OT_batch_apply(NprOperator):
    """批量处理：对场景里所有网格物体（或选中物体的子物体）应用当前组"""

    bl_idname = "npr.batch_apply"
    bl_label = "批量处理"

    include_children: BoolProperty(name="包含子物体", default=True)
    visible_only: BoolProperty(
        name="仅可见物体",
        description="跳过被隐藏的物体",
        default=True,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        group = self.active_group(context)
        if group is None:
            return self.fail("没有选中的材质组")
        settings = self.settings(context)

        objects = []
        for obj in context.view_layer.objects:
            if obj.type != 'MESH':
                continue
            if self.visible_only and not obj.visible_get():
                continue
            objects.append(obj)
        if not objects:
            return self.fail("没有可处理的网格物体")
        if not self.ensure_groups():
            return self.fail("节点组构建失败")

        report = []
        summary = core.apply_to_objects(
            context, objects, group,
            mode=settings.apply_mode,
            slot_mode='REPLACE_FIRST',
            auto_texture=False,
            out_report=report,
        )
        for material in summary["materials"]:
            group.add_material(material)
        lines = report + ["共处理 %d 个物体 / %d 个材质槽" % (len(objects), summary["slots"])]
        return self.succeed("批量处理完成：%d 个物体" % len(objects), lines)


class NPR_OT_render_defaults(NprOperator):
    """按参考文件的配置设置渲染环境（EEVEE / Standard 色彩管理 / 可选 Bloom）"""

    bl_idname = "npr.render_defaults"
    bl_label = "应用渲染设置"
    bl_options = {'REGISTER', 'UNDO'}

    enable_bloom: BoolProperty(
        name="启用合成器 Bloom",
        description="按参考文件「合成器节点」的写法创建 RenderLayer → Glare(Bloom) → AlphaOver",
        default=True,
    )

    def execute(self, context):
        settings = self.settings(context)
        if self.enable_bloom:
            settings.enable_compositor_bloom = True
        notes = presets.apply_render_defaults(context, self.enable_bloom)
        return self.succeed("已应用参考文件的渲染设置", notes)


class NPR_OT_clear_log(NprOperator):
    """清空日志"""

    bl_idname = "npr.clear_log"
    bl_label = "清空日志"
    bl_options = {'REGISTER'}

    def execute(self, context):
        utils.clear_log()
        return {'FINISHED'}


class NPR_OT_validate(NprOperator):
    """插件自检：检查节点组、材质、描边与设置是否正常"""

    bl_idname = "npr.validate"
    bl_label = "插件自检"
    bl_options = {'REGISTER'}

    def execute(self, context):
        issues = []
        report = shader_nodes.ensure_all()
        issues.extend(report["errors"])

        for name, nodes, links, current in shader_nodes.group_summary():
            if nodes == 0:
                issues.append("节点组 %s 不存在" % name)
            elif not current:
                issues.append("节点组 %s 版本过旧（点「重建 / 更新节点组」）" % name)

        settings = self.settings(context)
        if len(settings.groups) == 0:
            issues.append("没有任何材质组（点「创建预设组」）")
        for group in settings.groups:
            if group.outline_enable and group.outline_thickness <= 0.0:
                issues.append("组「%s」启用了描边但粗细为 0" % group.name)
            for material in group.material_list():
                if utils.find_group_instance(material, shader_nodes.G_MASTER) is None:
                    issues.append("材质 %s 缺少 NPR_Shader 主组" % material.name)

        engine = context.scene.render.engine
        if engine != 'BLENDER_EEVEE':
            issues.append("当前渲染引擎是 %s，建议改为 EEVEE" % engine)
        if context.scene.view_settings.view_transform != 'Standard':
            issues.append("View Transform 不是 Standard，三渲二颜色会被冲淡")

        if issues:
            for item in issues:
                utils.log(item, 'WARN')
            return self.succeed("自检发现 %d 个问题，详见日志" % len(issues), issues)
        return self.succeed("自检通过：未发现问题")


# --------------------------------------------------------------------------------------
# 注册
# --------------------------------------------------------------------------------------

classes = (
    NPR_OT_texture_clear,
    NPR_OT_apply,
    NPR_OT_apply_group,
    NPR_OT_read_back,
    NPR_OT_reset_group,
    NPR_OT_outline_apply,
    NPR_OT_outline_remove,
    NPR_OT_outline_selftest,
    NPR_OT_group_new,
    NPR_OT_group_duplicate,
    NPR_OT_group_rename,
    NPR_OT_group_delete,
    NPR_OT_group_move,
    NPR_OT_group_from_presets,
    NPR_OT_group_activate,
    NPR_OT_picker_collect,
    NPR_OT_picker_collect_all,
    NPR_OT_picker_toggle,
    NPR_OT_picker_clear,
    NPR_OT_picker_add,
    NPR_OT_picker_add_one,
    NPR_OT_material_add,
    NPR_OT_material_remove,
    NPR_OT_material_clear,
    NPR_OT_material_select,
    NPR_OT_material_assign_part,
    NPR_OT_rebuild_node_groups,
    NPR_OT_batch_apply,
    NPR_OT_render_defaults,
    NPR_OT_clear_log,
    NPR_OT_validate,
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
