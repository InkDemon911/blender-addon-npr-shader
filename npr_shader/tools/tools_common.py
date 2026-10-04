"""所有验证脚本共用的路径推断。

放在这里而不是各脚本里复制一份，是因为"插件父目录"在不同布局下层级不同：

* 已安装布局：``<addons>/npr_shader/tools/tools_x.py``  → 父目录是 ``<addons>``
* 仓库布局：``<repo>/npr_shader/tools/tools_x.py``      → 父目录是 ``<repo>``
* 源码直跑：``<work>/npr_shader/tools_x.py``            → 父目录是 ``<work>``

早期版本写死了层数，结果在"源码直跑"布局下推断成了 ``E:\\``，把整个磁盘根加进
``sys.path``（虽然没有立刻出错，但会带来 import 污染）。这里改成**向上搜索
包含 npr_shader 的那个目录**，对三种布局都成立。
"""
import os
import sys

#: 插件的包目录名。改名时只改这一处。
PACKAGE_NAME = "npr_shader"


def find_plugin_parent(start=None):
    """从 ``start``（默认本文件所在目录）向上找，返回**包含插件包**的目录。

    找不到时退回 ``start``，让调用方至少有一个确定的行为。
    """
    current = os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
    while True:
        if os.path.isdir(os.path.join(current, PACKAGE_NAME)):
            return current
        parent = os.path.dirname(current)
        if parent == current:  # 已到根
            return os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
        current = parent


def setup(extra_argv_index=1):
    """把插件父目录加入 ``sys.path`` 并返回它。

    Args:
        extra_argv_index: ``--`` 之后的第几个参数是插件父目录（1 = 第一个）。
            ``None`` 表示不解析命令行。
    """
    parent = None
    if extra_argv_index is not None and "--" in sys.argv:
        rest = sys.argv[sys.argv.index("--") + 1:]
        if len(rest) >= extra_argv_index:
            candidate = rest[extra_argv_index - 1]
            if os.path.isdir(candidate):
                parent = os.path.abspath(candidate)
    if parent is None:
        parent = find_plugin_parent()
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return parent
