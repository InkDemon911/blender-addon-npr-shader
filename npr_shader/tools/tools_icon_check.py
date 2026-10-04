"""校验插件里用到的每一个 icon 名称是否是 Blender 的合法枚举值。

**为什么需要这个检查**：icon 名写错时，面板 `draw()` 会抛
``TypeError: UILayout.label(): error with keyword argument "icon" - enum "X" not found in (...)``。
要命的是 Blender 会把**整个图标枚举（约 1000 项）**打进错误信息里，
一次就能产生 40+ MB 的日志，而且报错发生在 draw() 里 —— 用户看到的是
"面板打不开"，很难自己定位。

合法名称表固化在 :mod:`tools_icon_names`，因此本脚本**不需要 Blender 也能跑**，
可以放进 CI。

用法：
    python npr_shader/tools_icon_check.py            # 纯静态检查
    blender -b --factory-startup --python npr_shader/tools_icon_check.py   # 也可在 Blender 里跑
"""
import os
import re
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    from tools_icon_names import VALID_ICONS, BLENDER_VERSION
except ImportError:  # 作为包内模块被导入时
    from .tools_icon_names import VALID_ICONS, BLENDER_VERSION

#: 正则版（用于 tokenize 失败的兜底）：匹配 icon='NAME' / icon="NAME"
_ICON_RE_QUOTED = re.compile(r"""(?<![A-Za-z0-9_])icon\s*=\s*['"]([A-Za-z0-9_]+)['"]""")

#: token 版：tokenize 之后字符串的引号已被剥离，所以匹配裸的 ``icon = NAME``。
#: 必须挡住两种误报：
#:   * ``icons = {...}`` —— 变量赋值，用词边界排除
#:   * ``if icons``      —— 条件表达式（没有等号），靠"等号后紧跟标识符"排除
_ICON_RE_TOKENS = re.compile(r"""(?<![A-Za-z0-9_])icon\s*=\s*([A-Za-z_][A-Za-z0-9_]*)""")


def _collect_string_values(tokens, start):
    """从 ``icon=`` 右边的 token 开始，收集这个"参数值表达式"里的所有字符串字面量。

    需要覆盖几种真实写法（都在 ui.py 里出现过）：

    * ``icon='MATERIAL'``                              → 直接就是名字
    * ``icon='A' if cond else 'B'``                    → 三元，两个都要校验
    * ``icon=icons.get(item.level, 'INFO')``           → 动态取值，把兜底串也校验
    * ``icon=("A" if x else "B")``                     → 带括号

    停止条件：遇到**同层或更浅层**的逗号 / 右括号，说明这个参数值结束了。
    """
    depth = 0
    values = []
    for tok in tokens[start:]:
        text = tok.string
        if tok.type == tokenize.OP:
            if text in "([{":
                depth += 1
            elif text in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif text == "," and depth == 0:
                break
        elif tok.type == tokenize.STRING:
            values.append(text)
        elif tok.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            break
    return values


def _collect_dict_values(tokens, start):
    """只收集字典字面量里的**值**字符串（键通常是日志级别之类的非 icon 名）。

    形如 ``{'INFO': 'INFO', 'WARN': 'ERROR', 'ERROR': 'CANCEL'}``：
    键是 ``INFO``/``WARN``/``ERROR``（日志级别），值是真正上屏的 icon。
    早期版本把键也一起收集，导致 ``WARN`` 被误报成非法 icon。
    """
    depth = 0
    values = []
    expect_value = False          # 下一个字符串是"值"
    for tok in tokens[start:]:
        text = tok.string
        if tok.type == tokenize.OP:
            if text in "([{":
                depth += 1
            elif text in ")]}":
                if depth == 0:
                    break
                depth -= 1
                if depth == 0:
                    break          # 字典字面量结束
            elif text == ":":
                expect_value = True
            elif text == ",":
                expect_value = False
        elif tok.type == tokenize.STRING and expect_value:
            values.append(text)
            expect_value = False   # 一个值只取一次
        elif tok.type in (tokenize.NEWLINE, tokenize.ENDMARKER) and depth == 0:
            break
    return values


def _strip_quotes(raw):
    """去掉字符串字面量的引号与常见前缀。"""
    literal = raw.strip()
    while literal[:1] in ("r", "b", "f", "u") and literal[1:2] in ("'", '"'):
        literal = literal[1:]
    return literal.strip("'\"")


def scan(package_dir):
    """扫描包目录下所有 .py，返回 {icon 名: [出现位置, ...]}。

    **为什么用 tokenize 而不是正则**：需要同时做到两件事 ——
    剔除"文档字符串 / 注释里的示例"（本文件自己的 docstring 里就有 ``icon=...``），
    同时保留 ``icon='A' if c else 'B'`` 这类**动态表达式里的字面量**。
    早期版本试过两种偷懒办法都不行：
      * "行内 icon 前面是否出现过引号" → 把 ``text="x", icon='Y'`` 误判成字符串，漏掉 90% 用法
      * 纯正则 ``icon\\s*=\\s*(\\w+)``  → 误报 ``icons = {...}``（变量）和 ``if icons``（条件）
    正确做法是按 token 解析参数值表达式。解析失败的文件退回"带引号正则"扫描。
    """
    usages = {}
    #: 被当作 icon 来源的变量名（如 ``icons``），第二遍要把它们的字典值也校验
    dict_names = set()
    for root, _dirs, files in os.walk(package_dir):
        if "__pycache__" in root:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, os.path.dirname(package_dir))

            try:
                with open(path, "rb") as handle:
                    tokens = [t for t in tokenize.tokenize(handle.readline)
                              if t.type not in (tokenize.COMMENT, tokenize.NL,
                                                tokenize.INDENT, tokenize.DEDENT)]
            except (tokenize.TokenError, SyntaxError, IndentationError):
                tokens = None

            if tokens is None:
                # 兜底：带引号的正则（宁可多报，不可漏报）
                with open(path, encoding="utf-8") as handle:
                    for lineno, line in enumerate(handle, 1):
                        for match in _ICON_RE_QUOTED.finditer(line):
                            usages.setdefault(match.group(1), []).append(
                                "%s:%d" % (rel, lineno))
                continue

            for index, tok in enumerate(tokens):
                if tok.type != tokenize.NAME or tok.string != "icon":
                    continue
                # icon 应当是个关键字参数名：前一个 token 必须是 ( 或 ,
                prev = tokens[index - 1] if index > 0 else None
                if prev is None or prev.type != tokenize.OP or prev.string not in ("(", ","):
                    continue
                # 下一个必须是 =
                nxt = tokens[index + 1] if index + 1 < len(tokens) else None
                if nxt is None or nxt.type != tokenize.OP or nxt.string != "=":
                    continue
                # eval-string 里的引号会被 tokenize 剥掉，这里对 STRING token 手工补回
                for raw in _collect_string_values(tokens, index + 2):
                    literal = raw.strip()
                    if literal.startswith(("r'", 'r"', "b'", 'b"', "f'", 'f"')):
                        literal = literal[2:]
                    literal = literal.strip("'\"")
                    if literal:
                        usages.setdefault(literal, []).append("%s:%d" % (rel, tok.start[0]))

                # 动态取值：``icon=icons.get(...)`` —— 真正上屏的是**字典的值**，
                # 光校验兜底串（'INFO'）不够，必须把那个字典也找出来一起校验。
                value_tok = tokens[index + 2] if index + 2 < len(tokens) else None
                if value_tok is not None and value_tok.type == tokenize.NAME:
                    dict_names.add(value_tok.string)

    # 第二遍：把被用作 icon 来源的字典里的字符串值也纳入校验
    if dict_names:
        for root, _dirs, files in os.walk(package_dir):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, os.path.dirname(package_dir))
                try:
                    with open(path, "rb") as handle:
                        toks = [t for t in tokenize.tokenize(handle.readline)
                                if t.type not in (tokenize.COMMENT, tokenize.NL,
                                                  tokenize.INDENT, tokenize.DEDENT)]
                except (tokenize.TokenError, SyntaxError, IndentationError):
                    continue
                for i, tok in enumerate(toks):
                    if tok.type != tokenize.NAME or tok.string not in dict_names:
                        continue
                    nxt = toks[i + 1] if i + 1 < len(toks) else None
                    if nxt is None or nxt.type != tokenize.OP or nxt.string != "=":
                        continue
                    # 只收集这个字典字面量里的**值**（键是日志级别之类的非 icon 名）
                    for raw in _collect_dict_values(toks, i + 2):
                        literal = _strip_quotes(raw)
                        if literal:
                            usages.setdefault(literal, []).append(
                                "%s:%d (icon 字典 %s)" % (rel, tok.start[0], tok.string))
    return usages


def suggest(icon, icons):
    """给非法名找几个相近的合法名。"""
    stem = icon.rstrip("0123456789_")
    prefix = stem[:8]
    candidates = [c for c in icons if c.startswith(prefix) or prefix.startswith(c[:8])]
    return sorted(candidates)[:6]


def main():
    package_dir = os.path.dirname(HERE)          # npr_shader/
    if not os.path.isfile(os.path.join(package_dir, "__init__.py")):
        package_dir = HERE                        # 直接在插件目录里跑
    if not os.path.isfile(os.path.join(package_dir, "__init__.py")):
        package_dir = os.path.dirname(HERE)

    print("=" * 68)
    print("icon 名称校验（对照 Blender %s 的 %d 个合法图标）"
          % (BLENDER_VERSION, len(VALID_ICONS)))
    print("扫描目录: %s" % package_dir)
    print("=" * 68)

    usages = scan(package_dir)
    print("源码里共用到 %d 个不同的 icon 名称" % len(usages))

    invalid = {icon: places for icon, places in usages.items() if icon not in VALID_ICONS}

    if not invalid:
        print("\n全部合法 ✓")
        print("DONE")
        return 0

    print("\n!! 非法 icon（%d 个）：" % len(invalid))
    for icon in sorted(invalid):
        print("   %-26s 出现在 %s" % (icon, ", ".join(invalid[icon])))
        hints = suggest(icon, VALID_ICONS)
        print("   %-26s 建议改为: %s" % ("", ", ".join(hints) or "（无明显相近项）"))

    print("\n这些名字会让对应面板的 draw() 抛 TypeError，必须修正。")
    print("DONE")
    return 1


if __name__ == "__main__":
    sys.exit(main())
