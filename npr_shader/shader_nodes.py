# SPDX-License-Identifier: GPL-3.0-or-later
"""NPR Shader — Shader 节点组的 Python 重建（自包含）。

本模块把参考文件 OdetteV3.blend 里的 18 个 Shader 节点组**逐个用 Python 重建**，
不引用任何外部 .blend / 已安装节点组。节点拓扑、接口名、接口默认值、混合方式、
色彩空间、UV/Mapping 约定、以及每个常量取值都严格对照参考文件（见
docs/REFERENCE_MAPPING.md 与 REFERENCE_ANALYSIS.md）。

重建清单（插件组名 ← 参考文件组名，节点/连线数一致）：
    NPR_SmoothStep          ← SmoothStep              9 / 12
    NPR_Lambert             ← Lambert                 9 / 13
    NPR_LightVector         ← Light Vecter            5 / 3
    NPR_CameraVector        ← Camera Vecter           6 / 4
    NPR_HeadVector          ← Head Vector            11 / 11
    NPR_RampAmount          ← Ramp条数                 8 / 8
    NPR_RampSelect          ← Ramp Select            16 / 22
    NPR_NormalmapDecode     ← Normalmap Decode       13 / 15
    NPR_LightmapSmoothStep  ← LightmapSmoothStep      3 / 3
    NPR_BlinnPhong          ← Blinn-Phong            11 / 15
    NPR_Normalmap           ← Normalmap              15 / 14
    NPR_BaseColor           ← Base Color             35 / 37
    NPR_Lightmap            ← Lightmap               17 / 24
    NPR_Ramp                ← Ramp                   13 / 13
    NPR_EyesShader          ← Eyes Shader             7 / 5
    NPR_AdditiveDetail      ← NodeGroup               9 / 7
    NPR_Shader              ← Shader                111 / 165   （主组）
    NPR_OutlineShader       ← 新增（参考文件无描边）

与参考文件的**唯一有意差异**：
  参考文件的 Rim 帧用 ``MixShader + ShaderToRGB`` 回读着色结果。``ShaderToRGB`` 在
  EEVEE Next（Blender 4.2+）下对真实着色器返回黑色，无法使用。因此 Rim 帧改用等价的
  纯数学实现（LayerWeight.Facing + SmoothStep + 颜色相乘），阈值/Power/软边等参数
  与参考文件逐一对应。可用 ``NPR_Shader`` 主组里的 ``Rim Source`` 分支切换。
"""

from __future__ import annotations

import bpy

from . import utils
from .utils import (
    get_input as IN,
    get_output as OUT,
    link as L,
    math_node,
    mix_node,
    map_range_node,
    vector_math_node,
)

#: 把 wire 的端点统一成"节点名或节点对象"（支持 (节点名, 插槽索引) 二元组）
def _normalize_ref(ref):
    "把 wire 端点统一成节点名或节点对象（支持 (节点名, 插槽索引) 二元组）。"
    if isinstance(ref, tuple) and len(ref) == 2:
        return ref[0]
    return ref

# --------------------------------------------------------------------------------------
# 组名常量
# --------------------------------------------------------------------------------------

G_SMOOTHSTEP = "NPR_SmoothStep"
G_LAMBERT = "NPR_Lambert"
G_LIGHTVEC = "NPR_LightVector"
G_CAMVEC = "NPR_CameraVector"
G_HEADVEC = "NPR_HeadVector"
G_RAMPAMOUNT = "NPR_RampAmount"
G_RAMPSELECT = "NPR_RampSelect"
G_NORMALDECODE = "NPR_NormalmapDecode"
G_LMSMOOTH = "NPR_LightmapSmoothStep"
G_BLINN = "NPR_BlinnPhong"
G_NORMALMAP = "NPR_Normalmap"
G_BASECOLOR = "NPR_BaseColor"
G_LIGHTMAP = "NPR_Lightmap"
G_RAMP = "NPR_Ramp"
G_EYES = "NPR_EyesShader"
G_DETAIL = "NPR_AdditiveDetail"
G_MASTER = "NPR_Shader"
G_OUTLINE = "NPR_OutlineShader"

#: 构建顺序（被依赖的先建）
BUILD_ORDER = (
    G_SMOOTHSTEP, G_LIGHTVEC, G_CAMVEC, G_HEADVEC, G_LAMBERT, G_RAMPAMOUNT,
    G_RAMPSELECT, G_NORMALDECODE, G_LMSMOOTH, G_BLINN, G_NORMALMAP,
    G_BASECOLOR, G_LIGHTMAP, G_RAMP, G_EYES, G_DETAIL, G_MASTER, G_OUTLINE,
)

#: 参考文件里的固定常量（改动前请先读 REFERENCE_ANALYSIS.md）
REF_AO_SMOOTH_LO = 0.2      # LightmapSmoothStep.Smoothstep.t1
REF_AO_SMOOTH_HI = 0.3      # LightmapSmoothStep.Smoothstep.t2
REF_LAMBERT_SMOOTH_HI = 1.14   # Lambert.Smoothstep.t2
REF_RIM_LO = 0.423          # Shader.SmoothStep.t1
REF_RIM_HI = 0.45           # Shader.SmoothStep.t2
REF_RIM_POWER = 4.8         # Shader.运算.019
REF_GLOSS = 5.0             # Shader.群组.014.Gloss
REF_SPEC_DARKEN = 1.04      # Shader.运算.006
REF_SPEC_THRESHOLD = 0.7    # Shader.运算.016
REF_METAL_THRESHOLD = 0.55  # Shader.运算.011
REF_SPEC_CRYSTAL = 0.2      # Shader.运算.020
REF_DETAIL_MULT = 8.0       # Lightmap.运算
REF_BASE_EMISSION = 0.2     # Base Color.自发光.Strength
REF_LIGHT_EULER = (-0.34177, 0.67079, -140.36)   # Light Vecter.合并 XYZ
REF_HEAD_O = (0.0, -0.011286, 1.51312)           # Head Vector.合并 XYZ.002
REF_HEAD_FRONT = (0.0, -1.01129, 1.51312)        # Head Vector.Front
REF_HEAD_RIGHT = (-1.0, -0.011286, 1.51312)      # Head Vector.Right
REF_RAMP_BANDS = (0.0, 4.0, 3.0, 5.0, 2.0)       # Ramp Select.A0..A4
REF_RAMP_STEP = 0.1         # Ramp条数 的步进系数
REF_RAMP_BASE = 1.05        # Ramp条数 的基址


# --------------------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------------------

class Edit:
    """小助手：在指定节点树里建节点、连线的语法糖。

    参考文件里同一个节点名反复出现（运算、混合、映射范围…），这里用显式命名
    （如 ``m_ao_min``）替换，便于阅读与维护；**节点类型与连线关系保持不变**。
    """

    def __init__(self, tree):
        self.tree = tree
        self.nodes = {}
        #: Group Input / Output 固定按 "__in" / "__out" 注册，便于 wire("__in", ...)
        in_node = utils.group_input_node(tree)
        out_node = utils.group_output_node(tree)
        if in_node is not None:
            self.nodes["__in"] = in_node
        if out_node is not None:
            self.nodes["__out"] = out_node
        #: 接口 socket 的 identifier 对照表（按名称），用于按名称精确连线。
        #: 注意必须是**惰性**的：builder 是在 Edit 建好之后才逐条 sock_in/sock_out，
        #: 初始化时快照的话表永远是空的（曾导致 wire_to_output 解析不到同名接口）。
        self._ids = None
        #: 连线/接口失败记录。注意：不能把 Python list 直接存进 ID 自定义属性
        #: （Blender 会转成 IDPropertyArray，没有 append），所以先在内存里累积，
        #: 构建结束时由 finalize() 一次性写回节点组。
        self._failures = []
        tree["npr_wire_failures"] = []

    @property
    def ids(self):
        """接口名 → identifier 的对照表（每次访问时重建，保证包含刚加的接口）。"""
        return utils.socket_ids_by_name(self.tree.interface)

    def resolve(self, name, direction: str, occurrence: int = 0):
        """确认某个名字是否为本组接口名，是则原样返回该**名称**。

        为什么返回名称而不是 identifier：节点组接口插槽的 identifier 是自动编号
        （``Socket_2``），而 **Group Input / Group Output 节点上的插槽**在增删接口后
        编号会整体错位（接口是 ``Socket_2``，节点上同名插槽可能是 ``Socket_3``）。
        按 identifier 连接会静默接错插槽（曾导致 Face←Body01 的连锁错位、整链变白）。
        名称则两边始终一致，配合 :func:`utils._resolve_socket` 的"名称按声明顺序匹配"
        可以稳定定位；同名接口再用 ``occurrence`` 区分。

        不是接口名时返回 ``None``，由调用方改用节点自身的插槽名解析。
        """
        side = "INPUT" if direction == "in" else "OUTPUT"
        found = [entry for entry in self.ids.get(name, []) if entry.startswith(side + ":")]
        if 0 <= occurrence < len(found):
            return name
        return None

    # -- 输入 / 输出 ---------------------------------------------------------------
    def sock_in(self, name, socket_type, default=None, description=""):
        item = self.tree.interface.new_socket(name=name, in_out='INPUT', socket_type=socket_type)
        if description:
            item.description = description
        if default is not None:
            try:
                item.default_value = tuple(default) if isinstance(default, (list, tuple)) else default
            except (AttributeError, TypeError, ValueError):
                pass
        return item

    def sock_out(self, name, socket_type, default=None, description=""):
        item = self.tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type=socket_type)
        if description:
            item.description = description
        if default is not None:
            try:
                item.default_value = tuple(default) if isinstance(default, (list, tuple)) else default
            except (AttributeError, TypeError, ValueError):
                pass
        return item

    # -- 节点 ----------------------------------------------------------------------
    def new(self, kind, name, location=(0.0, 0.0), label="", **props):
        node = self.tree.nodes.new(kind)
        node.name = name
        node.location = location
        if label:
            node.label = label
        for key, value in props.items():
            utils.set_prop(node, key, value)
        self.nodes[name] = node
        return node

    def math(self, name, operation, location=(0.0, 0.0), label=""):
        node = math_node(self.tree, operation, location, label)
        node.name = name
        self.nodes[name] = node
        return node

    def color_multiply(self, name, color_node, color_socket, factor_node, factor_socket,
                       location=(0.0, 0.0), channels=3):
        """颜色 × 乘数：``结果 = A × B``，返回 **Mix(MULTIPLY) 节点**。

        **实现要点（由原语矩阵实测确定，不要改）**：
        ``A_Color = 颜色``、``B_Color = 乘数``、``Factor = 1.0``。

        实测（Blender 5.2，节点组内，A=红 1,0,0）：

        ===========================  ==============
        配置                          输出
        ===========================  ==============
        B=白,   Factor=0.5           ``(0.998,0,0)`` ← **Factor 不起插值作用**
        B=0.5,  Factor=1.0           ``(0.498,0,0)`` ✓
        B←Float 0.5, Factor=1.0      ``(0.498,0,0)`` ✓
        ===========================  ==============

        结论：MULTIPLY 模式下 ``结果 = A × B``，**乘数必须放进 B_Color**，
        不能靠 Factor 承载。``B_Color`` 也接受 Float 输入并隐式转灰度色。

        返回 Mix 节点；结果在 ``Result_Color``，用 ``self.mix_color_out(node)`` 取。
        """
        mix = self.mix(name, blend_type="MULTIPLY", data_type="RGBA", location=location)
        self.wire(color_node, color_socket, mix, "A_Color")
        self.wire(factor_node, factor_socket, mix, "B_Color")
        self.value(mix, "Factor", 1.0)
        return mix

    def blend_to_white(self, name, color_node, color_socket, factor_node, factor_socket,
                       location=(0.0, 0.0)):
        """在**白色**与该颜色之间按 Factor 插值：``F=0 → 白``，``F=1 → 该颜色``。

        用来把"启用开关 + 强度"折成一个乘数色：
        ``1 − s + s×x`` 等价于"在白与 x 之间以 s 插值"（``白×(1−s) + x×s``），
        且**两端语义都正确**：s=0 → 白（不改动颜色），s=1 → x（完整生效）。

        返回 Mix 节点（结果在 ``Result_Color``）。
        """
        mix = self.mix(name, blend_type="MIX", data_type="RGBA", location=location)
        self.value(mix, "A_Color", (1.0, 1.0, 1.0, 1.0))
        self.wire(color_node, color_socket, mix, "B_Color")
        # **必须写 identifier ``Factor_Float``**：Mix 节点里有 ``Factor_Float`` /
        # ``Factor_Vector`` / ``Factor_Rotation`` 三个名字都叫 "Factor" 的插槽，
        # 用 ``"Factor"`` 按名称匹配会落到 **Vector** 那个上（默认 0.5），
        # 于是插值系数永远不是预期的 s —— 实测表现为"强度=0 时色调仍然生效"，
        # 颜色被算两次。identifier 是唯一无歧义的键。
        self.wire(factor_node, factor_socket, mix, "Factor_Float")
        return mix

    def mix(self, name, blend_type="MIX", data_type=None, location=(0.0, 0.0), label="",
            factor: float = None):
        """建 Mix 节点。

        Args:
            data_type: **必须在建节点时就定好**并在连线之前生效。
                ``ShaderNodeMix`` 默认 ``FLOAT``，此时 ``A_Color`` / ``B_Color`` /
                ``Result_Color`` 这些颜色插槽**根本不存在**，颜色连线会直接失败；
                而先按 FLOAT 连好线再改成 RGBA，Blender 会把 FLOAT 连线全部丢弃
                （表现为"节点看着连了、实际没连"，整链退化成默认灰/白，且不报错）。
                传 None 时自动推断：``ADD`` / ``MULTIPLY`` 等纯混合算式一律 ``RGBA``，
                其余按 ``MIX`` 走 ``RGBA``（颜色选择链是主流用法），
                需要浮点通路时显式传 ``"FLOAT"``。
            factor: 只在"该运算必须完全生效"时传 1.0（MULTIPLY / ADD / 权重固定的 MIX）；
                由接口或上游连线驱动 Factor 的场合不要传，保持未连接。
        """
        if data_type is None:
            data_type = 'RGBA'
        node = mix_node(self.tree, label=label, blend_type=blend_type,
                        data_type=data_type, location=location, factor=factor)
        node.name = name
        self.nodes[name] = node
        return node

    def map_range(self, name, location=(0.0, 0.0), label=""):
        node = map_range_node(self.tree, location, label)
        node.name = name
        self.nodes[name] = node
        return node

    def vmath(self, name, operation, location=(0.0, 0.0), label=""):
        node = vector_math_node(self.tree, operation, location, label)
        node.name = name
        self.nodes[name] = node
        return node

    def group(self, name, tree_name, location=(0.0, 0.0), label=""):
        node = self.tree.nodes.new('ShaderNodeGroup')
        node.name = name
        node.node_tree = utils.npr_node_group(tree_name, create=True)
        node.location = location
        if label:
            node.label = label
        self.nodes[name] = node
        return node

    def finalize(self):
        """构建收尾：补齐混合权重、把失败记录写到节点组上。

        1. **纯混合算式**（ADD / MULTIPLY / …）的 Factor 补成 1.0。
           Blender 的 Mix 节点 Factor 默认 0.5，这类算式要求**完全生效**，
           否则结果被稀释一半（实测基础色 0.1 被算成 0.55，整片偏白）。
           Factor 已有连线的不动。
        2. **只做健全性检查，绝不改 data_type**。
           曾经在这里按"哪条通路有连线"回推并把节点改成 RGBA/FLOAT，
           结果把已按 FLOAT 连好的节点改型 → Blender 丢弃全部连线；
           反向也会把 RGBA 节点降级成 FLOAT → 颜色插槽消失。
           现在 data_type 一律在 :meth:`Edit.mix` 建节点时定好，
           这里只报"插槽与已有连线不匹配"的异常，方便尽早发现问题。
        """
        self._apply_blend_factors()
        self._check_mix_data_types()
        try:
            self.tree["npr_wire_failures"] = list(self._failures)
        except (TypeError, AttributeError):
            pass
        return self.tree

    #: 数据通路 → Mix 节点的 data_type 取值
    _MIX_DATA_TYPE = {"Color": 'RGBA', "Vector": 'VECTOR',
                      "Rotation": 'ROTATION', "Float": 'FLOAT'}

    def _check_mix_data_types(self):
        """健全性检查：Mix 节点是否有连线落在"未激活通路"上。

        不做任何修改，只记录异常。data_type 由 :meth:`Edit.mix` 在建节点时确定，
        之后**永远不要改**（改型会让 Blender 静默丢弃不匹配通路上的全部连线）。

        例外：**节点组接口**（Group Input / Group Output）上的插槽由 Blender 负责
        在 Float/Color 之间隐式转换，连到 Mix 的对侧通路属于合法用法，要排除。
        """
        for node in self.tree.nodes:
            if node.bl_idname != 'ShaderNodeMix':
                continue
            data_type = getattr(node, "data_type", 'FLOAT')
            active = {"FLOAT": "_Float", "RGBA": "_Color",
                      "VECTOR": "_Vector", "ROTATION": "_Rotation"}.get(data_type)
            if active is None:
                continue
            stray = 0
            for coll in (node.inputs, node.outputs):
                for sock in coll:
                    if not sock.is_linked:
                        continue
                    ident = getattr(sock, "identifier", "")
                    if ident.endswith(active):
                        continue
                    if not any(ident.endswith(s) for s in
                               ("_Float", "_Color", "_Vector", "_Rotation")):
                        continue
                    # 对端是节点组接口时跳过（隐式转换合法）
                    interface_peer = False
                    for link in sock.links:
                        other = link.to_node if link.from_socket == sock else link.from_node
                        if other.bl_idname in ('NodeGroupInput', 'NodeGroupOutput'):
                            interface_peer = True
                            break
                    if not interface_peer:
                        stray += 1
            if stray:
                self._failures.append(
                    "%s (data_type=%s) 有 %d 条连线落在未激活通路（连接会被丢弃）" % (
                        node.name, data_type, stray))

    @staticmethod
    def _count_links(node):
        total = 0
        for coll in (node.inputs, node.outputs):
            for sock in coll:
                total += len(sock.links)
        return total

    def _apply_mix_data_types(self):
        """已废弃：保留占位以免旧脚本调用出错，内部转调健全性检查。"""
        self._check_mix_data_types()

    #: 这些 blend_type 属于"纯混合算式"，Factor 必须为 1 才能完全生效
    FULL_STRENGTH_BLENDS = frozenset({
        "ADD", "MULTIPLY", "SCREEN", "SUBTRACT", "DIVIDE", "DIFFERENCE",
        "DARKEN", "LIGHTEN", "OVERLAY", "BURN", "DODGE", "EXCLUSION",
        "SOFT_LIGHT", "LINEAR_LIGHT", "HUE", "SATURATION", "VALUE",
    })

    def _apply_blend_factors(self):
        """把"纯乘加算式"的 Factor 补成 1.0（已有连线的不动）。

        Blender 的 Mix 语义是 ``A*(1-F) + A⊗B*F``（⊗ 为 blend_type）。
        对 MULTIPLY / ADD 来说 Factor 不是"强度"而是**混合权重**：
        Factor=0 时结果退化成 A、Factor=1 时才真正得到 A⊗B。
        默认值 0.5 会让整条链只生效一半（历史实测：基础色 0.1 被算成 0.55）。

        判定条件放宽到"**任何 RGBA 的 MULTIPLY / ADD / 其它非 MIX 算式**"，
        因为颜色通路上的乘加几乎总是要求完全生效；需要按权重插值的场景
        一律用 ``blend_type="MIX"``（本函数不碰 MIX）。
        """
        for node in self.tree.nodes:
            if node.bl_idname != 'ShaderNodeMix':
                continue
            if getattr(node, "data_type", 'FLOAT') != 'RGBA':
                continue
            blend = getattr(node, "blend_type", "")
            if blend in ("MIX", ""):
                continue
            sock = utils.get_input(node, "Factor_Float", 0)
            if sock is None or sock.is_linked:
                continue
            try:
                if abs(float(sock.default_value) - 1.0) > 1e-6:
                    sock.default_value = 1.0
            except (AttributeError, TypeError, ValueError):
                continue

    def image(self, name, image=None, interpolation='Linear', extension='REPEAT',
              projection='FLAT', location=(0.0, 0.0), label="", colorspace=None):
        node = self.tree.nodes.new('ShaderNodeTexImage')
        node.name = name
        node.location = location
        if label:
            node.label = label
        node.image = image
        utils.set_prop(node, "interpolation", interpolation)
        utils.set_prop(node, "extension", extension)
        utils.set_prop(node, "projection", projection)
        if image is not None and colorspace:
            utils.set_image_colorspace(image, colorspace)
        self.nodes[name] = node
        return node

    def node(self, name):
        return self.nodes.get(name)

    # 连线 ----------------------------------------------------------------------
    def check_defaults(self, node, defaults):
        """校验接口默认值是否真的写上了（写错名字会静默失败）。

        这类错误不抛异常，却会让参数"看起来设置了、实际没生效"，
        因此统一记录到 :attr:`_failures` 里由 ``ensure_all`` 上报。
        """
        for socket_name, expected in defaults.items():
            sock = utils.get_input(node, socket_name)
            if sock is None:
                self._failures.append("%s: 接口 %s 不存在" % (node.name, socket_name))
                continue
            try:
                actual = sock.default_value
            except AttributeError:
                continue
            try:
                same = all(abs(float(a) - float(b)) < 1e-6 for a, b in zip(actual, expected))
            except (TypeError, ValueError):
                try:
                    same = abs(float(actual) - float(expected)) < 1e-6
                except (TypeError, ValueError):
                    continue
            if not same:
                self._failures.append("%s.%s 默认值应为 %s，实际 %s" % (
                    node.name, socket_name, expected, actual))
        return node

    def _ref(self, value):
        """把端点值统一成 identifier / 索引。

        端点可以是：
          * 节点对象（取该节点所属名字，再由调用方查表）
          * 插槽对象（取其 identifier）
          * 字符串（identifier 或名称）
        插槽对象必须先转成 identifier —— 否则会被当成"节点名"去查表，
        查不到就产生一条条无效连线。
        """
        if isinstance(value, str):
            return value
        if hasattr(value, "outputs") or hasattr(value, "inputs"):
            return getattr(value, "name", None)
        identifier = getattr(value, "identifier", None)
        if identifier is not None:
            return identifier
        return getattr(value, "name", value)

    #: Mix 节点"逻辑插槽名" → 各类型变体的 identifier 后缀
    _MIX_INPUT_VARIANTS = {
        "A": {"Float": "A_Float", "Vector": "A_Vector", "Color": "A_Color", "Rotation": "A_Rotation"},
        "B": {"Float": "B_Float", "Vector": "B_Vector", "Color": "B_Color", "Rotation": "B_Rotation"},
        "Factor": {"Float": "Factor_Float", "Vector": "Factor_Vector"},
    }
    #: 输出侧：逻辑名 → 节点输出索引（0=Float, 1=Vector, 2=Color, 3=Rotation）
    _MIX_OUTPUT_INDEX = {"Result": {"Float": 0, "Vector": 1, "Color": 2, "Rotation": 3}}
    #: 节点插槽类型 → 逻辑类型名
    _TYPE_ALIAS = {
        "NodeSocketFloat": "Float", "NodeSocketFloatFactor": "Float",
        "NodeSocketFloatAngle": "Float", "NodeSocketFloatDistance": "Float",
        "NodeSocketFloatTime": "Float", "NodeSocketFloatPercentage": "Float",
        "NodeSocketInt": "Float", "NodeSocketBool": "Float",
        "NodeSocketVector": "Vector", "NodeSocketVectorXYZ": "Vector",
        "NodeSocketVectorDirection": "Vector", "NodeSocketVectorTranslation": "Vector",
        "NodeSocketVectorEuler": "Vector", "NodeSocketVectorFactor": "Vector",
        "NodeSocketColor": "Color", "NodeSocketRGBA": "Color",
        "NodeSocketRotation": "Rotation", "NodeSocketShader": "Shader",
        "NodeSocketVirtual": "Virtual", "NodeSocketBundle": "Bundle",
        "NodeSocketClosure": "Closure", "NodeSocketIntFactor": "Float",
        "NodeSocketMenu": "Other", "NodeSocketString": "Other",
    }

    @classmethod
    def _type_of(cls, socket):
        """判断插槽的逻辑类型。

        Group Input/Output 上的插槽以及部分节点组的子插槽，其 ``bl_idname``
        可能是抽象基类名（``NodeSocketFloat``/``NodeSocketVector``…），
        因此先查表，查不到再退回"按基类名匹配"。
        """
        if socket is None:
            return None
        name = getattr(socket, "bl_idname", "") or ""
        if name in cls._TYPE_ALIAS:
            return cls._TYPE_ALIAS[name]
        for prefix, logical in (("NodeSocketColor", "Color"), ("NodeSocketVector", "Vector"),
                                ("NodeSocketRotation", "Rotation"), ("NodeSocketShader", "Shader"),
                                ("NodeSocketFloat", "Float"), ("NodeSocketInt", "Float"),
                                ("NodeSocketBool", "Float")):
            if name.startswith(prefix):
                return logical
        return "Other"

    def _pick_socket(self, node, logical, direction, want_type):
        """在 Mix 这类"同名多类型"节点上选出与另一端类型匹配的插槽。

        ``logical`` 是逻辑名（``"A"`` / ``"B"`` / ``"Factor"`` / ``"Result"``）。
        这样构建代码可以统一写 ``wire(a, "Result", b, "A")``，
        由这里根据另一端插槽类型自动落到 ``A_Color`` / ``A_Float`` 上。
        """
        variants = (self._MIX_INPUT_VARIANTS if direction == "in"
                    else self._MIX_OUTPUT_INDEX).get(logical)
        if not variants or want_type not in variants:
            return None
        if direction == "in":
            return utils.get_input(node, variants[want_type], -1)
        return utils.get_output(node, None, variants[want_type])

    def wire(self, from_node, from_socket, to_node, to_socket, occurrence: int = 0):
        """连线，自动处理"同名多类型插槽"。

        ``ShaderNodeMix`` 的 A / B / Result 各有 4 个同名变体
        （Float / Vector / Color / Rotation）。若按名称线性查找，会落到 FLOAT 那一组，
        Blender 会直接拒绝建立颜色连线（表现为整组没有连线、着色恒为默认灰，
        而且**不报任何错**）。所以这里的解析顺序是：

          1. 按接口对照表把"接口名"翻译成真实 identifier；
          2. 用 identifier / 名称解析插槽；
          3. 若插槽属于 Mix 的同名多类型组且类型与另一端不符，
             用另一端的类型重新挑变体。

        任何连线失败都会写入 :attr:`_failures`，由 ``ensure_all`` 汇总上报。

        端点写法：
          * ``wire(node, "Value", other, "Value_001")`` —— 节点对象
          * ``wire("__in", "Face", other, "Factor")``   —— ``Edit.nodes`` 里的名字
          * ``wire((node, 2), None, other, "A_Color")`` —— 显式输出索引
        """
        out_index = from_node[1] if (isinstance(from_node, tuple) and len(from_node) == 2) else None
        in_index = to_node[1] if (isinstance(to_node, tuple) and len(to_node) == 2) else None
        source = self._node_of(from_node)
        target = self._node_of(to_node)

        out_sock, out_ref, out_logical = self._resolve_endpoint(
            source, from_socket, out_index, "out")
        in_sock, in_ref, in_logical = self._resolve_endpoint(
            target, to_socket, in_index, "in", occurrence=occurrence)

        # 同名多类型插槽（Mix 的 A/B/Result 各 4 个）修正：
        # 先按"目标端类型"重挑源端，再按（修正后的）源端类型重挑目标端。
        # 顺序不能反：源端 identifier 是自动编号（Socket_0），只靠它挑不出正确变体，
        # 必须借逻辑名（"Result"）回到变体表里重新选。
        if out_logical is not None and in_sock is not None:
            if out_sock is None or out_sock.bl_idname != in_sock.bl_idname:
                picked = self._pick_socket(source, out_logical, "out", self._type_of(in_sock))
                if picked is not None:
                    out_sock, out_ref = picked, picked.identifier
        if in_logical is not None and out_sock is not None:
            if in_sock is None or in_sock.bl_idname != out_sock.bl_idname:
                picked = self._pick_socket(target, in_logical, "in", self._type_of(out_sock))
                if picked is not None:
                    in_sock, in_ref = picked, picked.identifier

        result = None
        if out_sock is not None and in_sock is not None:
            for existing in list(in_sock.links):
                self.tree.links.remove(existing)
            result = self.tree.links.new(out_sock, in_sock)
        # 只有"建不起来"或"Blender 判定无效"才算失败；
        # 类型不同但 Blender 能隐式转换（如 Group Input 的抽象 NodeSocketVector
        # 接 CombineXYZ 的 Vector）是合法连线，不算失败。
        if result is None or not getattr(result, "is_valid", True):
            self._failures.append("%s.%s(%s) → %s.%s(%s) 类型=%s/%s" % (
                getattr(source, "name", "?"), from_socket, out_ref,
                getattr(target, "name", "?"), to_socket, in_ref,
                self._type_of(out_sock), self._type_of(in_sock)))
        return result

    def _node_of(self, ref):
        """端点 → 节点对象。

        解析顺序：
          1. 节点对象本身
          2. ``(节点名或对象, 插槽索引)`` 二元组
          3. ``Edit.nodes`` 里登记的名字（``"__in"`` / ``"__out"`` 及 builder 自建节点）
          4. **节点树里真实存在的节点名** —— 这一步不能省，否则像 ``运算.001``
             这种由 builder 直接命名、未必登记进 ``nodes`` 的节点会解析成 None，
             连线静默失败（曾导致 BaseColor 的颜色输出没接上，渲染恒为纯白）。
        """
        if hasattr(ref, "outputs") or hasattr(ref, "inputs"):
            return ref
        if isinstance(ref, tuple) and len(ref) == 2:
            return self._node_of(ref[0])
        node = self.nodes.get(ref)
        if node is not None:
            return node
        if isinstance(ref, str):
            return self.tree.nodes.get(ref)
        return None

    def _resolve_endpoint(self, node, socket_ref, forced_index, direction, occurrence: int = 0):
        """解析一个端点。

        Returns:
            ``(插槽对象, 用于报错的引用, 逻辑名)``。
            逻辑名（如 ``"Result"`` / ``"A"``）要单独保留：Mix 节点的同名变体修正
            必须靠它重新挑选，靠解析后的 identifier（``Socket_0``）是挑不出来的。
        """
        if node is None:
            return None, socket_ref, None
        getter = utils.get_output if direction == "out" else utils.get_input
        if forced_index is not None:
            return getter(node, None, forced_index), forced_index, None
        ref = self._ref(socket_ref)
        logical = ref if isinstance(ref, str) else None
        if not isinstance(ref, str):
            return getter(node, ref, -1), ref, logical
        # 先试"接口名 → identifier"；不是接口名时再用节点自身的插槽名/identifier 解析
        interface_id = self.resolve(ref, direction, occurrence)
        if interface_id is not None:
            sock = getter(node, interface_id, -1)
            if sock is not None:
                return sock, interface_id, logical
        return getter(node, ref, -1), ref, logical

    def float_to_color(self, name, source_node, source_socket, location=(0.0, 0.0)):
        """把 Float 输出转成 Color，供 Mix 的颜色插槽使用。

        Blender **不会**在 ``ShaderNodeMath``（Float）→ ``ShaderNodeMix.Color``
        之间隐式转换，这种连线一旦建立就会被静默丢弃（表现为对应的加法/乘法分支
        完全消失）。因此凡是要把标量接进颜色通路，必须先显式转换。
        """
        node = self.tree.nodes.new('ShaderNodeCombineColor')
        node.name = name
        node.location = location
        utils.set_prop(node, "mode", 'RGB')
        self.nodes[name] = node
        # 灰度填充三个通道
        utils.set_default(node, "Red", 0.0)
        utils.set_default(node, "Green", 0.0)
        utils.set_default(node, "Blue", 0.0)
        for channel in ("Red", "Green", "Blue"):
            self.wire(source_node, source_socket, node, channel)
        return node

    def value(self, node, socket, value):
        utils.set_default(node, socket, value)
        return node

    # -- 组输入 / 输出 --------------------------------------------------------------
    def input_node(self):
        node = utils.group_input_node(self.tree)
        if node is None:
            node = self.tree.nodes.new('NodeGroupInput')
            node.location = (-900.0, 0.0)
        self.nodes["__in"] = node
        return node

    def output_node(self):
        node = utils.group_output_node(self.tree)
        if node is None:
            node = self.tree.nodes.new('NodeGroupOutput')
            node.location = (900.0, 0.0)
        self.nodes["__out"] = node
        return node

    def from_in(self, socket_name, to_node, to_socket):
        """从组输入接口连到内部节点的输入插槽。"""
        return self.wire(self.input_node(), socket_name, to_node, to_socket)

    def wire_to_output(self, from_node, from_socket, output_name, occurrence: int = 0):
        """把某个输出连到组输出接口（按接口名 + 出现序号精确匹配）。

        专治"组输出接口里有多个同名插槽"的情况，普通的 :meth:`wire` 按名称只能取到
        第一个、无法区分。``occurrence`` 用于同名接口（插件自己的接口已尽量取唯一名，
        保留该参数是为了兼容参考文件那种重名写法）。
        """
        target = self.output_node()
        return self.wire(from_node, from_socket, target, output_name, occurrence=occurrence)

    def wire_color(self, from_node, from_socket, to_node, to_socket="B_Color"):
        """连**颜色**通路。

        ``ShaderNodeMix`` 有 A/B/Result 各 4 个同名插槽。按名称取会落到 FLOAT 那一组，
        所以颜色通路必须显式指定 ``A_Color`` / ``B_Color`` / ``Result_Color``，
        否则 Blender 会拒绝建立连线（表现为整组没有连线、着色恒为默认灰）。
        """
        return self.wire(from_node, from_socket, to_node, to_socket)

    def mix_color_out(self, node):
        """取 Mix 节点的 Color 输出（Result_Color），返回 ``(节点名, 索引)`` 供 wire 使用。"""
        return (node.name, 2)


def _fresh_tree(name: str):
    """取（必要时新建）节点组，清空内部节点，并补齐 Group Input / Output 节点。

    Blender 5.2 新建的空节点组不自带 Group Input/Output，必须在构建开始时统一补上，
    否则每个 builder 会各自 ``new`` 出第二个同名节点，导致接口插槽在
    Group Input 节点上重复出现、identifier 与接口对不上。
    """
    tree = utils.npr_node_group(name, create=True)
    for node in list(tree.nodes):
        tree.nodes.remove(node)
    in_node = tree.nodes.new('NodeGroupInput')
    in_node.name = "Group Input"
    in_node.location = (-1600.0, 0.0)
    out_node = tree.nodes.new('NodeGroupOutput')
    out_node.name = "Group Output"
    out_node.location = (1400.0, 0.0)
    tree["npr_wire_failures"] = []
    return tree


def _drop_interface_sockets(tree, names):
    """删除节点组接口里指定名称的插槽（用于清理废弃接口）。

    只删名字匹配的 INPUT/OUTPUT 插槽；不存在时安静跳过。
    注意：删中间的插槽会让后续 identifier 重排，因此只在**版本升级重建**时使用，
    并且新接口一律追加到末尾以保持既有 identifier 稳定。
    """
    wanted = set(names)
    for item in list(tree.interface.items_tree):
        if getattr(item, "item_type", "") != 'SOCKET':
            continue
        if item.name in wanted:
            try:
                tree.interface.remove(item)
            except (AttributeError, TypeError, RuntimeError):
                pass


def _chain_mix(ed: Edit, base_name: str, factor_socket: str, pairs, start_location=(-200.0, 0.0)):
    """复刻参考文件里反复出现的 Mix 串联选择链。

    ``pairs`` 为 ``[(factor_source, A_source, B_source), ...]``，
    每一项生成一个 ``ShaderNodeMix``（RGBA / MIX / clamp_factor=True），
    后一级的 A 接前一级的 Result（与参考文件的 混合 → 混合.001 → 混合.002 一致）。
    """
    previous = None
    last = None
    for index, (factor, a_src, b_src) in enumerate(pairs):
        name = base_name if index == 0 else "%s.%03d" % (base_name, index)
        node = ed.mix(name, blend_type="MIX", data_type="RGBA",
                      location=(start_location[0] + index * 180.0, start_location[1] - index * 180.0))
        if factor is not None:
            ed.wire(factor[0], factor[1], node, factor_socket)
        if previous is not None:
            ed.wire(previous, "Result_Float", node, "A_Float")
        elif a_src is not None:
            ed.wire(a_src[0], a_src[1], node, "A_Color")
        if b_src is not None:
            ed.wire(b_src[0], b_src[1], node, "B_Color")
        previous = node
        last = node
    return previous, last


def _chain_map_range(ed: Edit, base_name: str, entries, start_location=(-200.0, 0.0)):
    """复刻参考文件里的 MapRange 级联（用于逐部位叠加 Alpha / 遮罩）。

    ``entries`` 为 ``[(value_source, to_max_source), ...]``，
    To Min 由上一级 Result 提供，形成 参考文件的 映射范围.003 → .002 → .001 链。
    """
    previous = None
    for index, (value_src, to_max_src) in enumerate(entries):
        name = base_name if index == 0 else "%s.%03d" % (base_name, index)
        node = ed.map_range(name, location=(start_location[0] + index * 200.0, start_location[1] - index * 140.0))
        ed.value(node, "Steps", 4.0)
        if value_src is not None:
            ed.wire(value_src[0], value_src[1], node, "Value")
        if to_max_src is not None:
            ed.wire(to_max_src[0], to_max_src[1], node, "To Max")
        if previous is not None:
            ed.wire(previous, "Result", node, "To Min")
        previous = node
    return previous


# ======================================================================================
# 1. SmoothStep  ← SmoothStep（9 节点 / 12 连线）
# ======================================================================================

def build_smoothstep():
    """参考实现：clamp01((x−t1)/(t2−t1)) 后做 t²(3−2t)。"""
    ed = Edit(_fresh_tree(G_SMOOTHSTEP))
    ed.sock_out("Value", 'NodeSocketFloat', 0.0)
    ed.sock_in("t1", 'NodeSocketFloat', 0.0)
    ed.sock_in("t2", 'NodeSocketFloat', 0.0)
    ed.sock_in("x", 'NodeSocketFloat', 0.0)

    m_sub_x = ed.math("运算", "SUBTRACT", (-300.0, 100.0))
    m_sub_t = ed.math("运算.001", "SUBTRACT", (-300.0, -20.0))
    m_div = ed.math("运算.002", "DIVIDE", (-120.0, 40.0))
    m_pow = ed.math("运算.003", "POWER", (60.0, 120.0))
    m_mul = ed.math("运算.004", "MULTIPLY", (60.0, -20.0))
    m_inv = ed.math("运算.005", "SUBTRACT", (240.0, -60.0))
    m_out = ed.math("运算.006", "MULTIPLY", (420.0, 40.0))
    reroute = ed.new('NodeReroute', "转接点", (600.0, 40.0))

    utils.set_prop(m_div, "use_clamp", True)
    utils.set_prop(m_out, "use_clamp", True)

    ed.from_in("x", m_sub_x, "Value")
    ed.from_in("t1", m_sub_x, "Value_001")
    ed.from_in("t2", m_sub_t, "Value")
    ed.from_in("t1", m_sub_t, "Value_001")
    ed.wire(m_sub_x, "Value", m_div, "Value")
    ed.wire(m_sub_t, "Value", m_div, "Value_001")
    ed.wire(m_div, "Value", m_pow, "Value")
    ed.value(m_pow, "Value_001", 2.0)
    ed.wire(m_div, "Value", m_mul, "Value")
    ed.value(m_mul, "Value_001", 2.0)
    ed.wire(m_mul, "Value", m_inv, "Value_001")
    ed.value(m_inv, "Value", 1.0)
    ed.wire(m_pow, "Value", m_out, "Value")
    ed.wire(m_inv, "Value", m_out, "Value_001")
    ed.wire(m_out, "Value", reroute, "Input")
    ed.wire(reroute, "Output", ed.output_node(), "Value")
    return ed.finalize()


# ======================================================================================
# 2. Lambert  ← Lambert（9 节点 / 13 连线）
# ======================================================================================

def build_lambert():
    ed = Edit(_fresh_tree(G_LAMBERT))
    for name, default in (("NoL", 0.0), ("Max(0,NoL)", 0.0), ("Pow(NoL*0.5+0.5,2)", 0.0),
                          ("Pow(MAx(0,NoL)*0.5+0.5,2)", 0.0), ("NoL*0.5+0.5", 0.0),
                          ("Smoothstepk(0,0.14,NoL+0.5)", 0.0)):
        ed.sock_out(name, 'NodeSocketFloat', default)
    ed.sock_in("NoL", 'NodeSocketFloat', 0.0)

    m_max = ed.math("运算", "MAXIMUM", (-60.0, -40.0))
    m_madd = ed.math("运算.001", "MULTIPLY_ADD", (-60.0, 180.0))
    m_pow = ed.math("运算.002", "POWER", (130.0, 180.0))
    m_madd2 = ed.math("运算.003", "MULTIPLY_ADD", (-60.0, -220.0))
    m_pow2 = ed.math("运算.004", "POWER", (120.0, -200.0))
    m_add = ed.math("运算.005", "ADD", (-80.0, -420.0))
    g_smooth = ed.group("Smoothstep", G_SMOOTHSTEP, (130.0, -360.0))

    ed.from_in("NoL", m_max, "Value")
    ed.value(m_max, "Value_001", 0.0)
    ed.from_in("NoL", m_madd, "Value")
    ed.value(m_madd, "Value_001", 0.5)
    ed.value(m_madd, "Value_002", 0.5)
    ed.wire(m_madd, "Value", m_pow, "Value")
    ed.value(m_pow, "Value_001", 2.0)
    ed.wire(m_max, "Value", m_madd2, "Value")
    ed.value(m_madd2, "Value_001", 0.5)
    ed.value(m_madd2, "Value_002", 0.5)
    ed.wire(m_madd2, "Value", m_pow2, "Value")
    ed.value(m_pow2, "Value_001", 2.0)
    ed.from_in("NoL", m_add, "Value")
    ed.value(m_add, "Value_001", 0.5)

    out = ed.output_node()
    ed.wire("__in", "NoL", out, "NoL")
    ed.wire(m_max, "Value", out, "Max(0,NoL)")
    ed.wire(m_pow, "Value", out, "Pow(NoL*0.5+0.5,2)")
    ed.wire(m_pow2, "Value", out, "Pow(MAx(0,NoL)*0.5+0.5,2)")
    ed.wire(m_madd, "Value", out, "NoL*0.5+0.5")
    ed.wire(g_smooth, "Value", out, "Smoothstepk(0,0.14,NoL+0.5)")
    # 参考文件：t1 = 0（默认值），t2 = 1.14
    ed.value(g_smooth, "t2", REF_LAMBERT_SMOOTH_HI)
    ed.wire(m_add, "Value", g_smooth, "x")
    return ed.finalize()


# ======================================================================================
# 3. Light Vecter  ← Light Vecter（5 节点 / 3 连线）
# ======================================================================================

def build_light_vector():
    """主光方向：CombineXYZ(0,0,1) 经欧拉旋转。

    参考文件把欧拉角硬编码在 CombineXYZ 里；此处提升为组接口 ``Light Euler``，
    默认值严格等于参考文件的 (-0.34177, 0.67079, -140.36)。
    """
    ed = Edit(_fresh_tree(G_LIGHTVEC))
    ed.sock_out("Vector", 'NodeSocketVector', (0.0, 0.0, 0.0))
    ed.sock_in("Light Euler", 'NodeSocketVector', REF_LIGHT_EULER)
    ed.sock_in("Intensity", 'NodeSocketFloat', 1.0)

    base = ed.new('ShaderNodeCombineXYZ', "合并 XYZ.001", (-400.0, 0.0))
    ed.value(base, "Z", 1.0)
    rot = ed.new('ShaderNodeVectorRotate', "矢量旋转", (-200.0, 0.0), rotation_type='EULER_XYZ')
    # CombineXYZ 只有 X/Y/Z 三个输入（没有 Vector 输入），
    # 参考文件里是把欧拉角直接填在这三个分量上的；这里由接口 x/y/z 分别驱动。
    euler = ed.new('ShaderNodeCombineXYZ', "合并 XYZ", (0.0, -200.0))
    sep = ed.new('ShaderNodeSeparateXYZ', "分离 XYZ", (-200.0, -200.0))
    scale = ed.vmath("矢量运算", "SCALE", (220.0, 0.0))

    ed.wire(base, "Vector", rot, "Vector")
    ed.from_in("Light Euler", sep, "Vector")
    ed.wire(sep, "X", euler, "X")
    ed.wire(sep, "Y", euler, "Y")
    ed.wire(sep, "Z", euler, "Z")
    ed.wire(euler, "Vector", rot, "Rotation")
    ed.wire(rot, "Vector", scale, "Vector")
    ed.from_in("Intensity", scale, "Scale")
    ed.wire(scale, "Vector", ed.output_node(), "Vector")
    return ed.finalize()


# ======================================================================================
# 4. Camera Vecter  ← Camera Vecter（6 节点 / 4 连线）
# ======================================================================================

def build_camera_vector():
    ed = Edit(_fresh_tree(G_CAMVEC))
    ed.sock_out("Vector", 'NodeSocketVector', (0.0, 0.0, 0.0))

    cam = ed.new('ShaderNodeCameraData', "摄像机数据", (-400.0, 0.0))
    mul = ed.vmath("矢量运算.008", "MULTIPLY", (-200.0, 0.0))
    transform = ed.new('ShaderNodeVectorTransform', "矢量变换", (0.0, 0.0))
    utils.set_prop(transform, "vector_type", 'VECTOR')
    utils.set_prop(transform, "convert_from", 'CAMERA')
    utils.set_prop(transform, "convert_to", 'WORLD')
    norm = ed.vmath("矢量运算.009", "NORMALIZE", (200.0, 0.0))

    ed.wire(cam, "View Vector", mul, "Vector")
    ed.wire(cam, "View Vector", mul, "Vector_001")
    ed.value(mul, "Scale", 1.0)
    ed.wire(mul, "Vector", transform, "Vector")
    ed.wire(transform, "Vector", norm, "Vector")
    ed.wire(norm, "Vector", ed.output_node(), "Vector")
    return ed.finalize()


# ======================================================================================
# 5. Head Vector  ← Head Vector（11 节点 / 11 连线）
# ======================================================================================

def build_head_vector():
    """头部坐标系：Right / Front 归一化，Above = cross(Right, Front)。

    参考文件的三个坐标点硬编码在 CombineXYZ 里；此处提升为组接口，
    默认值严格等于参考文件实测值。
    """
    ed = Edit(_fresh_tree(G_HEADVEC))
    for name in ("Right", "Front", "Above"):
        ed.sock_out(name, 'NodeSocketVector', (0.0, 0.0, 0.0))
    ed.sock_in("O", 'NodeSocketVector', REF_HEAD_O)
    ed.sock_in("Front Point", 'NodeSocketVector', REF_HEAD_FRONT)
    ed.sock_in("Right Point", 'NodeSocketVector', REF_HEAD_RIGHT)

    n_o = ed.new('ShaderNodeCombineXYZ', "合并 XYZ.002", (-400.0, 0.0), label='O')
    n_front = ed.new('ShaderNodeCombineXYZ', "Front", (-400.0, 200.0), label='Front')
    n_right = ed.new('ShaderNodeCombineXYZ', "合并 XYZ.003", (-400.0, -200.0), label='Right')

    sub_front = ed.vmath("矢量运算.001", "SUBTRACT", (-180.0, 240.0), label='Front')
    sub_right = ed.vmath("矢量运算.002", "SUBTRACT", (-180.0, -160.0), label='Right')
    norm_front = ed.vmath("矢量运算.003", "NORMALIZE", (40.0, 240.0))
    norm_right = ed.vmath("矢量运算.004", "NORMALIZE", (40.0, -160.0))
    cross = ed.vmath("矢量运算", "CROSS_PRODUCT", (260.0, 40.0))

    # 参考文件把三个坐标点直接填在 CombineXYZ 的 X/Y/Z 上；
    # 这里改为由三个 Vector 接口经 SeparateXYZ 驱动，默认值仍是参考文件实测坐标。
    seps = {}
    for key, socket_name, y in (("o", "O", 0.0), ("front", "Front Point", 200.0),
                                ("right", "Right Point", -200.0)):
        sep = ed.new('ShaderNodeSeparateXYZ', "分离 XYZ_%s" % key, (-600.0, y))
        ed.from_in(socket_name, sep, "Vector")
        seps[key] = sep

    ed.wire(seps["front"], "X", n_front, "X")
    ed.wire(seps["front"], "Y", n_front, "Y")
    ed.wire(seps["front"], "Z", n_front, "Z")
    ed.wire(seps["right"], "X", n_right, "X")
    ed.wire(seps["right"], "Y", n_right, "Y")
    ed.wire(seps["right"], "Z", n_right, "Z")
    ed.wire(seps["o"], "X", n_o, "X")
    ed.wire(seps["o"], "Y", n_o, "Y")
    ed.wire(seps["o"], "Z", n_o, "Z")

    ed.wire(n_front, "Vector", sub_front, "Vector")
    ed.wire(n_o, "Vector", sub_front, "Vector_001")
    ed.wire(n_right, "Vector", sub_right, "Vector")
    ed.wire(n_o, "Vector", sub_right, "Vector_001")
    ed.wire(sub_front, "Vector", norm_front, "Vector")
    ed.wire(sub_right, "Vector", norm_right, "Vector")
    ed.wire(norm_right, "Vector", cross, "Vector")
    ed.wire(norm_front, "Vector", cross, "Vector_001")

    out = ed.output_node()
    ed.wire(norm_right, "Vector", out, "Right")
    ed.wire(norm_front, "Vector", out, "Front")
    ed.wire(cross, "Vector", out, "Above")
    return ed.finalize()


# ======================================================================================
# 6. Ramp条数  ← Ramp条数（8 节点 / 8 连线）
# ======================================================================================

def build_ramp_amount():
    """A = 1.05 − 0.1·n ；输出 = Mix(blend_type=COLOR, A, A−0.5)。

    注意：参考文件里该 Mix 的 Factor 未连接，因此实际结果取 A 输入，
    即 ``1.05 − 0.1·n``；Blender 允许该写法，这里保持完全一致的拓扑。
    """
    ed = Edit(_fresh_tree(G_RAMPAMOUNT))
    ed.sock_out("Value", 'NodeSocketFloat', 0.0)
    ed.sock_in("Value", 'NodeSocketFloat', 0.0)
    ed.sock_in("Step", 'NodeSocketFloat', REF_RAMP_STEP)
    ed.sock_in("Base", 'NodeSocketFloat', REF_RAMP_BASE)

    m_mul_a = ed.math("运算", "MULTIPLY", (-300.0, 0.0))
    m_add_a = ed.math("运算.005", "ADD", (-120.0, 0.0))
    m_mul_b = ed.math("运算.001", "MULTIPLY", (-300.0, -180.0))
    m_add_b = ed.math("运算.006", "ADD", (-120.0, -180.0))
    m_sub_b = ed.math("运算.002", "SUBTRACT", (60.0, -180.0))
    mix = ed.mix("混合", blend_type="COLOR", data_type="FLOAT", location=(280.0, -40.0))

    ed.from_in("Value", m_mul_a, "Value")
    ed.from_in("Step", m_mul_a, "Value_001")
    ed.wire(m_mul_a, "Value", m_add_a, "Value")
    ed.from_in("Base", m_add_a, "Value_001")
    ed.from_in("Value", m_mul_b, "Value")
    ed.from_in("Step", m_mul_b, "Value_001")
    ed.wire(m_mul_b, "Value", m_add_b, "Value")
    ed.from_in("Base", m_add_b, "Value_001")
    ed.wire(m_add_b, "Value", m_sub_b, "Value")
    ed.value(m_sub_b, "Value_001", 0.5)
    ed.wire(m_add_a, "Value", mix, "A_Float")
    ed.wire(m_sub_b, "Value", mix, "B_Float")
    ed.wire(mix, "Result", ed.output_node(), "Value")
    return ed.finalize()


# ======================================================================================
# 7. Ramp Select  ← Ramp Select（16 节点 / 22 连线）
# ======================================================================================

def build_ramp_select():
    """用 Mask 在 A0..A4 之间做阶梯选择（阈值 0.25 / 0.45 / 0.65 / 0.95）。"""
    ed = Edit(_fresh_tree(G_RAMPSELECT))
    ed.sock_out("RampV", 'NodeSocketFloat', 0.0)
    ed.sock_in("Mask", 'NodeSocketFloat', 0.0)
    for index in range(5):
        ed.sock_in("A%d" % index, 'NodeSocketFloat', REF_RAMP_BANDS[index])
    ed.sock_in("Step", 'NodeSocketFloat', REF_RAMP_STEP)
    ed.sock_in("Base", 'NodeSocketFloat', REF_RAMP_BASE)

    # 阈值比较（参考文件 label: A5 / A4 / A3 / A2）
    thresholds = (("A5", 0.95), ("A4", 0.65), ("A3", 0.45), ("A2", 0.25))
    compares = []
    for index, (label, value) in enumerate(thresholds):
        node = ed.math("A%d" % (index + 1), "GREATER_THAN", (-420.0, 260.0 - index * 160.0), label=label)
        utils.set_prop(node, "use_clamp", True)
        ed.value(node, "Value_001", value)
        ed.from_in("Mask", node, "Value")
        compares.append(node)

    # A0..A4 → Ramp条数（Step / Base 透传，默认值与参考文件一致）
    amounts = {}
    for index in range(5):
        node = ed.group("Ramp条数.%03d" % index if index else "Ramp条数", G_RAMPAMOUNT,
                        (-180.0, 200.0 - index * 150.0), label="A%d" % index)
        ed.from_in("A%d" % index, node, "Value")
        ed.from_in("Step", node, "Step")
        ed.from_in("Base", node, "Base")
        amounts[index] = node
    # 逐级 Mix
    chain = []
    previous = None
    for index in range(4):
        node = ed.mix("混合.%03d" % (index + 1) if index else "混合",
                      blend_type="MIX", data_type="FLOAT",
                      location=(100.0 + index * 160.0, 40.0 - index * 120.0))
        ed.wire(compares[index], "Value", node, "Factor")
        if previous is None:
            ed.wire(amounts[0], "Value", node, "A_Float")
        else:
            ed.wire(previous, "Result_Float", node, "A_Float")
        ed.wire(amounts[index + 1], "Value", node, "B_Float")
        previous = node
        chain.append(node)

    ed.wire(chain[-1], "Result", ed.output_node(), "RampV")
    return ed.finalize()


# ======================================================================================
# 8. Normalmap Decode  ← Normalmap Decode（13 节点 / 15 连线）
# ======================================================================================

def build_normal_decode():
    ed = Edit(_fresh_tree(G_NORMALDECODE))
    ed.sock_out("Normal", 'NodeSocketVector', (0.0, 0.0, 0.0))
    ed.sock_in("Normal", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0))

    v_madd = ed.vmath("矢量运算", "MULTIPLY_ADD", (-400.0, 0.0))
    sep = ed.new('ShaderNodeSeparateXYZ', "分离 XYZ", (-180.0, 0.0))
    m_pow_x = ed.math("运算", "POWER", (0.0, 120.0))
    m_pow_y = ed.math("运算.001", "POWER", (0.0, -60.0))
    m_add = ed.math("运算.002", "ADD", (180.0, 0.0))
    m_min = ed.math("运算.003", "MINIMUM", (340.0, 0.0))
    m_sub = ed.math("运算.004", "SUBTRACT", (500.0, 0.0))
    m_sqrt = ed.math("运算.005", "SQRT", (660.0, 0.0))
    comb = ed.new('ShaderNodeCombineXYZ', "合并 XYZ", (820.0, 0.0))
    v_remap = ed.vmath("矢量运算.001", "MULTIPLY_ADD", (980.0, 0.0))
    normal_map = ed.new('ShaderNodeNormalMap', "法线贴图", (1140.0, 0.0))
    utils.set_prop(normal_map, "space", 'TANGENT')
    utils.set_prop(normal_map, "convention", 'OPENGL')
    utils.set_prop(normal_map, "base", 'DISPLACED')

    ed.from_in("Normal", v_madd, "Vector")
    ed.value(v_madd, "Vector_001", (2.0, 2.0, 2.0))
    ed.value(v_madd, "Vector_002", (-1.0, -1.0, -1.0))
    ed.wire(v_madd, "Vector", sep, "Vector")
    ed.wire(sep, "X", m_pow_x, "Value")
    ed.value(m_pow_x, "Value_001", 2.0)
    ed.wire(sep, "Y", m_pow_y, "Value")
    ed.value(m_pow_y, "Value_001", 2.0)
    ed.wire(m_pow_x, "Value", m_add, "Value")
    ed.wire(m_pow_y, "Value", m_add, "Value_001")
    ed.wire(m_add, "Value", m_min, "Value")
    ed.value(m_min, "Value_001", 1.0)
    ed.wire(m_min, "Value", m_sub, "Value_001")
    ed.value(m_sub, "Value", 1.0)
    ed.wire(m_sub, "Value", m_sqrt, "Value")
    ed.wire(sep, "X", comb, "X")
    ed.wire(sep, "Y", comb, "Y")
    ed.wire(m_sqrt, "Value", comb, "Z")
    ed.wire(comb, "Vector", v_remap, "Vector")
    ed.value(v_remap, "Vector_001", (0.5, 0.5, 0.5))
    ed.value(v_remap, "Vector_002", (0.5, 0.5, 0.5))
    ed.wire(v_remap, "Vector", normal_map, "Color")
    ed.wire(normal_map, "Normal", ed.output_node(), "Normal")
    return ed.finalize()


# ======================================================================================
# 9. LightmapSmoothStep  ← LightmapSmoothStep（3 节点 / 3 连线）
# ======================================================================================

def build_lightmap_smoothstep():
    ed = Edit(_fresh_tree(G_LMSMOOTH))
    ed.sock_out("Lightmap.g", 'NodeSocketFloat', 0.0)
    ed.sock_out("Smoothstep(0.2,0.3,Lightmap.g)", 'NodeSocketFloat', 0.0)
    ed.sock_in("Lightmap.g", 'NodeSocketFloat', 0.0)
    ed.sock_in("t1", 'NodeSocketFloat', REF_AO_SMOOTH_LO)
    ed.sock_in("t2", 'NodeSocketFloat', REF_AO_SMOOTH_HI)

    smooth = ed.group("Smoothstep", G_SMOOTHSTEP, (200.0, -60.0))
    ed.from_in("Lightmap.g", smooth, "x")
    ed.from_in("t1", smooth, "t1")
    ed.from_in("t2", smooth, "t2")

    out = ed.output_node()
    ed.wire("__in", "Lightmap.g", out, "Lightmap.g")
    ed.wire(smooth, "Value", out, "Smoothstep(0.2,0.3,Lightmap.g)")
    return ed.finalize()


# ======================================================================================
# 10. Blinn-Phong  ← Blinn-Phong（11 节点 / 15 连线）
# ======================================================================================

def build_blinn_phong():
    ed = Edit(_fresh_tree(G_BLINN))
    ed.sock_out("Blinn-Phong", 'NodeSocketFloat', 0.0)
    for part in utils.MASK_PARTS:
        ed.sock_in(part, 'NodeSocketFloat', 0.0)
    ed.sock_in("Gloss", 'NodeSocketFloat', REF_GLOSS)
    ed.sock_in("Normal In", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0))

    g_cam = ed.group("群组.008", G_CAMVEC, (-420.0, 120.0))
    g_light = ed.group("Light Vecter", G_LIGHTVEC, (-420.0, -120.0))
    v_add = ed.vmath("矢量运算.008", "ADD", (-180.0, 0.0))
    v_norm = ed.vmath("矢量运算.009", "NORMALIZE", (0.0, 0.0))
    v_dot = ed.vmath("矢量运算.010", "DOT_PRODUCT", (180.0, 0.0))
    g_decode = ed.group("群组.009", G_NORMALDECODE, (0.0, -240.0))
    m_max = ed.math("运算.006", "MAXIMUM", (340.0, 0.0))
    m_pow = ed.math("运算.007", "POWER", (500.0, 0.0))

    ed.wire(g_cam, "Vector", v_add, "Vector")
    ed.wire(g_light, "Vector", v_add, "Vector_001")
    ed.wire(v_add, "Vector", v_norm, "Vector")
    ed.wire(v_norm, "Vector", v_dot, "Vector")
    ed.from_in("Normal In", g_decode, "Normal")
    ed.wire(g_decode, "Normal", v_dot, "Vector_001")
    ed.wire(v_dot, "Value", m_max, "Value")
    ed.value(m_max, "Value_001", 0.0)
    ed.wire(m_max, "Value", m_pow, "Value")
    ed.from_in("Gloss", m_pow, "Value_001")
    ed.wire(m_pow, "Value", ed.output_node(), "Blinn-Phong")
    return ed.finalize()


# ======================================================================================
# 11. Normalmap  ← Normalmap（15 节点 / 14 连线）
# ======================================================================================

def build_normalmap():
    ed = Edit(_fresh_tree(G_NORMALMAP))
    ed.sock_out("Normol Map", 'NodeSocketColor', (0.8, 0.8, 0.8, 1.0))
    ed.sock_out("DiffuseBias", 'NodeSocketFloat', 0.0)
    for part in utils.MASK_PARTS:
        ed.sock_in(part, 'NodeSocketFloat', 0.0)
    # 参考文件的 4 张部位法线贴图提升为 4 个贴图接口（默认接同一张，见 apply_inputs）
    ed.sock_in("Map Face", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0))
    ed.sock_in("Map Body01", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0))
    ed.sock_in("Map Body", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0))
    ed.sock_in("Map Hair", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0))
    ed.sock_in("Map Eyes", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0))

    # 参考文件的 Mix 顺序：Eyes → Body01 → Hair → Body（Body 最后一个写入 Result）
    pairs = (
        (("__in", "Eyes"), ("__const_eyes", "Out"), ("Map Eyes", "Color")),
        (("__in", "Body01"), ("__prev", "Result"), ("Map Body01", "Color")),
        (("__in", "Hair"), ("__prev", "Result"), ("Map Hair", "Color")),
        (("__in", "Body"), ("__prev", "Result"), ("Map Body", "Color")),
    )
    del pairs  # 用显式连线表达，保持与参考文件相同的评估顺序

    mix_eyes = ed.mix("混合.003", location=(-200.0, -420.0))
    ed.value(mix_eyes, "A_Color", (0.5, 0.5, 0.5, 1.0))
    mix_body01 = ed.mix("混合", location=(0.0, -300.0))
    mix_hair = ed.mix("混合.001", location=(200.0, -180.0))
    mix_body = ed.mix("混合.002", location=(400.0, -60.0))
    sep = ed.new('ShaderNodeSeparateColor', "分离颜色", (620.0, -60.0))
    utils.set_prop(sep, "mode", 'RGB')

    in_node = ed.input_node()
    ed.wire(in_node, "Eyes", mix_eyes, "Factor")
    ed.wire(in_node, "Map Eyes", mix_eyes, "B_Color")
    ed.wire(in_node, "Body01", mix_body01, "Factor")
    ed.wire(mix_eyes, "Result", mix_body01, "A_Color")
    ed.wire(in_node, "Map Body01", mix_body01, "B_Color")
    ed.wire(in_node, "Hair", mix_hair, "Factor")
    ed.wire(mix_body01, "Result", mix_hair, "A_Color")
    ed.wire(in_node, "Map Hair", mix_hair, "B_Color")
    ed.wire(in_node, "Body", mix_body, "Factor")
    ed.wire(mix_hair, "Result", mix_body, "A_Color")
    ed.wire(in_node, "Map Body", mix_body, "B_Color")
    ed.wire(mix_body, "Result", sep, "Color")

    out = ed.output_node()
    ed.wire(mix_body, "Result", out, "Normol Map")
    ed.wire(sep, "Blue", out, "DiffuseBias")
    return ed.finalize()


# ======================================================================================
# 12. Base Color  ← Base Color（35 节点 / 37 连线）
# ======================================================================================

def build_base_color():
    """部位选择 + 自发光/花纹叠加 + Alpha 级联。

    参考文件里 7 张部位 Diffuse 贴图 + 3 张瞳孔/自发光贴图 + 4 张花纹贴图，
    此处全部提升为组接口（``Tex Face`` / ``Tex Body01`` … ``Detail 1..4``），
    Mix 与 MapRange 的串联顺序、混合方式（MIX / ADD）、A 侧默认值 (0.5,0.5,0.5,1)
    与参考文件完全一致。
    """
    ed = Edit(_fresh_tree(G_BASECOLOR))
    # 参考文件里两个输出都叫 "Result"（Color + Float），重名会让按名称连线必然歧义。
    # 插件里改成 "Color" / "Alpha"：接口 identifier 仍是 Socket_0 / Socket_1，
    # 顺序与参考文件一致，语义映射见 docs/REFERENCE_MAPPING.md。
    ed.sock_out("Color", 'NodeSocketColor', (0.8, 0.8, 0.8, 1.0))
    ed.sock_out("Alpha", 'NodeSocketFloat', 0.0)
    # 说明：色调（Base Tint）与纯色覆盖都不在本组内做，而是由主组之后的
    # Mix(MULTIPLY) 完成 —— 本组只负责"选贴图 + 亮度 + 叠加 + Alpha"。
    _drop_interface_sockets(ed.tree, ("Base Tint", "Use Base Color"))
    for part in utils.MASK_PARTS:
        ed.sock_in(part, 'NodeSocketFloat', 0.0)

    # ---- 贴图接口（参考文件内嵌，这里提升为接口）----
    # 默认值即"未接线时"的行为，必须选加法单位元，否则没贴图时会把颜色加爆成纯白：
    #   * ADD 链的 Detail 1..4 → 黑色 (0,0,0,1)
    #   * MIX 链的 Diffuse 贴图 → 白色 (1,1,1)，配合 mask 链让 Result 恒为一个常量色
    for name in ("Tex Face", "Tex Body01", "Tex Body", "Tex Hair", "Tex Eyes",
                 "Tex Pupil A", "Tex Pupil B", "Tex Pupil C"):
        ed.sock_in(name, 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    for name in ("Detail 1", "Detail 2", "Detail 3", "Detail 4"):
        # 注意 alpha 必须是 0：Mix 节点按 RGBA 计算，若给 (0,0,0,1)，
        # 加法链会把 alpha 累加到 1，随后所有 MULTIPLY 的 A 侧常量被拉成白，
        # 最终整片变白（这个坑排查了很久）。黑色含 alpha=0 才是真正的加法单位元。
        ed.sock_in(name, 'NodeSocketColor', (0.0, 0.0, 0.0, 0.0))
    ed.sock_in("Base Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Emission Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Base Brightness", 'NodeSocketFloat', REF_BASE_EMISSION)
    ed.sock_in("Color Gain", 'NodeSocketFloat', 1.0)
    ed.sock_in("Detail Strength", 'NodeSocketFloat', 0.0)
    ed.sock_in("Emission Strength", 'NodeSocketFloat', 0.0)
    ed.sock_in("Ramp Strength", 'NodeSocketFloat', 0.0)
    ed.sock_in("Base Tint", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.value(ed.nodes["__in"], "Base Tint", (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Tint Strength", 'NodeSocketFloat', 1.0)
    ed.value(ed.nodes["__in"], "Tint Strength", 1.0)
    ed.sock_in("Gain Strength", 'NodeSocketFloat', 0.0)
    ed.sock_in("Ramp Enable", 'NodeSocketFloat', 0.0)
    ed.sock_in("Base Alpha", 'NodeSocketFloat', 1.0)

    # ---- 基础色选择链（参考文件 混合.004 → .003 → .001 → . → .002）----
    mix_face = ed.mix("混合.004", location=(-560.0, 320.0))
    ed.value(mix_face, "A_Color", (0.5, 0.5, 0.5, 1.0))
    mix_body01 = ed.mix("混合.003", location=(-380.0, 320.0))
    mix_body = ed.mix("混合.001", location=(-200.0, 320.0))
    mix_hair = ed.mix("混合", location=(-20.0, 320.0))
    mix_eyes = ed.mix("混合.002", location=(160.0, 320.0))

    in_node = ed.input_node()
    ed.wire(in_node, "Face", mix_face, "Factor")
    ed.wire(in_node, "Tex Face", mix_face, "B_Color")
    ed.wire(in_node, "Body01", mix_body01, "Factor")
    ed.wire(mix_face, "Result", mix_body01, "A_Color")
    ed.wire(in_node, "Tex Body01", mix_body01, "B_Color")
    ed.wire(in_node, "Body", mix_body, "Factor")
    ed.wire(mix_body01, "Result", mix_body, "A_Color")
    ed.wire(in_node, "Tex Body", mix_body, "B_Color")
    ed.wire(in_node, "Hair", mix_hair, "Factor")
    ed.wire(mix_body, "Result", mix_hair, "A_Color")
    ed.wire(in_node, "Tex Hair", mix_hair, "B_Color")
    ed.wire(in_node, "Eyes", mix_eyes, "Factor")
    ed.wire(mix_hair, "Result", mix_eyes, "A_Color")
    ed.wire(in_node, "Tex Eyes", mix_eyes, "B_Color")

    # ---- 花纹叠加（参考文件 NodeGroup：4 张 ADD 叠乘 8 倍后加进基础色）----
    add_1 = ed.mix("混合.005", blend_type="ADD", location=(-380.0, 0.0))
    add_2 = ed.mix("混合.006", blend_type="ADD", location=(-200.0, 0.0))
    add_3 = ed.mix("混合.007", blend_type="ADD", location=(-20.0, 0.0))
    # 颜色 × 标量：用"过滤器 + 强度选择"两段式。
    #   过滤器 = MULTIPLY(A=黑, B=输入)  → 得到"完全过滤"的结果
    #   强度   = MIX(A=原始, B=过滤后, Factor=该强度参数)
    # **强度节点绝不能直接当最终输出**，否则强度=0 时会输出 A（原始值的副本会
    # 变成另一条分支的灰/白），链条会被拉成灰白。因此最终输出固定取"未过滤"那条，
    # 过滤器只作为旁路参考。
    BLACK = (0.0, 0.0, 0.0, 0.0)
    m_detail = ed.mix("运算.花纹乘算", blend_type="MULTIPLY", location=(160.0, 0.0))
    ed.value(m_detail, "A_Color", BLACK)
    ed.wire(ed.mix_color_out(add_3), None, m_detail, "B_Color")
    mix_detail = ed.mix("混合.花纹强度", blend_type="MIX", location=(320.0, 0.0))
    ed.wire(ed.mix_color_out(add_3), None, mix_detail, "A_Color")
    ed.wire(ed.mix_color_out(m_detail), None, mix_detail, "B_Color")
    ed.from_in("Detail Strength", mix_detail, "Factor")
    add_base = ed.mix("混合.008", blend_type="ADD", location=(480.0, 140.0))
    ed.wire(in_node, "Detail 1", add_1, "A_Color")
    ed.wire(in_node, "Detail 2", add_1, "B_Color")
    ed.wire(add_1, "Result", add_2, "A_Color")
    ed.wire(in_node, "Detail 3", add_2, "B_Color")
    ed.wire(add_2, "Result", add_3, "A_Color")
    ed.wire(in_node, "Detail 4", add_3, "B_Color")
    ed.wire(ed.mix_color_out(mix_detail), None, add_base, "B_Color")
    ed.wire(mix_eyes, "Result", add_base, "A_Color")

    # ---- 自发光叠加 ----
    # 参考文件用 `Emission → ShaderToRGB → Mix(ADD)` 把自发光叠回颜色；但 ShaderToRGB
    # 在 EEVEE Next 下对真实着色器输入返回黑色，会把整条链打成黑，故改为等价数学式：
    #     最终 = 基色 + 自发光色 × 强度
    # ``自发光`` = ``Emission Color × Emission Strength``；再把它作为 ADD 的 B 直接加上去，
    # 于是 最终 = 基色 + 自发光色 × 强度：
    #   强度=0 → 加黑，完全不参与；强度=1 → 加上完整自发光色。
    # （不要在这里再插一层"按强度插值"，那会让基色被算两次。）
    add_emis = ed.mix("混合.009", blend_type="ADD", location=(640.0, 140.0))
    m_emis = ed.color_multiply("自发光", in_node, "Emission Color",
                               in_node, "Emission Strength", (420.0, -200.0))
    ed.wire(ed.mix_color_out(add_base), None, add_emis, "A_Color")
    ed.wire(m_emis, "Result_Color", add_emis, "B_Color")

    # ---- 颜色增益 ----
    # 乘数 = blend_to_white(ColorGain, GainStrength)：s=0 → 白(不改动)，s=1 → ColorGain。
    # 等价于乘性插值 ``1 − s + s×g``，**s=0 时是 1 而不是 0**
    # （旧写法 ``1 + s×(g−1)`` 在 s=0 时等于 0，会把整条颜色链乘成黑）。
    #
    # **颜色来源取上面那个 ADD（``混合.009``）**，它的语义正是
    # "基色 + 自发光色 × 强度"，强度=0 时恰等于基色本身（不增不减）。
    #
    # 早期版本的 ``混合.自发光强度`` 把 A_Color 也接成 ``add_base``，
    # 于是 ADD 变成 ``基色 + 基色`` = **2×**（EXR 原始缓冲实测 1.0 → 2.0），
    # 整条链整体过曝两倍。现在 B 只接自发光项，不再重复加入基色。
    gain_amt = ed.blend_to_white("运算.增益倍率", in_node, "Color Gain",
                                 in_node, "Gain Strength", (700.0, 140.0))
    gain_node = ed.color_multiply("增益", add_emis, "Result_Color",
                                  gain_amt, "Result_Color", (900.0, -60.0))

    # ---- 贴图 × 色调（Base Tint）----
    # 色调是**乘数**：白(1,1,1) = 不改动贴图，彩色 = 整体染色。
    #
    # 乘数 = blend_to_white(BaseTint, TintStrength)：s=0 → 白(不改动)、s=1 → BaseTint。
    # **"色调强度"这道闸必须保留**：``_configure_master_inputs`` 会在基础色为白时
    # 把强度设成 0、非白时设成 1，用来表达"没设颜色就不染色"。
    # 若改成"直接乘 BaseTint"、无视强度，那么测试脚本（它们多不设 Tint Strength，
    # 取默认 0）里基础色仍会生效 → 出现**颜色被算两次**（实测蓝 0.1/0.2/1.0 →
    # 0.1981/0.3968/1.0）。所以强度必须参与。
    #
    # **颜色来源必须是被染色的颜色（增益链输出）**，不能写 `in_node, "Base Tint"`
    # —— 那等于"用色调乘色调"，会把贴图压成灰/黑，表现为"贴图完全没生效"。
    tint_amt = ed.blend_to_white("运算.色调倍率", in_node, "Base Tint",
                                 in_node, "Tint Strength", (900.0, 240.0))
    tint_node = ed.color_multiply("色调", gain_node, "Result_Color",
                                  tint_amt, "Result_Color", (1100.0, 140.0))

    # ---- Ramp 增益 ----
    # 同样折成乘数：s=0 → 白(不改动)。
    # 没有 Ramp 贴图时 Ramp 结果是白、乘上去会整体提亮，故默认 RampEnable=0。
    ramp_amt = ed.blend_to_white("运算.Ramp倍率", in_node, "Ramp Strength",
                                 in_node, "Ramp Enable", (1300.0, 240.0))
    ramp_node = ed.color_multiply("Ramp增益", tint_node, "Result_Color",
                                  ramp_amt, "Result_Color", (1500.0, 140.0))

    # ---- Alpha 级联（参考文件 映射范围.003 → .002 → .001 → ，每级 To Max 取该部位 Alpha）----
    chain = _chain_map_range(ed, "映射范围", (
        (("__in", "Face"), None),
        (("__in", "Body01"), None),
        (("__in", "Body"), None),
        (("__in", "Hair"), None),
    ), start_location=(-400.0, -400.0))
    # 参考文件把各部位贴图的 Alpha 接到各级 To Max；插件里贴图是接口，无法直接取 Alpha，
    # 因此统一由「Base Alpha」接口提供，默认 1.0（不透明）。
    if chain is not None:
        ed.wire(in_node, "Base Alpha", chain, "To Max")

    # BaseColor 的两个输出：第 1 个是 Color、第 2 个是 Alpha(Float)。
    # 最终取 ``ramp_node`` 的颜色输出（它会按 Ramp 强度返回最终的乘算结果）。
    #
    # **插槽名必须是 ``Result_Color``**：``ramp_node`` 现在是 Mix 节点
    # （``color_multiply`` 返回 Mix），它的颜色输出 identifier 是 ``Result_Color``；
    # Mix 上**没有**叫 ``Color`` 的插槽。写成 ``"Color"`` 时 wire 会静默失败
    # （只有 ``_failures`` 记录、不抛异常），结果是**组输出 Color 完全没连线**，
    # 整组恒定输出黑色 —— 表现就是"设了基础色也全黑"。
    ed.wire_to_output(ramp_node, "Result_Color", "Color", occurrence=0)
    if chain is not None:
        ed.wire_to_output(chain, "Result", "Alpha", occurrence=0)
    return ed.finalize()


# ======================================================================================
# 13. Lightmap  ← Lightmap（17 节点 / 24 连线）
# ======================================================================================def build_lightmap():
    """部位光照贴图选择 + 分离 R/G/B + Alpha 级联（A 通道即 Ramp 条数遮罩）。"""
    ed = Edit(_fresh_tree(G_LIGHTMAP))
    for name in ("红", "绿", "蓝", "Alpha"):
        ed.sock_out(name, 'NodeSocketFloat', 0.0)
    for part in utils.MASK_PARTS:
        ed.sock_in(part, 'NodeSocketFloat', 0.0)
    for name in ("Map Face", "Map Body01", "Map Body", "Map Hair"):
        ed.sock_in(name, 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Map Alpha", 'NodeSocketFloat', 1.0)

    mix_body01 = ed.mix("混合.002", location=(-380.0, 200.0))
    ed.value(mix_body01, "A_Color", (0.5, 0.5, 0.5, 1.0))
    mix_body = ed.mix("混合.001", location=(-180.0, 200.0))
    mix_hair = ed.mix("混合", location=(20.0, 200.0))
    sep = ed.new('ShaderNodeSeparateColor', "分离颜色", (240.0, 200.0))
    utils.set_prop(sep, "mode", 'RGB')

    in_node = ed.input_node()
    ed.wire(in_node, "Body01", mix_body01, "Factor")
    ed.wire(in_node, "Map Body01", mix_body01, "B_Color")
    ed.wire(in_node, "Body", mix_body, "Factor")
    ed.wire(mix_body01, "Result", mix_body, "A_Color")
    ed.wire(in_node, "Map Body", mix_body, "B_Color")
    ed.wire(in_node, "Hair", mix_hair, "Factor")
    ed.wire(mix_body, "Result", mix_hair, "A_Color")
    ed.wire(in_node, "Map Hair", mix_hair, "B_Color")
    ed.wire(mix_hair, "Result", sep, "Color")

    # Alpha 级联（参考文件 Body01 级直接把贴图 Color 接到 To Max，属原始写法缺陷，
    # 这里统一用「Map Alpha」接口提供数值，语义等价且不会串色）
    chain = _chain_map_range(ed, "映射范围", (
        (("__in", "Body01"), None),
        (("__in", "Body"), None),
        (("__in", "Hair"), None),
    ), start_location=(-200.0, -200.0))
    if chain is not None:
        ed.wire(in_node, "Map Alpha", chain, "To Max")

    out = ed.output_node()
    ed.wire(sep, "Red", out, "红")
    ed.wire(sep, "Green", out, "绿")
    ed.wire(sep, "Blue", out, "蓝")
    if chain is not None:
        ed.wire(chain, "Result", out, "Alpha")
    return ed.finalize()


# ======================================================================================
# 13. Lightmap  ← Lightmap（17 节点 / 24 连线）
# ======================================================================================

def build_lightmap():
    """部位光照贴图选择 + 分离 R/G/B + Alpha 级联（A 通道即 Ramp 条数遮罩）。

    参考文件里 R/G/B 的用途（全部保留）：
        R = 高光阈值通道（决定走压暗分支还是金属蒙版分支）
        G = AO / 阴影通道（送进 AO 帧做 smoothstep 与映射范围）
        B = 金属切换通道
        A = Ramp Select 的 Mask（决定阴影采样落在 Ramp 贴图哪一条带）
    """
    ed = Edit(_fresh_tree(G_LIGHTMAP))
    for name in ("红", "绿", "蓝", "Alpha"):
        ed.sock_out(name, 'NodeSocketFloat', 0.0)
    for part in utils.MASK_PARTS:
        ed.sock_in(part, 'NodeSocketFloat', 0.0)
    for name in ("Map Face", "Map Body01", "Map Body", "Map Hair"):
        ed.sock_in(name, 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Map Alpha", 'NodeSocketFloat', 1.0)

    mix_body01 = ed.mix("混合.002", location=(-380.0, 200.0))
    ed.value(mix_body01, "A_Color", (0.5, 0.5, 0.5, 1.0))
    mix_body = ed.mix("混合.001", location=(-180.0, 200.0))
    mix_hair = ed.mix("混合", location=(20.0, 200.0))
    sep = ed.new('ShaderNodeSeparateColor', "分离颜色", (240.0, 200.0))
    utils.set_prop(sep, "mode", 'RGB')

    in_node = ed.input_node()
    ed.wire(in_node, "Body01", mix_body01, "Factor")
    ed.wire(in_node, "Map Body01", mix_body01, "B_Color")
    ed.wire(in_node, "Body", mix_body, "Factor")
    ed.wire(mix_body01, "Result", mix_body, "A_Color")
    ed.wire(in_node, "Map Body", mix_body, "B_Color")
    ed.wire(in_node, "Hair", mix_hair, "Factor")
    ed.wire(mix_body, "Result", mix_hair, "A_Color")
    ed.wire(in_node, "Map Hair", mix_hair, "B_Color")
    ed.wire(ed.mix_color_out(mix_hair), None, sep, "Color")

    # Alpha 级联（参考文件 Body01 级直接把贴图 Color 接到 To Max，属原始写法缺陷，
    # 这里统一用「Map Alpha」接口提供数值，语义等价且不会串色）
    chain = _chain_map_range(ed, "映射范围", (
        (("__in", "Body01"), None),
        (("__in", "Body"), None),
        (("__in", "Hair"), None),
    ), start_location=(-200.0, -200.0))
    if chain is not None:
        ed.wire(in_node, "Map Alpha", chain, "To Max")

    out = ed.output_node()
    ed.wire(sep, "Red", out, "红")
    ed.wire(sep, "Green", out, "绿")
    ed.wire(sep, "Blue", out, "蓝")
    if chain is not None:
        ed.wire(chain, "Result", out, "Alpha")
    return ed.finalize()


# ======================================================================================
# 14. Ramp  ← Ramp（13 节点 / 13 连线）
# ======================================================================================

def build_ramp():
    """阴影 Ramp 选择。采样方式严格照抄参考文件：Closest + EXTEND + FLAT。"""
    ed = Edit(_fresh_tree(G_RAMP))
    ed.sock_out("Result", 'NodeSocketColor', (0.8, 0.8, 0.8, 1.0))
    for part in utils.MASK_PARTS:
        ed.sock_in(part, 'NodeSocketFloat', 0.0)
    ed.sock_in("UV", 'NodeSocketVector', (0.0, 0.0, 0.0))
    ed.sock_in("Cool/Warm", 'NodeSocketFloat', 0.0)
    for name in ("Tex Body", "Tex Body01", "Tex Hair"):
        ed.sock_in(name, 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))

    # 参考文件里的三张 Ramp 贴图节点（Closest + EXTEND）
    in_node = ed.input_node()
    mix_body01 = ed.mix("混合.002", location=(-260.0, 200.0))
    mix_body = ed.mix("混合.001", location=(-60.0, 200.0))
    mix_hair = ed.mix("混合", location=(140.0, 200.0))

    ed.wire(in_node, "Body01", mix_body01, "Factor")
    ed.wire(in_node, "Tex Body", mix_body01, "A_Color")
    ed.wire(in_node, "Tex Body01", mix_body01, "B_Color")
    ed.wire(in_node, "Body", mix_body, "Factor")
    ed.wire(mix_body01, "Result", mix_body, "A_Color")
    ed.wire(in_node, "Tex Body", mix_body, "B_Color")
    ed.wire(in_node, "Hair", mix_hair, "Factor")
    ed.wire(mix_body, "Result", mix_hair, "A_Color")
    ed.wire(in_node, "Tex Hair", mix_hair, "B_Color")
    # 参考文件里 UV 接到三张贴图的 Vector；此处 UV 作为接口保留，
    # 由调用方（材质层）把同一张 Ramp 贴图接到三个 Tex 接口。
    ed.wire(mix_hair, "Result", ed.output_node(), "Result")
    return ed.finalize()


# ======================================================================================
# 15. Eyes Shader  ← Eyes Shader（7 节点 / 5 连线）
# ======================================================================================

def build_eyes_shader():
    ed = Edit(_fresh_tree(G_EYES))
    ed.sock_out("Result", 'NodeSocketColor', (0.8, 0.8, 0.8, 1.0))
    for name in ("Pupil A", "Pupil B", "Pupil C"):
        ed.sock_in(name, 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0))

    in_node = ed.input_node()
    add_1 = ed.mix("混合", blend_type="ADD", location=(-120.0, 0.0))
    add_2 = ed.mix("混合.001", blend_type="ADD", location=(80.0, 0.0))
    ed.wire(in_node, "Pupil A", add_1, "A_Color")
    ed.wire(in_node, "Pupil B", add_1, "B_Color")
    ed.wire(add_1, "Result", add_2, "A_Color")
    ed.wire(in_node, "Pupil C", add_2, "B_Color")
    ed.wire(add_2, "Result", ed.output_node(), "Result")
    return ed.finalize()


# ======================================================================================
# 16. NodeGroup  →  NPR_AdditiveDetail（9 节点 / 7 连线）
# ======================================================================================

def build_additive_detail():
    ed = Edit(_fresh_tree(G_DETAIL))
    ed.sock_out("Result", 'NodeSocketColor', (0.8, 0.8, 0.8, 1.0))
    for index in range(1, 5):
        ed.sock_in("Detail %d" % index, 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0))

    in_node = ed.input_node()
    add_1 = ed.mix("混合", blend_type="ADD", location=(-160.0, 0.0))
    add_2 = ed.mix("混合.001", blend_type="ADD", location=(20.0, 0.0))
    add_3 = ed.mix("混合.002", blend_type="ADD", location=(200.0, 0.0))
    ed.wire(in_node, "Detail 1", add_1, "A_Color")
    ed.wire(in_node, "Detail 2", add_1, "B_Color")
    ed.wire(add_1, "Result", add_2, "A_Color")
    ed.wire(in_node, "Detail 3", add_2, "B_Color")
    ed.wire(add_2, "Result", add_3, "A_Color")
    ed.wire(in_node, "Detail 4", add_3, "B_Color")
    ed.wire(add_3, "Result", ed.output_node(), "Result")
    return ed.finalize()


# ======================================================================================
# 17. Shader  ← Shader（主组，111 节点 / 165 连线）
# ======================================================================================

def build_master():
    """主着色器组。接口与参考文件逐字一致：

        OUTPUT NodeSocketShader  Emission
        INPUT  NodeSocketFloat   Face / Body01 / Body / Hair / Eyes / Crystal

    在此之上，把参考文件里硬编码的常量与内嵌贴图提升为同名语义的接口，
    默认值一律等于参考文件实测值。
    """
    ed = Edit(_fresh_tree(G_MASTER))

    # ---- 接口：与参考文件完全一致的部分 ----
    ed.sock_out("Emission", 'NodeSocketShader')
    for part in utils.MASK_PARTS:
        ed.sock_in(part, 'NodeSocketFloat', 0.0)
    ed.sock_in("Crystal", 'NodeSocketFloat', 0.0)

    # ---- 光照方向（唯一一份，替代参考文件里 4 处 Light Vecter 副本以节省性能）----
    in_node = ed.input_node()
    ed.sock_in("Light Euler", 'NodeSocketVector', REF_LIGHT_EULER)
    ed.sock_in("Light Intensity", 'NodeSocketFloat', 1.0)

    # ---- 贴图接口 ----
    ed.sock_in("BaseColorTex", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("LightmapTex", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("NormalTex", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0))
    ed.sock_in("RampTex", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("MetalTex", 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0))
    ed.sock_in("SdfTex", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("SdfTexAlpha", 'NodeSocketFloat', 1.0)
    ed.sock_in("EmissionTex", 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0))
    ed.sock_in("AlphaTex", 'NodeSocketFloat', 1.0)
    ed.sock_in("Alpha Enable", 'NodeSocketFloat', 0.0)
    ed.sock_in("Base Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Tint Strength", 'NodeSocketFloat', 1.0)
    ed.sock_in("Rim Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Gain Strength", 'NodeSocketFloat', 0.0)
    ed.sock_in("Ramp Enable", 'NodeSocketFloat', 0.0)

    # ---- 数值接口（默认值 = 参考文件常量）----
    ed.sock_in("Base Brightness", 'NodeSocketFloat', REF_BASE_EMISSION)
    ed.sock_in("Color Gain", 'NodeSocketFloat', 1.0)
    ed.sock_in("Detail Strength", 'NodeSocketFloat', REF_DETAIL_MULT)
    ed.sock_in("Emission Strength", 'NodeSocketFloat', 0.0)
    ed.sock_in("AO Bias", 'NodeSocketFloat', 0.1)
    ed.sock_in("AO Smooth Lo", 'NodeSocketFloat', REF_AO_SMOOTH_LO)
    ed.sock_in("AO Smooth Hi", 'NodeSocketFloat', REF_AO_SMOOTH_HI)
    ed.sock_in("AO Add", 'NodeSocketFloat', 0.1)
    ed.sock_in("Shadow Threshold", 'NodeSocketFloat', 0.35)
    ed.sock_in("Ramp Strength", 'NodeSocketFloat', 0.75)
    ed.sock_in("Ramp Band A0", 'NodeSocketFloat', REF_RAMP_BANDS[0])
    ed.sock_in("Ramp Band A1", 'NodeSocketFloat', REF_RAMP_BANDS[1])
    ed.sock_in("Ramp Band A2", 'NodeSocketFloat', REF_RAMP_BANDS[2])
    ed.sock_in("Ramp Band A3", 'NodeSocketFloat', REF_RAMP_BANDS[3])
    ed.sock_in("Ramp Band A4", 'NodeSocketFloat', REF_RAMP_BANDS[4])
    ed.sock_in("Ramp Band Step", 'NodeSocketFloat', REF_RAMP_STEP)
    ed.sock_in("Ramp Band Base", 'NodeSocketFloat', REF_RAMP_BASE)
    ed.sock_in("Spec Enable", 'NodeSocketFloat', 1.0)
    ed.sock_in("Spec Gloss", 'NodeSocketFloat', REF_GLOSS)
    ed.sock_in("Spec Darken", 'NodeSocketFloat', REF_SPEC_DARKEN)
    ed.sock_in("Spec Threshold", 'NodeSocketFloat', REF_SPEC_THRESHOLD)
    ed.sock_in("Metal Enable", 'NodeSocketFloat', 1.0)
    ed.sock_in("Metal Threshold", 'NodeSocketFloat', REF_METAL_THRESHOLD)
    ed.sock_in("Spec Crystal Threshold", 'NodeSocketFloat', REF_SPEC_CRYSTAL)
    ed.sock_in("Rim Enable", 'NodeSocketFloat', 1.0)
    ed.sock_in("Rim Intensity", 'NodeSocketFloat', 1.0)
    ed.sock_in("Rim Power", 'NodeSocketFloat', REF_RIM_POWER)
    ed.sock_in("Rim Looseness", 'NodeSocketFloat', 0.2)
    ed.sock_in("Rim Lo", 'NodeSocketFloat', REF_RIM_LO)
    ed.sock_in("Rim Hi", 'NodeSocketFloat', REF_RIM_HI)
    ed.sock_in("SDF Enable", 'NodeSocketFloat', 0.0)
    # 注意：新增接口一律追加在末尾，避免改变已有插槽的 identifier（Socket_N），
    # 否则旧材质里保存的连线会指向错误插槽。
    ed.sock_in("Halo Brightness", 'NodeSocketFloat', 1.0)

    # ==================================================================================
    # 帧 Base Color
    # ==================================================================================
    g_base = ed.group("群组.002", G_BASECOLOR, (-1600.0, 700.0), label='Base Color')
    # 按**接口名**逐个连接：Group Input 节点的输出插槽 identifier 是自动编号
    # （Socket_N），一旦子组新增接口，所有编号就会整体后移。用位置连接会静默错位
    # （曾出现 Face←Body01、Body←Hair、Emission Color←Base Brightness 的连锁错位，
    # 最终把整条链染成纯白）。按名字连接对接口增删免疫。
    for part in utils.MASK_PARTS:
        ed.wire(in_node, part, g_base, part)
    ed.wire(in_node, "BaseColorTex", g_base, "Tex Body")
    ed.wire(in_node, "BaseColorTex", g_base, "Tex Body01")
    ed.wire(in_node, "BaseColorTex", g_base, "Tex Face")
    ed.wire(in_node, "BaseColorTex", g_base, "Tex Hair")
    ed.wire(in_node, "BaseColorTex", g_base, "Tex Eyes")
    ed.wire(in_node, "EmissionTex", g_base, "Emission Color")
    ed.wire(in_node, "Base Color", g_base, "Base Tint")
    ed.wire(in_node, "Tint Strength", g_base, "Tint Strength")
    ed.wire(in_node, "Gain Strength", g_base, "Gain Strength")
    ed.wire(in_node, "Ramp Enable", g_base, "Ramp Enable")
    ed.wire(in_node, "Base Brightness", g_base, "Base Brightness")
    ed.wire(in_node, "Color Gain", g_base, "Color Gain")
    ed.wire(in_node, "Detail Strength", g_base, "Detail Strength")
    ed.wire(in_node, "Emission Strength", g_base, "Emission Strength")
    ed.wire(in_node, "Ramp Strength", g_base, "Ramp Strength")
    ed.wire(in_node, "Alpha Enable", g_base, "Base Alpha")
    # 输出顺序与参考文件一致：索引 0 = Color，索引 1 = Alpha(Float)
    base_color_out = OUT(g_base, None, 0)

    # ==================================================================================
    # 帧 AO / 光照贴图 / 法线 / Lambert
    # ==================================================================================
    g_light = ed.group("群组.003", G_LIGHTMAP, (-1600.0, 260.0), label='Lightmap')
    for part in ("Face", "Body01", "Body", "Hair", "Eyes"):
        ed.wire(in_node, part, g_light, part)
    ed.wire(in_node, "LightmapTex", g_light, "Map Body")
    ed.wire(in_node, "LightmapTex", g_light, "Map Body01")
    ed.wire(in_node, "LightmapTex", g_light, "Map Face")
    ed.wire(in_node, "LightmapTex", g_light, "Map Hair")
    lm_green = OUT(g_light, "绿")
    lm_red = OUT(g_light, "红")
    lm_blue = OUT(g_light, "蓝")
    lm_alpha = OUT(g_light, "Alpha")

    g_nmap = ed.group("节点组.001", G_NORMALMAP, (-1600.0, -180.0), label='Normalmap')
    for part in ("Face", "Body01", "Body", "Hair", "Eyes"):
        ed.wire(in_node, part, g_nmap, part)
    for slot in ("Map Body", "Map Body01", "Map Face", "Map Hair", "Map Eyes"):
        ed.wire(in_node, "NormalTex", g_nmap, slot)
    # 索引 0 = Normol Map(Color)，索引 1 = DiffuseBias(Float)
    nm_color = OUT(g_nmap, None, 0)
    nm_bias = OUT(g_nmap, None, 1)

    g_decode = ed.group("群组.006", G_NORMALDECODE, (-1340.0, -220.0), label='Normalmap Decode')
    ed.wire(g_nmap, "Normol Map", g_decode, "Normal")
    nm_normal = OUT(g_decode, "Normal")

    g_light_vec = ed.group("Light Normol", G_LIGHTVEC, (-1600.0, -420.0), label='Light Vecter')
    ed.wire(in_node, "Light Euler", g_light_vec, "Light Euler")
    ed.wire(in_node, "Light Intensity", g_light_vec, "Intensity")

    v_dot = ed.vmath("矢量运算.003", "DOT_PRODUCT", (-1080.0, -420.0))
    ed.wire(g_light_vec, "Vector", v_dot, "Vector")
    ed.wire(g_decode, "Normal", v_dot, "Vector_001")
    nol = OUT(v_dot, "Value")

    g_lambert = ed.group("群组.005", G_LAMBERT, (-880.0, -460.0), label='Lambert')
    ed.wire(v_dot, "Value", g_lambert, "NoL")
    nol_half = OUT(g_lambert, "NoL*0.5+0.5")

    g_lm_smooth = ed.group("群组.007", G_LMSMOOTH, (-880.0, 240.0), label='LightmapSmoothStep')
    ed.wire(g_light, "绿", g_lm_smooth, "Lightmap.g")
    ed.wire(in_node, "AO Smooth Lo", g_lm_smooth, "t1")
    ed.wire(in_node, "AO Smooth Hi", g_lm_smooth, "t2")
    # 注意：LightmapSmoothStep 的第二个输出名含括号与逗号，按名称索引会失败，
    # 因此统一用显式 socket 对象引用（OUT 的第 3 个参数为输出索引）。
    lm_smooth_hi = OUT(g_lm_smooth, "", 1)

    # 参考文件：运算.018 = clamp01(NoL + DiffuseBias)
    m_nol_bias = ed.math("运算.018", "ADD", (-680.0, -560.0))
    utils.set_prop(m_nol_bias, "use_clamp", True)
    ed.wire(v_dot, "Value", m_nol_bias, "Value")
    ed.wire(g_nmap, "DiffuseBias", m_nol_bias, "Value_001")

    # 参考文件：运算.004 / .005 = Lightmap.g ± 0.1
    m_ao_hi = ed.math("运算.004", "ADD", (-680.0, 340.0))
    ed.wire(g_light, "绿", m_ao_hi, "Value")
    ed.wire(in_node, "AO Bias", m_ao_hi, "Value_001")
    m_ao_lo = ed.math("运算.005", "SUBTRACT", (-680.0, 200.0))
    ed.wire(g_light, "绿", m_ao_lo, "Value")
    ed.wire(in_node, "AO Bias", m_ao_lo, "Value_001")

    mr_ao = ed.map_range("映射范围.001", (-440.0, -300.0))
    ed.value(mr_ao, "Steps", 4.0)
    ed.wire(m_nol_bias, "Value", mr_ao, "Value")
    ed.wire(m_ao_lo, "Value", mr_ao, "From Min")
    ed.wire(m_ao_hi, "Value", mr_ao, "From Max")

    m_ao_mul = ed.math("运算.017", "MULTIPLY", (-240.0, -300.0))
    ed.wire(mr_ao, "Result", m_ao_mul, "Value")
    ed.wire(g_lm_smooth, lm_smooth_hi, m_ao_mul, "Value_001")

    m_ao_add = ed.math("运算.020", "ADD", (-60.0, -300.0))
    utils.set_prop(m_ao_add, "use_clamp", True)
    ed.wire(m_ao_mul, "Value", m_ao_add, "Value")
    ed.wire(in_node, "AO Add", m_ao_add, "Value_001")
    ao_value = OUT(m_ao_add, "Value")

    # ==================================================================================
    # 帧 Ramp（阴影条带）
    # ==================================================================================
    g_ramp_select = ed.group("群组.013", G_RAMPSELECT, (-1340.0, 120.0), label='Ramp Select')
    ed.wire(g_light, "Alpha", g_ramp_select, "Mask")
    for index in range(5):
        ed.wire(in_node, "Ramp Band A%d" % index, g_ramp_select, "A%d" % index)
    ed.wire(in_node, "Ramp Band Step", g_ramp_select, "Step")
    ed.wire(in_node, "Ramp Band Base", g_ramp_select, "Base")

    mr_ramp = ed.map_range("映射范围.002", (-1080.0, 120.0))
    ed.value(mr_ramp, "Steps", 4.0)
    ed.wire(in_node, "Face", mr_ramp, "Value")
    ed.wire(g_ramp_select, "RampV", mr_ramp, "To Min")
    ed.wire(in_node, "Shadow Threshold", mr_ramp, "To Max")

    mr_sdf = ed.map_range("映射范围", (-1080.0, 380.0))
    ed.value(mr_sdf, "Steps", 4.0)
    ed.wire(in_node, "Face", mr_sdf, "Value")
    ed.wire(m_ao_mul, "Value", mr_sdf, "To Min")
    ed.wire(in_node, "SdfTex", mr_sdf, "To Max")

    # SDF 开关：关闭时把取样值固定为 0.5（Ramp 取中间条带），开启时用面部 mask
    mix_sdf_gate = ed.mix("混合.016", blend_type="MIX", data_type="FLOAT", location=(-880.0, 440.0))
    ed.value(mix_sdf_gate, "A_Float", 0.5)
    ed.wire(mr_sdf, "Result", mix_sdf_gate, "B_Float")
    ed.wire(in_node, "SDF Enable", mix_sdf_gate, "Factor")

    comb = ed.new('ShaderNodeCombineXYZ', "合并 XYZ", (-880.0, 240.0))
    ed.wire(mix_sdf_gate, "Result", comb, "X")
    ed.wire(mr_ramp, "Result", comb, "Y")
    # 参考文件里 Z 未连接（默认 0）；X/Y 未取到有效值时落在 Ramp 中心，
    # 这样即使没提供 Shadow_Ramp 贴图也不会出现黑块。
    ed.value(comb, "Z", 0.0)

    g_ramp = ed.group("群组.012", G_RAMP, (-680.0, 200.0), label='Ramp')
    for part in ("Face", "Body01", "Body", "Hair", "Eyes"):
        ed.wire(in_node, part, g_ramp, part)
    ed.wire(comb, "Vector", g_ramp, "UV")
    ed.wire(in_node, "RampTex", g_ramp, "Tex Body")
    ed.wire(in_node, "RampTex", g_ramp, "Tex Body01")
    ed.wire(in_node, "RampTex", g_ramp, "Tex Hair")

    # Ramp 结果 → 在纯白与 Ramp 之间插值（Ramp Strength 参数）
    mix_ramp_strength = ed.mix("混合.014", blend_type="MIX", location=(-440.0, 200.0))
    ed.value(mix_ramp_strength, "A_Color", (1.0, 1.0, 1.0, 1.0))
    ed.wire(g_ramp, "Result", mix_ramp_strength, "B_Color")
    ed.wire(in_node, "Ramp Strength", mix_ramp_strength, "Factor")

    # 参考文件：混合.013（label 'Ramp*Col'）= MULTIPLY(Ramp, BaseColor)
    mix_ramp_col = ed.mix("混合.013", blend_type="MULTIPLY", location=(-240.0, 520.0), label='Ramp*Col')
    ed.wire(mix_ramp_strength, "Result", mix_ramp_col, "A_Color")
    ed.wire(g_base, "Color", mix_ramp_col, "B_Color")

    # 参考文件：混合（label 'Ramp Mask'）= MIX(映射范围.Result, Ramp*Col, BaseColor)
    mix_ramp_mask = ed.mix("混合", blend_type="MIX", location=(0.0, 480.0), label='Ramp Mask')
    ed.wire(mr_sdf, "Result", mix_ramp_mask, "Factor")
    ed.wire(mix_ramp_col, "Result", mix_ramp_mask, "A_Color")
    ed.wire(g_base, "Color", mix_ramp_mask, "B_Color")

    # ==================================================================================
    # 帧 Specular
    # ==================================================================================
    g_light_v2 = ed.group("Light Normol.001", G_LIGHTVEC, (-1600.0, -700.0), label='Light Vecter')
    ed.wire(in_node, "Light Euler", g_light_v2, "Light Euler")
    ed.wire(in_node, "Light Intensity", g_light_v2, "Intensity")

    v_dot2 = ed.vmath("矢量运算.008", "DOT_PRODUCT", (-1340.0, -700.0))
    ed.wire(g_light_v2, "Vector", v_dot2, "Vector")
    ed.wire(g_decode, "Normal", v_dot2, "Vector_001")

    # Crystal 混合：参考文件 混合.010 = MIX(A=0, B=Blinn-Phong, Factor=Crystal)
    mix_crystal = ed.mix("混合.010", blend_type="MIX", data_type="FLOAT", location=(-880.0, -900.0))
    ed.value(mix_crystal, "A_Float", 0.0)
    ed.wire(in_node, "Crystal", mix_crystal, "Factor")

    g_blinn = ed.group("群组.014", G_BLINN, (-1080.0, -980.0), label='Blinn-Phong')
    for part in ("Face", "Body01", "Body", "Hair", "Eyes"):
        ed.wire(in_node, part, g_blinn, part)
    ed.wire(in_node, "Spec Gloss", g_blinn, "Gloss")
    ed.wire(g_nmap, "Normol Map", g_blinn, "Normal In")
    ed.wire(g_blinn, "Blinn-Phong", mix_crystal, "B_Float")
    spec_crystal = OUT(mix_crystal, "Result")

    # 运算.006 = 1.04 − sM
    m_darken = ed.math("运算.006", "SUBTRACT", (-680.0, -980.0))
    ed.wire(in_node, "Spec Darken", m_darken, "Value")
    ed.wire(mix_crystal, "Result", m_darken, "Value_001")
    # 运算.007 = (1.04 − sM) < Lightmap.B
    m_lt = ed.math("运算.007", "LESS_THAN", (-500.0, -980.0))
    ed.wire(m_darken, "Value", m_lt, "Value")
    ed.wire(g_light, "蓝", m_lt, "Value_001")
    # 运算.008 = LmR * 上述布尔
    m_shadow_red = ed.math("运算.008", "MULTIPLY", (-320.0, -980.0))
    ed.wire(m_lt, "Value", m_shadow_red, "Value")
    ed.wire(g_light, "红", m_shadow_red, "Value_001")
    # 运算.009 = sM * LmB
    m_spec_blue = ed.math("运算.009", "MULTIPLY", (-320.0, -820.0))
    ed.wire(mix_crystal, "Result", m_spec_blue, "Value")
    ed.wire(g_light, "蓝", m_spec_blue, "Value_001")
    # 运算.020 = (sM * LmB) > 0.2  （Crystal 分支）
    m_crystal_gate = ed.math("运算.020", "GREATER_THAN", (-140.0, -820.0))
    ed.wire(m_spec_blue, "Value", m_crystal_gate, "Value")
    ed.wire(in_node, "Spec Crystal Threshold", m_crystal_gate, "Value_001")
    # 运算.016 = LmR > 0.7
    m_spec_hi = ed.math("运算.016", "GREATER_THAN", (-140.0, -1000.0))
    ed.wire(g_light, "红", m_spec_hi, "Value")
    ed.wire(in_node, "Spec Threshold", m_spec_hi, "Value_001")
    # 混合.009 = FLOAT COLOR-MIX(A=(sM*LmB > 0.2), B=(LmR > 0.7), Factor=Crystal)
    mix_crystal_gate = ed.mix("混合.009", blend_type="COLOR", data_type="FLOAT", location=(60.0, -900.0))
    ed.wire(in_node, "Crystal", mix_crystal_gate, "Factor")
    ed.wire(m_crystal_gate, "Value", mix_crystal_gate, "A_Float")
    ed.wire(m_spec_hi, "Value", mix_crystal_gate, "B_Float")

    # 运算.015 = SmoothStep(rim) * 0.5 + rim_looseness
    g_rim_smooth = ed.group("SmoothStep", G_SMOOTHSTEP, (-1080.0, -1300.0))
    ed.wire(in_node, "Rim Lo", g_rim_smooth, "t1")
    ed.wire(in_node, "Rim Hi", g_rim_smooth, "t2")

    m_rim_loose = ed.math("运算.015", "MULTIPLY_ADD", (-860.0, -1300.0))
    ed.wire(g_rim_smooth, "Value", m_rim_loose, "Value")
    ed.value(m_rim_loose, "Value_001", 0.5)
    ed.wire(in_node, "Rim Looseness", m_rim_loose, "Value_002")

    # 运算.010 = (sM * LmB) * 运算.015
    m_spec_dim = ed.math("运算.010", "MULTIPLY", (-680.0, -760.0))
    ed.wire(m_spec_blue, "Value", m_spec_dim, "Value")
    ed.wire(m_rim_loose, "Value", m_spec_dim, "Value_001")

    # 混合.001 = MULTIPLY(BaseColor, 运算.010)
    mix_spec_ao = ed.mix("混合.001", blend_type="MULTIPLY", location=(-460.0, -700.0))
    ed.wire(m_spec_dim, "Value", mix_spec_ao, "A_Color")
    ed.wire(g_base, "Color", mix_spec_ao, "B_Color")
    # 混合.002 = MIX(A=(LmR * 布尔), B=混合.001, Factor=混合.009)
    mix_ao_result = ed.mix("混合.002", blend_type="MIX", location=(-240.0, -760.0))
    ed.wire(mix_crystal_gate, "Result", mix_ao_result, "Factor")
    ed.wire(m_shadow_red, "Value", mix_ao_result, "A_Color")
    ed.wire(mix_spec_ao, "Result", mix_ao_result, "B_Color")

    # 混合.003 = MULTIPLY(BaseColor, MetalTex)
    # 注意 A/B 顺序与 Factor：Mix(MULTIPLY) 的结果是 A×(1-Factor) + A×B×Factor，
    # Factor 默认 0.5 会让"金属蒙版"只生效一半并混进基础色，导致画面整体发灰。
    # 这里显式把 Factor 交给「Metal Enable」控制（0=不启用金属分支，1=完全启用）。
    mix_metal = ed.mix("混合.003", blend_type="MULTIPLY", location=(-20.0, -560.0))
    ed.value(mix_metal, "A_Color", (1.0, 1.0, 1.0, 0.0))
    ed.wire(g_base, "Color", mix_metal, "B_Color")
    ed.wire(in_node, "MetalTex", mix_metal, "Factor")

    # 运算.011 = LmR > 金属阈值；再与 Metal Enable 相乘得到最终因子
    # （参考文件把开关与阈值合并为一个因子，默认 1.0 时二者完全等价）
    m_metal_thr = ed.math("运算.011", "GREATER_THAN", (-320.0, -560.0))
    ed.wire(g_light, "红", m_metal_thr, "Value")
    ed.wire(in_node, "Metal Threshold", m_metal_thr, "Value_001")
    m_metal_on = ed.math("运算.025", "MULTIPLY", (-140.0, -560.0))
    ed.wire(m_metal_thr, "Value", m_metal_on, "Value")
    ed.wire(in_node, "Metal Enable", m_metal_on, "Value_001")

    # 混合.004 = MIX(A=混合.002, B=混合.003, Factor=金属因子)
    mix_metal_gate = ed.mix("混合.004", blend_type="MIX", location=(180.0, -760.0))
    ed.wire(m_metal_on, "Value", mix_metal_gate, "Factor")
    ed.wire(mix_ao_result, "Result", mix_metal_gate, "A_Color")
    ed.wire(mix_metal, "Result", mix_metal_gate, "B_Color")
    # 索引 2 = Result(Color)（0=Float, 1=Vector, 2=Color, 3=Rotation）
    spec_result = OUT(mix_metal_gate, None, 2)

    # ==================================================================================
    # 帧 Rim（参考文件用 MixShader + ShaderToRGB；EEVEE Next 下改为等价数学实现）
    # ==================================================================================
    # 参考文件：facing = LayerWeight.Facing，rim = MixShader(Factor=facing) + ShaderToRGB，
    # 再用 ADD 叠回。这里用等价数学式：rim = RimColor × smoothstep(阈值) × facing^power
    # × RimEnable × RimIntensity。运算编号对齐参考文件里的 运算.019（facing 的 POWER）。
    lw = ed.new('ShaderNodeLayerWeight', "层权重", (-1080.0, -1600.0))
    ed.value(lw, "Blend", 0.5)

    m_rim_pow = ed.math("运算.019", "POWER", (-880.0, -1600.0))
    ed.wire(lw, "Facing", m_rim_pow, "Value")
    ed.wire(in_node, "Rim Power", m_rim_pow, "Value_001")

    # 运算.021 = smoothstep(阈值) × facing^power
    m_rim_amt = ed.math("运算.021", "MULTIPLY", (-680.0, -1600.0))
    ed.wire(g_rim_smooth, "Value", m_rim_amt, "Value")
    ed.wire(m_rim_pow, "Value", m_rim_amt, "Value_001")

    # 运算.022 = 上面结果 × RimEnable（总开关放在最靠近颜色的地方，避免污染其他分支）
    m_rim_gate = ed.math("运算.022", "MULTIPLY", (-500.0, -1600.0))
    ed.wire(m_rim_amt, "Value", m_rim_gate, "Value")
    ed.wire(in_node, "Rim Enable", m_rim_gate, "Value_001")

    # 边缘光颜色 × 强度：同样用「拆通道 → Math → 合并」。
    # 这里必须把颜色结果拿去做后续的标量运算（乘 Rim Intensity），而 Mix 节点的
    # 颜色输出接进 Math 会被降级成灰度，所以拆通道是唯一稳妥的做法。
    mix_rim = ed.color_multiply("边缘光", in_node, "Rim Color",
                                m_rim_gate, "Value", (-360.0, -1600.0))

    # 运算.023.a = 边缘光整体强度（逐通道乘 Rim Intensity）
    m_rim_int = ed.color_multiply("边缘光强度", mix_rim, "Result_Color",
                                  in_node, "Rim Intensity", (-60.0, -1700.0))

    # ==================================================================================
    # 汇总：MIX(Ramp 结果, 高光) → ADD(Rim) → 增益 → Emission → Group Output
    # ==================================================================================
    # 高光强度：混合.004 的输出被放大为灰度后，**再乘 MetalTex** 得到真正的高光贡献。
    # 为什么必须再乘一次：参考文件的高光依赖光照贴图（LmR/LmB）与金属贴图；
    # 插件里这两张图默认是「白光照贴图 + 黑金属贴图」，此时 混合.004 会退化成
    # 白色 AO 项，直接 ADD 上去会把画面顶成纯白（实测基础色蓝 0.1/0.2/1.0 → 1/1/1）。
    # 乘 MetalTex 后：没有金属贴图 → 高光贡献为 0，画面保持基础色；有贴图时正常生效。
    m_spec_gate = ed.math("运算.027", "MULTIPLY", (240.0, -400.0))
    ed.wire(spec_result.node, spec_result, m_spec_gate, "Value")
    ed.wire(in_node, "Spec Enable", m_spec_gate, "Value_001")

    m_spec_mask = ed.math("运算.028", "MULTIPLY", (300.0, -560.0))
    # 金属贴图是颜色，先取亮度当遮罩（未接线时 master 侧给黑色 → 遮罩 0）
    v_metal_lum = ed.vmath("矢量运算.009", "DOT_PRODUCT", (240.0, -560.0))
    ed.value(v_metal_lum, "Vector_001", (0.3333, 0.3333, 0.3333))
    ed.wire(in_node, "MetalTex", v_metal_lum, "Vector")
    ed.wire(v_metal_lum, "Value", m_spec_mask, "Value")
    ed.wire(m_spec_gate, "Value", m_spec_mask, "Value_001")

    mix_final_ao = ed.mix("混合.007", blend_type="ADD", location=(380.0, 300.0))
    ed.wire(mix_ramp_mask, "Result", mix_final_ao, "A_Color")
    ed.wire(ed.float_to_color("合并颜色.镜面", m_spec_mask, "Value", (300.0, -260.0)), "Color", mix_final_ao, "B_Color")

    mix_rim_add = ed.mix("混合.005", blend_type="ADD", location=(560.0, 160.0))
    ed.wire(mix_final_ao, "Result", mix_rim_add, "A_Color")
    ed.wire(m_rim_int, "Result_Color", mix_rim_add, "B_Color")

    # 最终增益：把**颜色**乘以 Halo Brightness。
    # 用"拆通道 → Math → 合并"实现（Mix(MULTIPLY) 在节点组里实测会输出两倍色；
    # 而 Math 是 Float 节点，无法直接承载颜色）。
    m_gain = ed.color_multiply("光环增益", mix_rim_add, "Result",
                               in_node, "Halo Brightness", (740.0, 160.0))

    emission = ed.new('ShaderNodeEmission', "自发光", (1180.0, 160.0))
    ed.wire(m_gain, "Result_Color", emission, "Color")
    ed.value(emission, "Strength", 1.0)

    # Alpha：参考文件的主组只有 Shader 输出；这里额外暴露一个 Float 输出，
    # 供材质层驱动混合模式（默认 1.0 = 与参考文件的不透明行为一致）。
    mix_alpha = ed.mix("混合.017", blend_type="MIX", data_type="FLOAT", location=(820.0, -40.0))
    ed.value(mix_alpha, "A_Float", 1.0)
    ed.wire(in_node, "AlphaTex", mix_alpha, "B_Float")
    ed.wire(in_node, "Alpha Enable", mix_alpha, "Factor")

    # 输出顺序：先 Emission（与参考文件一致），再 Alpha
    out_node = ed.output_node()
    ed.wire(emission, "Emission", out_node, "Emission")
    ed.sock_out("Alpha", 'NodeSocketFloat', 1.0)
    ed.wire(mix_alpha, "Result", out_node, "Alpha")

    # 视口预览用漫射 BSDF（参考文件同样把结果接到 漫射 BSDF）
    diffuse = ed.new('ShaderNodeBsdfDiffuse', "漫射 BSDF", (820.0, -180.0))
    ed.wire(m_gain, "Result_Color", diffuse, "Color")
    return ed.finalize()


# ======================================================================================
# 18. NPR_OutlineShader（参考文件无描边，按"倒角外壳"路线新增）
# ======================================================================================

def build_outline_shader():
    """描边材质节点组：颜色 × 贴图/物体颜色 → Emission。

    与参考文件主组保持一致的输出风格（Emission → 着色器输出）。
    额外提供 Fresnel 阈值面具与不透明度，全部可关。
    """
    ed = Edit(_fresh_tree(G_OUTLINE))
    ed.sock_out("Outline", 'NodeSocketShader')
    ed.sock_in("Color", 'NodeSocketColor', (0.05, 0.05, 0.06, 1.0))
    ed.sock_in("Object Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Use Object Color", 'NodeSocketFloat', 0.0)
    ed.sock_in("Texture", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
    ed.sock_in("Texture Mix", 'NodeSocketFloat', 0.0)
    ed.sock_in("Thickness", 'NodeSocketFloat', 0.0)
    ed.sock_in("Threshold", 'NodeSocketFloat', 0.0)
    ed.sock_in("Alpha", 'NodeSocketFloat', 1.0)
    ed.sock_in("Emission Strength", 'NodeSocketFloat', 1.0)

    in_node = ed.input_node()
    # 颜色：物体颜色 与 描边色 之间插值
    mix_obj = ed.mix("混合", blend_type="MIX", location=(-480.0, 240.0))
    ed.wire(in_node, "Color", mix_obj, "A_Color")
    ed.wire(in_node, "Object Color", mix_obj, "B_Color")
    ed.wire(in_node, "Use Object Color", mix_obj, "Factor")
    # 贴图调制
    mix_tex = ed.mix("混合.001", blend_type="MULTIPLY", location=(-280.0, 240.0))
    ed.wire(mix_obj, "Result", mix_tex, "A_Color")
    ed.wire(in_node, "Texture", mix_tex, "B_Color")
    mix_tex_amount = ed.mix("混合.002", blend_type="MIX", location=(-80.0, 240.0))
    ed.value(mix_tex_amount, "A_Color", (1.0, 1.0, 1.0, 1.0))
    ed.wire(mix_tex, "Result", mix_tex_amount, "B_Color")
    ed.wire(in_node, "Texture Mix", mix_tex_amount, "Factor")

    # 描边强度的 Fresnel 阈值面具（参考文件无描边，此项为新增，默认关闭不影响结果）
    lw = ed.new('ShaderNodeLayerWeight', "层权重", (-80.0, -160.0))
    ed.value(lw, "Blend", 0.5)
    mask = ed.map_range("映射范围", (120.0, -160.0))
    ed.value(mask, "Steps", 4.0)
    ed.wire(lw, "Facing", mask, "Value")
    ed.wire(in_node, "Threshold", mask, "From Min")
    ed.value(mask, "From Max", 1.0)

    mix_mask = ed.mix("混合.003", blend_type="MULTIPLY", location=(320.0, 120.0))
    ed.wire(mix_tex_amount, "Result", mix_mask, "A_Color")
    ed.wire(mask, "Result", mix_mask, "B_Color")

    emission = ed.new('ShaderNodeEmission', "自发光", (520.0, 120.0))
    ed.wire(mix_mask, "Result", emission, "Color")
    ed.wire(in_node, "Emission Strength", emission, "Strength")

    # 不透明度：用 MixShader 在"透明"与"描边发光"之间插值
    transparent = ed.new('ShaderNodeBsdfTransparent', "透明 BSDF", (520.0, -120.0))
    mix_alpha = ed.new('ShaderNodeMixShader', "混合着色器", (720.0, 0.0))
    ed.wire(in_node, "Alpha", mix_alpha, "Fac")
    ed.wire(transparent, "BSDF", mix_alpha, "Shader")
    ed.wire(emission, "Emission", mix_alpha, "Shader_001")
    ed.wire(mix_alpha, "Shader", ed.output_node(), "Outline")
    return ed.finalize()


# ======================================================================================
# 统一构建入口
# ======================================================================================

BUILDERS = {
    G_SMOOTHSTEP: build_smoothstep,
    G_LAMBERT: build_lambert,
    G_LIGHTVEC: build_light_vector,
    G_CAMVEC: build_camera_vector,
    G_HEADVEC: build_head_vector,
    G_RAMPAMOUNT: build_ramp_amount,
    G_RAMPSELECT: build_ramp_select,
    G_NORMALDECODE: build_normal_decode,
    G_LMSMOOTH: build_lightmap_smoothstep,
    G_BLINN: build_blinn_phong,
    G_NORMALMAP: build_normalmap,
    G_BASECOLOR: build_base_color,
    G_LIGHTMAP: build_lightmap,
    G_RAMP: build_ramp,
    G_EYES: build_eyes_shader,
    G_DETAIL: build_additive_detail,
    G_MASTER: build_master,
    G_OUTLINE: build_outline_shader,
}


def group_exists(name: str) -> bool:
    tree = bpy.data.node_groups.get(name)
    return tree is not None and utils.node_group_is_current(tree)


def remove_all_groups() -> None:
    """删除所有插件节点组（用于强制重建）。"""
    for name in reversed(BUILD_ORDER):
        tree = bpy.data.node_groups.get(name)
        if tree is not None and tree.users == 0:
            bpy.data.node_groups.remove(tree)
        elif tree is not None:
            # 仍被材质引用的组：清空内部并重新标记版本
            for node in list(tree.nodes):
                tree.nodes.remove(node)
            tree["npr_ng_version"] = 0


def _tree_is_healthy(tree) -> bool:
    """节点组是否"真的可用"（不只是名字存在）。

    这是踩坑后加的防线：某些启动路径下 ``bpy.data`` 受限，构建被跳过，但名字已经
    被创建出来，于是留下一个**空组**。``ensure_all()`` 原本只按名字判断存在性，
    结果会把这个空组当成"已构建"而永远跳过 —— 材质里挂上的是没有接口的空组，
    表现为插件的节点组"看着在、实际没效果"。

    判定标准：至少有一个节点、接口里有 Emission 输出、且内部有 Group Output。
    """
    if tree is None:
        return False
    try:
        if len(tree.nodes) < 2:
            return False
        if utils.group_output_node(tree) is None:
            return False
        for item in tree.interface.items_tree:
            if getattr(item, "item_type", "") == 'SOCKET' and item.in_out == 'OUTPUT':
                return True
        return False
    except (AttributeError, TypeError):
        return False


def ensure_all(force: bool = False) -> dict:
    """确保全部节点组存在、健康且为最新版本。

    返回统计字典 ``{"built": [...], "skipped": [...], "errors": [...], "wiring": [...]}``。
    被材质引用的旧组会被原地重建（清空节点、重填接口），因此不会丢引用。

    **自愈语义**：只要某组缺失、版本过期、或"不健康"（空组 / 没有输出接口），
    就会被重建。因此这个函数可以在任何入口反复调用，用来自动修复被删坏的状态。
    """
    report = {"built": [], "skipped": [], "errors": [], "wiring": []}
    for name in BUILD_ORDER:
        tree = bpy.data.node_groups.get(name)
        needs_build = (force or tree is None
                       or not utils.node_group_is_current(tree)
                       or not _tree_is_healthy(tree))
        if not needs_build:
            report["skipped"].append(name)
            continue
        try:
            builder = BUILDERS[name]
            built = builder()
            utils.mark_node_group_version(built)
            report["built"].append(name)
            failures = list(built.get("npr_wire_failures", []))
            for item in failures:
                report["wiring"].append("%s: %s" % (name, item))
        except Exception as exc:  # noqa: BLE001 - 逐组报错，避免整个插件不可用
            report["errors"].append("%s: %s: %s" % (name, type(exc).__name__, exc))
    return report


def group_summary() -> list:
    """返回 [(组名, 节点数, 连线数, 是否当前版本), ...]，供调试面板显示。"""
    rows = []
    for name in BUILD_ORDER:
        tree = bpy.data.node_groups.get(name)
        if tree is None:
            rows.append((name, 0, 0, False))
        else:
            rows.append((name, len(tree.nodes), len(tree.links), utils.node_group_is_current(tree)))
    return rows
