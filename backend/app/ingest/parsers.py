# -*- coding: utf-8 -*-
"""引擎 B：独立抽取源文件文本（规格 §4 入库层 / §5 独立性与生产不同）。

生产管线用 PyMuPDF/PaddleOCR，这里刻意用不同实现以防同源错误（自证）。

引擎选型说明（2026-10-04 实测修正）：
  原主引擎 pdfplumber 对**矢量密集型 PDF**（CAD 导出图纸）性能是灾难级的——
  实测一个 4.6MB 抗震图纸抽「单页」耗时 151.8 秒；同类文件 pypdf 抽 12 页仅 66 秒，
  快约 27 倍。故主引擎改为 pypdf（同样独立于 PyMuPDF，且主打 PurePython），
  pdfplumber 降级为**小文件兜底**（布局感知更强，能救回部分表格场景）。
"""
import os

# pdfplumber 兜底的体积上限：超过就不再尝试（避免重蹈慢速覆辙）
FALLBACK_MAX_MB = 3.0
# 抽取策略版本号：改动主引擎/抽取逻辑时必须提升，使抽取缓存整体失效。
# 历史：v1 = pypdf 主 + pdfplumber 小文件兜底（原为 pdfplumber 主，因矢量 PDF 过慢而换）
#       v2 = 格式路由器上线：扫描 PDF/图片→RapidOCR，dxf/dwg→CAD 提取，zip→解包递归
#       v3 = pymupdf 提为主引擎（实测 4.6MB 矢量 PDF：pymupdf 1.97s vs pypdf 48.4s，
#            快 25 倍）。pypdf 降为兜底 —— 它在矢量图上依然病态（单文件近 1 分钟）。
ENGINE_TAG = "pymupdf-v3"


def extract_source_text(path: str, max_pages=2000, meta=None) -> str:
    """统一入口：交给格式路由器按「扩展名+内容探测」分发到专用处理器。

    返回 '' 表示无文本/格式不适用（路由器会通过 meta["needs_human"] 区分
    「无处理器，需人工决定入库」与「确实无文本」）。
    """
    from . import format_router
    return format_router.extract(path, max_pages=max_pages, meta=meta) or ""


import hashlib

def _cache_key(path, mtime, size):
    # 缓存 key 纳入 ENGINE_TAG：更换引擎时只需提升 TAG 版本号即可整体失效，
    # 避免旧引擎抽取结果污染新引擎的评分（也免去了手工删除上千个缓存文件）。
    return hashlib.md5(("%s|%s|%s|%s" % (ENGINE_TAG, path, mtime, size))
                       .encode("utf-8", "ignore")).hexdigest()


def extract_source_text_cached(path, cache_dir, max_pages=2000, meta=None):
    """带磁盘缓存的源文抽取：按 (path, mtime, size) 缓存，避免 /diff 每次重抽大文件。"""
    if not os.path.exists(path):
        return ""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = _cache_key(path, st.st_mtime, st.st_size)
    cpath = os.path.join(cache_dir, "src_%s.txt" % key)
    epath = cpath + ".engine"
    if os.path.exists(cpath):
        try:
            with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            if meta is not None:
                meta["engine"] = _maybe_read(epath) or "cached"
                meta["cached"] = True
            return text
        except Exception:
            pass
    text = extract_source_text(path, max_pages, meta)
    # 不完整结果（OCR 页数/时间超限）不写缓存：否则补跑永远拿到残缺文本
    if not (meta is not None and meta.get("partial")):
        try:
            os.makedirs(cache_dir, exist_ok=True)
            tmp = cpath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, cpath)
            if meta is not None and meta.get("engine"):
                with open(epath, "w", encoding="utf-8") as f:
                    f.write(meta["engine"])
        except Exception:
            pass
    return text


def _maybe_read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return ""


def _pdf_pypdf(path, max_pages):
    """pypdf 抽取：独立于 PyMuPDF，且比 pdfplumber 快一个数量级。

    返回 None 表示引擎不可用或解析失败（区别于 "" 表示抽到但没有文本）。
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    parts = []
    try:
        rd = PdfReader(path)
        for i, page in enumerate(rd.pages):
            if i >= max_pages:
                break
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                parts.append(t)
    except Exception:
        return None
    return "\n".join(parts)


def _pdf_pdfplumber(path, max_pages):
    try:
        import pdfplumber
    except ImportError:
        return ""
    parts = []
    try:
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t)
    except Exception:
        return ""
    return "\n".join(parts)


def _pdf_text(path, max_pages, meta=None):
    """PDF 抽取策略：pypdf 主打（快），pdfplumber 仅小文件兜底（布局感知）。"""
    txt = _pdf_pypdf(path, max_pages)
    if txt:
        if meta is not None:
            meta["engine"] = "pypdf"
        return txt
    try:
        mb = os.path.getsize(path) / 1048576.0
    except OSError:
        mb = 0.0
    if 0 < mb <= FALLBACK_MAX_MB:          # 只对小文件尝试慢速兜底
        t2 = _pdf_pdfplumber(path, max_pages)
        if t2:
            if meta is not None:
                meta["engine"] = "pdfplumber"
            return t2
    if meta is not None:
        meta["engine"] = "pypdf"
    return txt or ""


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def _docx(path):
    try:
        import docx
    except ImportError:
        return ""
    try:
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs if p.text.strip())
    except Exception:
        return ""


def _xlsx(path):
    try:
        import openpyxl
    except ImportError:
        return ""
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        parts = []
        for ws in wb.worksheets:
            parts.append("## " + ws.title)
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    parts.append(" ".join(cells))
        wb.close()
        return "\n".join(parts)
    except Exception:
        return ""


def _pptx(path):
    try:
        from pptx import Presentation
    except ImportError:
        return ""
    try:
        prs = Presentation(path)
        parts = []
        for slide in prs.slides:
            for sh in slide.shapes:
                if hasattr(sh, "text") and sh.text.strip():
                    parts.append(sh.text)
        return "\n".join(parts)
    except Exception:
        return ""


def _msg(path):
    """抽取 .msg 邮件正文与**全部原始表头**。

    ⚠️ 历史缺陷（2026-10-05 修复）：原先只取 `subject + body`，
    发件人/收件人/抄送/时间等表头被整段丢弃 —— 这些是邮件的真实内容，
    丢了就是静默丢数据。现在按固定顺序原样输出，**不做任何翻译或改写**。

    标签用英文（Subject/From/To/…），与上游转换器写出的 md 表格一致，
    这样左右两栏的同一行才能真正对齐、并被判定为 match。
    """
    try:
        import extract_msg
    except ImportError:
        return ""
    try:
        m = extract_msg.Message(path)
    except Exception:
        return ""
    try:
        parts = []

        def _add(label, value):
            v = "" if value is None else str(value).strip()
            # "None"/"null" 是 extract_msg 对缺失字段的字符串化结果，不是真实内容
            if not v or v.lower() in ("none", "null"):
                return
            parts.append("%s: %s" % (label, v))

        _add("Subject", getattr(m, "subject", None))
        _add("From", getattr(m, "sender", None))
        _add("To", getattr(m, "to", None))
        _add("Cc", getattr(m, "cc", None))
        _add("Bcc", getattr(m, "bcc", None))
        _add("Date", getattr(m, "date", None))
        mid = getattr(m, "message_id", None)
        _add("Message-ID", mid)

        body = m.body or ""
        if parts:
            parts.append("")            # 表头与正文之间留一个空行
        parts.append(body)
        return "\n".join(parts).strip("\n")
    except Exception:
        return ""
    finally:
        try:
            m.close()
        except Exception:
            pass


# ---------- 大文件保护：子进程抽取 + 超时强杀 ----------
BIG_MB = 12.0           # 超过该体积走子进程
SUBPROC_TIMEOUT = 180   # 子进程抽取超时（秒），超时即强杀
TIMEOUT_SENTINEL = "__EXTRACT_TIMEOUT__"


def _cache_path(path, cache_dir):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return os.path.join(cache_dir, "src_%s.txt" % _cache_key(path, st.st_mtime, st.st_size))


def _read_cache(path, cache_dir):
    p = _cache_path(path, cache_dir)
    if p and os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None
    return None


def extract_source_text_guarded(path, cache_dir, timeout=SUBPROC_TIMEOUT, meta=None):
    """带大文件保护的抽取。

    小文件：进程内直接抽（快）。
    大文件(>BIG_MB)：交给子进程，超时强杀并返回 TIMEOUT_SENTINEL，
    父进程据此标记「延后」，绝不因一个巨型 PDF 卡死整批任务。
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if size <= BIG_MB * 1024 * 1024:
        return extract_source_text_cached(path, cache_dir, meta=meta)

    cached = _read_cache(path, cache_dir)
    if cached is not None:
        if meta is not None:
            meta["cached"] = True
        return cached

    import subprocess
    import sys
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract_worker.py")
    try:
        subprocess.run([sys.executable, worker, path, cache_dir],
                       timeout=timeout,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return TIMEOUT_SENTINEL
    except Exception:
        return ""

    # 子进程应已写缓存；读不到就当作无文本
    out = _read_cache(path, cache_dir)
    return out if out is not None else ""


def md_path_for(md_root: str, rel: str) -> str:
    """源相对路径 -> .md 镜像路径（out_rel = rel + '.md'）。"""
    return os.path.join(md_root, rel + ".md")


def read_md_text(md_path: str) -> str:
    return _read_text(md_path)
