"""把渲染结果转成 ASCII 图，直接在终端里"看"到画面。

用法：
    blender -b --factory-startup --python npr_shader/tools_ascii_view.py -- <图片路径> [更多路径...]
"""
import os
import sys

import bpy

paths = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not paths:
    # 默认看仓库根目录下 render_out 里最新的一张图
    default_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "render_out")
    if os.path.isdir(default_dir):
        candidates = [os.path.join(default_dir, n) for n in os.listdir(default_dir)
                      if n.lower().endswith((".png", ".jpg", ".jpeg"))]
        candidates.sort(key=os.path.getmtime, reverse=True)
        if candidates:
            paths = [candidates[0]]
if not paths:
    print("没有可显示的图片。用法：-- <图片路径>")
    sys.exit(1)

CHARS = " .:-=+*#%@"


def show(path, cols=48, rows=24):
    img = bpy.data.images.load(path)
    width, height = img.size
    px = list(img.pixels)
    print("\n=== %s  (%dx%d) ===" % (path.split("\\")[-1], width, height))
    for row in range(rows):
        line = []
        for col in range(cols):
            x = int(col * (width - 1) / max(1, cols - 1))
            y = int((rows - 1 - row) * (height - 1) / max(1, rows - 1))
            index = (y * width + x) * 4
            lum = 0.2126 * px[index] + 0.7152 * px[index + 1] + 0.0722 * px[index + 2]
            lum = max(0.0, min(1.0, lum))
            line.append(CHARS[min(len(CHARS) - 1, int(lum * len(CHARS)))])
        print("   |" + "".join(line) + "|")
    print("   center linear RGB = (%.3f, %.3f, %.3f)" % tuple(
        px[((height // 2) * width + width // 2) * 4 + k] for k in range(3)))
    bpy.data.images.remove(img)


for path in paths:
    show(path)
print("\nASCII_DONE")
