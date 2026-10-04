# -*- coding: utf-8 -*-
"""CAD 文本提取（.dxf 原生 / .dwg 经转换）。

价值（用户 2026-10-04 拍板）：DWG 图纸提取的是图签、技术说明、尺寸标注文字，
零散短句但有合规价值；提取结果进入对比流程，但初始标「待人工确认」。

DWG→DXF 转换器探测顺序（全部免安装/免提权，注册表式可插拔）：
  1. LibreDWG 的 dwg2dxf.exe（GNU，官方提供 win64 便携 zip，随仓库 tools/ 携带）
       命令行：dwg2dxf -o <out.dxf> <in.dwg>
  2. ODA File Converter（行业标配 freeware，需安装到 Program Files）
       命令行：ODAFileConverter <inDir> <outDir> <ver> <type> <recursive> <audit> [filter]
  3. PATH 中的其他 dwg2dxf（libdxfrw 构建，命令行 dwg2dxf <in> <out>）
  都没有 → 返回 None，路由层标「需人工决定」，用户装好转换器后重跑即自动生效。
"""
import glob
import os
import subprocess
import tempfile

# dwg 版本太老或损坏时给转换器的超时
_DWG_CONV_TIMEOUT = 180
# 转换后 DXF 解析的文本实体上限（防止异常图纸把内存吃光）
_MAX_TEXT_ITEMS = 50000

_HERE = os.path.dirname(os.path.abspath(__file__))          # .../fidelity/backend/app/ingest
_BACKEND = os.path.dirname(os.path.dirname(_HERE))          # .../fidelity/backend
_PROJECT_APP = os.path.dirname(_BACKEND)                    # .../fidelity
_PROJECT_ROOT = os.path.dirname(_PROJECT_APP)               # .../2026-10-03-01-21-49
_WORKSPACE_ROOT = os.path.dirname(_PROJECT_ROOT)            # .../WorkBuddy

_TOOLS_DIR = os.path.join(_PROJECT_APP, "tools")

# LibreDWG 便携包可能放置的位置（按优先级）。也支持 LIBREDWG_DIR 环境变量覆盖。
_LIBREDWG_DIRS = [
    os.environ.get("LIBREDWG_DIR") or "",
    os.path.join(_TOOLS_DIR, "libredwg"),                       # 随项目携带（推荐）
    os.path.join(_WORKSPACE_ROOT, "tools", "libredwg"),         # 工作区级共享
    os.path.join(_PROJECT_ROOT, "tools", "libredwg"),
    r"C:\tools\libredwg",
    r"C:\Program Files\libredwg",
]

_ODA_COMMON_PATHS = [
    r"C:\Program Files\ODA\ODAFileConverter*",
    r"C:\Program Files (x86)\ODA\ODAFileConverter*",
]


def _find_dwg2dxf():
    """定位 LibreDWG 的 dwg2dxf.exe，返回路径或 None。"""
    for d in _LIBREDWG_DIRS:
        if d and os.path.isdir(d):
            p = os.path.join(d, "dwg2dxf.exe")
            if os.path.isfile(p):
                return p
    # 兜底：tools/ 任意子目录 + PATH
    hits = _find_exe(["dwg2dxf.exe", "dwg2dxf"])
    return hits


def _find_exe(names):
    """在 PATH 和 tools/ 目录里找可执行文件。"""
    dirs = list(os.environ.get("PATH", "").split(os.pathsep)) + [_TOOLS_DIR]
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    if os.path.isdir(_TOOLS_DIR):
        for n in names:
            hits = glob.glob(os.path.join(_TOOLS_DIR, "**", n), recursive=True)
            if hits:
                return hits[0]
    return None


def _find_oda_converter():
    for pat in _ODA_COMMON_PATHS:
        hits = glob.glob(os.path.join(pat, "ODAFileConverter.exe"))
        if hits:
            return hits[0]
    return _find_exe(["ODAFileConverter.exe"])


def converter_status():
    """给运维/UI 看的转换器可用性诊断。"""
    libredwg = _find_dwg2dxf()
    oda = _find_oda_converter()
    try:
        import ezdxf  # noqa: F401
        ezdxf_ok = True
    except ImportError:
        ezdxf_ok = False
    return {
        "libredwg": libredwg,
        "oda": oda,
        "ezdxf": ezdxf_ok,
        "dwg_ready": bool((libredwg or oda) and ezdxf_ok),
    }


def _run(cmd, timeout=_DWG_CONV_TIMEOUT):
    """跑转换命令，吞掉 LibreDWG 那些无害的 'Unstable Class' 告警。"""
    try:
        p = subprocess.run(cmd, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=False)
        return p.returncode
    except (OSError, subprocess.SubprocessError):
        return -1


def dwg_to_dxf(dwg_path):
    """DWG→DXF，返回临时 dxf 路径或 None。

    ⚠️ 临时目录生命周期（2026-10-04 修）：成功时早前只 `return out`，
    **从不删除 out_dir**。批量评测几百个 DWG 后就在系统临时目录里堆出
    几百个 qa_dwg_xxxx/ 目录（实测有 600KB~1MB 级的 DXF），
    既占空间也让排查变得困难。现在把 out_dir 挂在返回对象上，
    由调用方用 cleanup_dwg() 统一删除（见 format_router._cad_route）。
    """
    out_dir = tempfile.mkdtemp(prefix="qa_dwg_")
    stem = os.path.splitext(os.path.basename(dwg_path))[0]
    out = os.path.join(out_dir, stem + ".dxf")

    # 1) LibreDWG（首选：便携、无需安装、无需注册）
    exe = _find_dwg2dxf()
    if exe:
        is_libredwg = os.path.basename(exe).lower() == "dwg2dxf.exe"
        # LibreDWG 用 -o；libdxfrw 构建用 <in> <out>。两种都试，谁产出算谁。
        attempts = ([exe, "-o", out, dwg_path], [exe, dwg_path, out]) \
            if is_libredwg else ([exe, dwg_path, out], [exe, "-o", out, dwg_path])
        for cmd in attempts:
            try:
                _run(cmd)
            except Exception:
                pass
            if os.path.isfile(out) and os.path.getsize(out) > 0:
                _remember_dir(out_dir)
                return out

    # 2) ODA File Converter：<in> <out> <ver> <type> <recursive> <audit> [filter]
    oda = _find_oda_converter()
    if oda:
        try:
            _run([oda, os.path.dirname(dwg_path), out_dir,
                  "ACAD2018", "DXF", "0", "1", "*.dwg"])
            if os.path.isfile(out) and os.path.getsize(out) > 0:
                _remember_dir(out_dir)
                return out
        except Exception:
            pass

    cleanup_dwg(out_dir)
    return None


# 成功转换留下的临时目录登记处。之所以不能在 dwg_to_dxf 内部直接删：
# 调用方还要先 ezdxf 读完 DXF 才能删文件，所以删除时机交给调用方。
_DWG_TMP_DIRS = {}


def _remember_dir(d):
    _DWG_TMP_DIRS[d] = True


def cleanup_dwg(dxf_path):
    """删除 dwg_to_dxf 产出的文件**及其所在临时目录**。

    只删文件会留下空的 qa_dwg_xxxx/ 目录，批量跑完就是几百个空目录
    （实测泄漏过 694 个）。

    ⚠️ **安全约束**：只删「本进程 mkdtemp 建、且已登记」的目录里的东西。
    早期版本无条件 `os.remove(dxf_path)` 且只凭 `qa_dwg_` 前缀就删整目录，
    一旦传入用户自己的路径就会**删掉用户的文件**（单测 test_dwg_tmp_cleanup
    就是为此而写）。现在：不在登记处 + 前缀不匹配 → 什么都不删。
    """
    if not dxf_path:
        return
    d = os.path.dirname(dxf_path)
    owned = d in _DWG_TMP_DIRS
    if not (owned or os.path.basename(d).startswith("qa_dwg_")):
        # 不是本函数产出的临时目录 —— 绝不碰（可能是用户的真实文件）
        return
    try:
        if os.path.isfile(dxf_path):
            os.remove(dxf_path)
    except OSError:
        pass
    try:
        for f in os.listdir(d):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
        os.rmdir(d)
    except OSError:
        pass
    _DWG_TMP_DIRS.pop(d, None)


def _clean_text(t):
    """清掉 MTEXT 格式码与 CAD 特殊码。

    DIMENSION 的覆盖文字常带 `{\\H1.14286x;490}` 这类格式串，直接入库会污染
    比对（源文与 MD 无论如何都配不上）；`%%d/%%c/%%p` 是 °/Ø/± 的转义，
    还原后才是合规检索真正要命中的字符。
    """
    if not t:
        return ""
    if "{" in t or "%" in t or "\\" in t:
        try:
            from ezdxf.tools import text as _dt
            t = _dt.plain_mtext(t)
        except Exception:
            import re as _re
            for _ in range(5):  # 处理嵌套 {...}
                t2 = _re.sub(r"\{[^{}]*\}", "", t)
                if t2 == t:
                    break
                t = t2
            t = t.replace("%%d", "°").replace("%%c", "Ø").replace("%%p", "±")
    return t.strip()


def _text_of(entity):
    """取实体的可读文本（MTEXT 走 plain_text，其余走 dxf.text，统一再清洗）。"""
    try:
        if entity.dxftype() == "MTEXT":
            raw = entity.plain_text() or ""
        else:
            raw = (entity.dxf.text if hasattr(entity, "dxf") else None) or ""
    except Exception:
        return ""
    return _clean_text(raw)


def _insert_xy(entity):
    try:
        return float(entity.dxf.insert.x), float(entity.dxf.insert.y)
    except Exception:
        return 0.0, 0.0


def extract_dxf(dxf_path):
    """ezdxf 提取 TEXT/MTEXT/ATTRIB/标注文字，按 (y,x) 排序近似阅读顺序。

    扫描范围：**所有布局**（模型空间 + 图纸空间）—— 图签/标题栏通常在图纸空间，
    只扫模型空间会漏掉项目名、图号、比例、审批人等关键合规信息。

    返回 '' 表示没有文字实体（纯图形）。
    """
    try:
        import ezdxf
    except ImportError:
        return ""
    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception:
        # 损坏/版本太新 → 恢复模式
        try:
            from ezdxf import recover
            doc, _auditor = recover.readfile(dxf_path)
        except Exception:
            return ""

    items = []  # (-y, x, text)

    def _add(entity, text):
        t = (text or "").strip()
        if not t or t == "<>":
            return
        if len(items) >= _MAX_TEXT_ITEMS:
            return
        x, y = _insert_xy(entity)
        items.append((round(-y, 1), round(x, 1), t))

    layouts = []
    try:
        layouts = list(doc.layouts())
    except Exception:
        try:
            layouts = [doc.modelspace()]
        except Exception:
            layouts = []

    for layout in layouts:
        try:
            for e in layout.query("TEXT MTEXT"):
                _add(e, _text_of(e))
        except Exception:
            pass
        try:
            for ins in layout.query("INSERT"):   # 块引用属性文字（图签常在块内）
                for a in ins.attribs:
                    _add(a, _text_of(a))
        except Exception:
            pass
        try:
            for dim in layout.query("DIMENSION"):
                _add(dim, _text_of(dim))
        except Exception:
            pass

    items.sort()
    # 去重：同一段文字可能在多个布局/块里重复出现
    seen, out = set(), []
    for _y, _x, t in items:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return "\n".join(out)
