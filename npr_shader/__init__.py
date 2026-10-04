# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Shader — 面向 Blender 5.2 / EEVEE 的自包含三渲二（NPR）插件。"""

bl_info = {
    "name": "NPR Shader",
    "author": "NPR Shader contributors",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "3D 视图 > 侧边栏(N) > 三渲二",
    "description": "自包含三渲二插件：按参考文件重建 Shader 节点组，一键材质 / 描边 / 模块化材质组",
    "category": "Material",
    "doc_url": "",
    "tracker_url": "",
    "support": 'COMMUNITY',
}

import importlib
import sys

import bpy

from . import utils

#: 子模块加载顺序（被依赖的先加载）
_MODULE_ORDER = (
    "utils",
    "properties",
    "shader_nodes",
    "outline",
    "presets",
    "core",
    "operators",
    "ui",
)

_loaded = []


def _reload_modules():
    """支持在 Blender 中热重载（开发用）。"""
    for name in _MODULE_ORDER:
        full = "%s.%s" % (__package__, name)
        if full in sys.modules:
            importlib.reload(sys.modules[full])


def _build_groups_now():
    """立即构建全部节点组（自包含：完全由代码生成）。

    Returns:
        bool: 构建成功（或无需构建）返回 True；数据尚不可用返回 False。
    """
    try:
        from . import shader_nodes
    except Exception as exc:  # noqa: BLE001
        print("[NPR Shader] 无法导入 shader_nodes：%s: %s" % (type(exc).__name__, exc))
        return False
    try:
        report = shader_nodes.ensure_all()
    except AttributeError as exc:
        # 启动阶段 bpy.data 是 _RestrictData 代理，访问 node_groups 会抛 AttributeError。
        # 这**不是**错误，而是"还不到时候"，由调用方安排稍后重试。
        text = str(exc)
        if "_RestrictData" in text or "node_groups" in text:
            return False
        print("[NPR Shader] 构建失败（AttributeError）：%s" % exc)
        return False
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("[NPR Shader] 构建失败：%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()
        return False
    if report["errors"]:
        utils.log("节点组构建出现错误：%s" % "; ".join(report["errors"]), 'ERROR')
    elif report["built"]:
        utils.log("已构建 %d 个 Shader 节点组" % len(report["built"]))
    return True


def _data_ready():
    """判断 ``bpy.data`` 是否真的是可用数据（而不是启动期的受限代理）。"""
    try:
        bpy.data.node_groups  # 触发代理的属性检查
        return True
    except AttributeError:
        return False


def _schedule_deferred_build():
    """挂上兜底机制：load_post handler + 低频 timer。

    二者互补：
    * ``load_post`` —— 每次打开/新建文件后检查（新建会清空 ``bpy.data``）；
    * ``timer`` —— 界面模式下持续低频自愈；后台模式（``-b``）不跑 timer，
      所以不能只依赖它。
    """
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    try:
        if not bpy.app.timers.is_registered(_on_timer):
            bpy.app.timers.register(_on_timer, first_interval=0.5)
    except (AttributeError, ValueError, TypeError):
        pass


def _on_load(_dummy=None):
    """打开/新建文件后：如果节点组被清掉了就补建。

    这一点很重要：``read_homefile()`` / 打开新文件会**清空** ``bpy.data``，
    里面所有节点组都没了。没有这个回调，用户新建场景后插件就会"看似装了但没节点组"。
    """
    if not _data_ready():
        return
    if not _has_all_groups():
        _build_groups_now()


def _on_timer():
    """数据可用后补建节点组。

    注意：**后台模式（``blender -b``）不跑 timer**，所以 timer 只能作为
    界面模式下的兜底；真正的兜底是 :func:`_on_load` 与
    :func:`shader_nodes.ensure_all` 的自愈。
    """
    if _data_ready() and not _has_all_groups():
        _build_groups_now()
    return 1.0  # 持续低频轮询：开销极小，但能自动修复"节点组被删"的情况


def _unregister_deferred():
    """移除兜底用的 handler / timer。"""
    for handler in list(bpy.app.handlers.load_post):
        if handler is _on_load:
            try:
                bpy.app.handlers.load_post.remove(handler)
            except (ValueError, TypeError):
                pass
    try:
        if bpy.app.timers.is_registered(_on_timer):
            bpy.app.timers.unregister(_on_timer)
    except (AttributeError, ValueError, TypeError):
        pass


def _has_all_groups():
    """是否 18 个节点组都已存在。"""
    from . import shader_nodes
    try:
        return all(name in bpy.data.node_groups for name in shader_nodes.BUILD_ORDER)
    except AttributeError:
        return False


def register():
    _reload_modules()
    _loaded.clear()
    for name in _MODULE_ORDER:
        module = sys.modules.get("%s.%s" % (__package__, name))
        if module is None:
            module = importlib.import_module(".%s" % name, __package__)
        hook = getattr(module, "register", None)
        if hook is not None:
            hook()
            _loaded.append(module)

    # 兜底机制（**必须先挂上**，再尝试构建）：
    #   1. timer：界面模式下持续低频检查；后台模式不跑，所以有第 2 条
    #   2. load_post：每次打开/新建文件后检查（新建会清空 bpy.data，必须补建）
    # 另外 shader_nodes.ensure_all() 自身是自愈的（缺哪个补哪个），
    # 所以即使用户手动删了节点组，任何一次"重建节点组"都能修好。
    _schedule_deferred_build()

    # 立刻尝试构建：多数情况（用户在已有文件里启用插件）此时数据已可用。
    _build_groups_now()


def unregister():
    _unregister_deferred()
    for module in reversed(_loaded):
        hook = getattr(module, "unregister", None)
        if hook is not None:
            try:
                hook()
            except Exception as exc:  # noqa: BLE001
                print("[NPR Shader] 卸载 %s 失败：%s" % (module.__name__, exc))
    _loaded.clear()


if __name__ == "__main__":
    register()
