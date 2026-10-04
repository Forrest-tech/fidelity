# -*- coding: utf-8 -*-
"""CSS 对比度守卫：守住「文字看不见」这类只有肉眼才会发现的 bug。

## 为什么需要
2026-10-05 用户报「白色字体看不到」。根因是 CSS 层叠：
`.trow.sel`（白字 + 深蓝底）与 `.tree-file.picked`（浅蓝底）**特异性相同**，
后者在样式表里定义得更靠后，于是背景变浅、白字留下 → 白字白底。
截图能看出来，但**没有任何测试会失败** —— 所以把它变成可计算的断言。

## 做法
从 styles.css 里取出选择器的实际声明，按 CSS 层叠顺序算出最终生效的
background/color，再算 WCAG 对比度。低于阈值即失败。

普通正文要求 >= 4.5:1（WCAG AA）；大号/粗体文字要求 >= 3:1。

用法：python scripts/check_contrast.py
"""
import os
import re
import sys

WEB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web", "src"))
CSS = os.path.join(WEB, "styles.css")


def read_css():
    with open(CSS, "r", encoding="utf-8") as f:
        return f.read()


def css_vars(src):
    """解析 :root { --name: value } 里的自定义属性。"""
    root = re.search(r":root\s*\{(.*?)\}", src, re.S)
    out = {}
    if root:
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", root.group(1)):
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def resolve(v, variables, depth=0):
    """把 var(--x) 解析成字面值（支持嵌套，最多 5 层）。"""
    if depth > 5 or not v:
        return v
    m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", v.strip())
    if m and m.group(1) in variables:
        return resolve(variables[m.group(1)], variables, depth + 1)
    return v.strip()


def to_rgb(color):
    """#rgb / #rrggbb / rgb() / rgba() -> (r,g,b)；不支持返回 None。"""
    if not color:
        return None
    c = color.strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) == 6:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return None
    m = re.match(r"rgba?\(([^)]+)\)", c)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        try:
            return tuple(int(float(p)) for p in parts[:3])
        except ValueError:
            return None
    named = {"white": (255, 255, 255), "black": (0, 0, 0)}
    return named.get(c.lower())


def luminance(rgb):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    a, b = luminance(fg), luminance(bg)
    hi, lo = (a, b) if a > b else (b, a)
    return (hi + 0.05) / (lo + 0.05)


def rules(src):
    """按出现顺序抽出所有 `选择器 { 声明 }`，顺序即层叠顺序（后写的赢）。"""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", src):
        sel = m.group(1).strip()
        if sel.startswith("@") or not sel:
            continue
        body = m.group(2)
        decls = {}
        for d in re.finditer(r"([\w-]+)\s*:\s*([^;]+);", body):
            decls[d.group(1).strip()] = d.group(2).strip()
        if decls:
            out.append((sel, decls))
    return out


def effective(rs, selector, prop, variables, inherited=None):
    """模拟层叠：找出该选择器最终生效的 prop 值。"""
    val = None
    for sel, decls in rs:
        if selector in [s.strip() for s in sel.split(",")]:
            if prop in decls:
                val = decls[prop]
    if val is None:
        return inherited
    return resolve(val, variables)


CHECKS = [
    # (选择器, 说明, 最小对比度)
    (".trow.sel", "目录树选中行（白字深蓝底）", 4.5),
    (".tree-file.sel.picked", "目录树选中+勾选（用户报「白字看不到」的那个状态）", 4.5),
    ("button.primary", "主按钮（白字蓝底）", 4.5),
    (".vbtn.ok.sel", "裁决-一致 选中态", 4.5),
    (".vbtn.diff.sel", "裁决-差异大 选中态", 4.5),
    (".vbtn.rej.sel", "裁决-不接受 选中态", 4.5),
    (".langsw button.on", "语言切换选中态", 4.5),
    (".score-pill.good", "自动分-高", 4.5),
    (".score-pill.mid", "自动分-中", 4.5),
    (".score-pill.bad", "自动分-低", 4.5),
    (".badge.trusted", "状态徽标-可信", 4.5),
    (".badge.need_review", "状态徽标-待复核", 4.5),
    (".badge.diff_big", "状态徽标-差异大", 4.5),
]

FAILS = []
COUNT = [0]


def main():
    src = read_css()
    variables = css_vars(src)
    rs = rules(src)
    print("CSS 变量 %d 个，规则 %d 条\n" % (len(variables), len(rs)))

    for selector, label, minimum in CHECKS:
        COUNT[0] += 1
        color = effective(rs, selector, "color", variables)
        # 背景：先找本选择器，再回退到 body 的背景
        bg = effective(rs, selector, "background", variables)
        if bg is None or bg == "transparent":
            bg = effective(rs, "body", "background", variables, inherited="rgb(255,255,255)")
        fg_rgb, bg_rgb = to_rgb(color), to_rgb(bg)
        if fg_rgb is None or bg_rgb is None:
            FAILS.append("%s：无法解析颜色 fg=%r bg=%r" % (label, color, bg))
            print("  FAIL %-46s fg=%s bg=%s（无法解析）" % (label, color, bg))
            continue
        ratio = contrast(fg_rgb, bg_rgb)
        good = ratio >= minimum
        if not good:
            FAILS.append("%s：对比度 %.2f < %.1f" % (label, ratio, minimum))
        print("  %s %-46s %.2f:1 (要求 %.1f)  fg=%s bg=%s"
              % ("ok  " if good else "FAIL", label, ratio, minimum, color, bg))

    # 反向防线：确认「选中+勾选」确实不再是浅底白字（原始 bug 的特征）
    COUNT[0] += 1
    bg_sel_picked = to_rgb(effective(rs, ".tree-file.sel.picked", "background", variables))
    if bg_sel_picked and luminance(bg_sel_picked) > 0.6:
        FAILS.append(".sel.picked 背景过浅（%s），会重现白字白底" % (bg_sel_picked,))
        print("  FAIL .sel.picked 背景过浅：%s" % (bg_sel_picked,))
    else:
        print("  ok   .sel.picked 背景为深色，白字可读  bg=%s" % (bg_sel_picked,))

    print("\n" + "=" * 56)
    if FAILS:
        print("对比度检查失败 %d / %d：" % (len(FAILS), COUNT[0]))
        for f in FAILS:
            print("  - " + f)
        return 1
    print("对比度检查全部通过：%d / %d" % (COUNT[0], COUNT[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
