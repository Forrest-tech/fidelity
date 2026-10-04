# -*- coding: utf-8 -*-
"""源文件预览渲染层（独立于「抽取/识别」）。

职责：把源文件按**原生格式**渲染出来给用户看 —— 左栏显示源文件的真实样貌，
右栏显示转换后的 .md，两边逐行比对着看。

与 parsers/format_router 的区别：
  * format_router 追求「抽出可比对文本」，会丢弃排版、图表、图片等非文本信息；
  * preview 追求「还原人眼所见」，优先出图（PDF 页、图片、CAD 图），
    出不了图的用结构化 HTML 近似（表格 / 幻灯片 / 邮件正文），
    再不行才退回文本或明确说明不支持。

性能红线（沿用全项目的「不许卡死」约束）：
  * 渲染结果全部落磁盘缓存，翻页来回切不重复渲染；
  * 每个渲染器都带体积/规模上限，超限立即降级，绝不强攻；
  * 任何渲染异常都被兜住，返回 unsupported + 原因，不让 /api/preview 500。
"""
import hashlib
import os
import re
import time

from .. import config

PREVIEW_CACHE = os.path.join(config.CACHE_DIR, "preview")
os.makedirs(PREVIEW_CACHE, exist_ok=True)

# 各类渲染的规模上限（超过即降级，防止卡死）
PDF_MAX_PAGES = 3000        # 超过只渲染前 N 页
IMG_MAX_PX = 2200           # 图片最长边上限（超过等比缩小）
XLSX_MAX_ROWS = 300
XLSX_MAX_COLS = 40
TEXT_MAX_CHARS = 300000
DXF_MAX_ENTITIES = 20000    # CAD 实体过多则不渲染图形，退回文字清单
DXF_MAX_MB = 40.0
CAD_ENGINE = "libredwg+ezdxf"
RENDER_BUDGET_SEC = 20.0    # 单次预览渲染的时间预算（超过即提示，依赖缓存补偿）

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
_TEXT_EXT = {".txt", ".md", ".log", ".csv", ".xml", ".json", ".yaml", ".yml",
             ".ini", ".cfg", ".sql", ".html", ".htm"}
_UNSUPPORTED = {
    ".rfa": "Revit 族文件（.rfa）无开源解析器，需 Revit 桌面端导出；建议人工决定是否入库。",
    ".rvt": "Revit 项目文件（.rvt）需 Revit 桌面端导出；建议人工决定是否入库。",
    ".mp4": "视频文件无法做文本预览，需人工抽取关键信息。",
    ".doc": "旧版 Word（.doc）二进制格式暂不支持，建议先另存为 .docx 再入库。",
    ".ppt": "旧版 PowerPoint（.ppt）二进制格式暂不支持，建议先另存为 .pptx 再入库。",
    ".xls": "旧版 Excel（.xls）暂不支持预览，建议先另存为 .xlsx 再入库。",
    ".bak": "备份文件，无预览意义。",
}


def _key(path, tag=""):
    try:
        st = os.stat(path)
        raw = "%s|%s|%s|%s" % (path, st.st_mtime, st.st_size, tag)
    except OSError:
        raw = "%s|%s" % (path, tag)
    return hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()


def _ext(path):
    return os.path.splitext(path)[1].lower()


def _mb(path):
    try:
        return os.path.getsize(path) / 1048576.0
    except OSError:
        return 0.0


# ---------------------------------------------------------------- PDF
def _pdf_doc(path):
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # 旧版兼容
    doc = pymupdf.open(path)
    if doc.is_encrypted:
        try:
            doc.authenticate("")
        except Exception:
            pass
    return doc


def _pdf_info(path):
    try:
        doc = _pdf_doc(path)
        n = doc.page_count
        doc.close()
        return {"kind": "image", "pages": min(n, PDF_MAX_PAGES),
                "total_pages": n, "engine": "pymupdf-page",
                "note": ("仅渲染前 %d 页" % PDF_MAX_PAGES) if n > PDF_MAX_PAGES else ""}
    except Exception as e:
        return {"kind": "unsupported", "pages": 1, "engine": "pymupdf",
                "note": "PDF 打开失败：%s" % str(e)[:120]}


def _pdf_image(path, page, dpi=110):
    key = _key(path, "pdf%d@%d" % (page, dpi))
    cp = os.path.join(PREVIEW_CACHE, "pv_%s.png" % key)
    if os.path.exists(cp):
        with open(cp, "rb") as f:
            return f.read(), "image/png"
    doc = _pdf_doc(path)
    try:
        n = doc.page_count
        idx = max(0, min(page - 1, n - 1))
        pix = doc[idx].get_pixmap(dpi=dpi)
        data = pix.tobytes("png")
    finally:
        doc.close()
    try:
        tmp = cp + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, cp)
    except OSError:
        pass
    return data, "image/png"


# ---------------------------------------------------------------- 图片
def _image_info(path):
    return {"kind": "image", "pages": 1, "total_pages": 1,
            "engine": "pillow", "note": ""}


def _image_bytes(path, _page=1, _dpi=110):
    key = _key(path, "img")
    cp = os.path.join(PREVIEW_CACHE, "pv_%s.png" % key)
    if os.path.exists(cp):
        with open(cp, "rb") as f:
            return f.read(), "image/png"
    try:
        from PIL import Image
        im = Image.open(path)
        im.load()
        if max(im.size) > IMG_MAX_PX:
            r = IMG_MAX_PX / float(max(im.size))
            im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        tmp = cp + ".tmp"
        im.save(tmp, "PNG", optimize=True)
        os.replace(tmp, cp)
        with open(cp, "rb") as f:
            return f.read(), "image/png"
    except Exception:
        # 兜底：原样吐出（浏览器多数能直接显示）
        try:
            with open(path, "rb") as f:
                return f.read(), "image/*"
        except OSError:
            return b"", "image/png"


# ---------------------------------------------------------------- HTML 小工具
def _esc(s):
    # 注意：邮件头字段可能是 datetime / list，必须先转 str —— 否则 str.replace
    # 会被 datetime.replace(...) 接管并抛 TypeError（extract_msg 的 date 就是 datetime）
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_html(raw):
    """去掉脚本/样式/外链引用（邮件正文常带远程内容）。"""
    if not raw:
        return ""
    t = re.sub(r"(?is)<script.*?</script>", "", raw)
    t = re.sub(r"(?is)<style.*?</style>", "", t)
    t = re.sub(r"(?i)\s(on\w+)=[\"'][^\"']*[\"']", "", t)
    return t


# ---------------------------------------------------------------- Word
def _docx_html(path):
    import docx
    d = docx.Document(path)
    parts = []
    for p in d.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue
        style = (p.style.name or "").lower()
        if style.startswith("heading"):
            lvl = re.search(r"(\d)", style)
            lv = int(lvl.group(1)) if lvl else 2
            parts.append("<h%d>%s</h%d>" % (min(lv + 1, 5), _esc(t), min(lv + 1, 5)))
        else:
            parts.append("<p>%s</p>" % _esc(t))
    for tb in d.tables[:20]:
        rows = []
        for r in tb.rows[:80]:
            rows.append("<tr>" + "".join(
                "<td>%s</td>" % _esc(c.text.strip()) for c in r.cells[:20]) + "</tr>")
        if rows:
            parts.append("<table>" + "".join(rows) + "</table>")
    return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "python-docx",
            "html": "".join(parts) or "<p class='muted'>（文档无文本内容）</p>"}


# ---------------------------------------------------------------- Excel
def _xlsx_sheets(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    names = wb.sheetnames
    wb.close()
    return names


def _xlsx_html(path, sheet=0):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        names = wb.sheetnames
        idx = sheet if 0 <= sheet < len(names) else 0
        ws = wb[names[idx]]
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= XLSX_MAX_ROWS:
                rows.append("<tr><td class='muted' colspan='99'>… 已截断，仅显示前 %d 行</td></tr>"
                            % XLSX_MAX_ROWS)
                break
            cells = []
            for c in row[:XLSX_MAX_COLS]:
                if c is None:
                    c = ""
                cells.append("<td>%s</td>" % _esc(str(c)))
            if cells:
                rows.append("<tr>" + "".join(cells) + "</tr>")
        return {"kind": "html", "pages": len(names), "total_pages": len(names),
                "engine": "openpyxl", "sheets": names, "sheet": idx,
                "html": ("<table>%s</table>" % "".join(rows))
                         or "<p class='muted'>（空工作表）</p>"}
    finally:
        wb.close()


def _csv_html(path):
    import csv
    rows = []
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        for i, row in enumerate(csv.reader(f)):
            if i >= XLSX_MAX_ROWS:
                break
            rows.append("<tr>" + "".join("<td>%s</td>" % _esc(c) for c in row[:XLSX_MAX_COLS]) + "</tr>")
    return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "csv",
            "html": "<table>%s</table>" % "".join(rows)}


# ---------------------------------------------------------------- PowerPoint
def _pptx_html(path, page=1):
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation(path)
    n = len(prs.slides)
    idx = max(0, min(page - 1, n - 1))
    try:
        w, h = prs.slide_width, prs.slide_height
        scale = 760.0 / float(w) if w else 1.0
        boxes = []
        sl = prs.slides[idx]
        for sh in sl.shapes:
            try:
                left, top = float(sh.left or 0), float(sh.top or 0)
                sw, sh_h = float(sh.width or 0), float(sh.height or 0)
            except Exception:
                continue
            txt = ""
            if getattr(sh, "has_text_frame", False):
                txt = "\n".join(p.text for p in sh.text_frame.paragraphs if p.text.strip())
            elif getattr(sh, "has_table", False):
                for r in sh.table.rows:
                    txt += " | ".join(c.text.strip() for c in r.cells) + "\n"
            if not txt.strip():
                continue
            boxes.append(
                "<div class='ppt-box' style='left:%.0fpx;top:%.0fpx;width:%.0fpx;min-height:%.0fpx'>%s</div>"
                % (left * scale, top * scale, sw * scale, sh_h * scale,
                   _esc(txt).replace("\n", "<br/>")))
        html = ("<div class='ppt-slide' style='height:%.0fpx'>%s</div>"
                % (h * scale, "".join(boxes)))
        return {"kind": "html", "pages": n, "total_pages": n, "engine": "python-pptx",
                "html": html or "<p class='muted'>（该页无文本）</p>",
                "note": "按文本框坐标还原版式（图形/图片不渲染）"}
    finally:
        pass


# ---------------------------------------------------------------- 邮件
def _as_text(v):
    """extract_msg 的 htmlBody 可能是 bytes（也可能是 str），统一解码。"""
    if v is None:
        return ""
    if isinstance(v, bytes):
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return v.decode(enc)
            except UnicodeDecodeError:
                continue
        return v.decode("utf-8", "ignore")
    return v


def _msg_html(path):
    """渲染 .msg 预览。

    ⚠️ 历史缺陷（2026-10-05 修复）：这里原本**凭空捏造**了中文表头
    「主题/发件人/收件人/时间」，而 .msg 里根本没有中文字段（真实表头是英文
    Subject/From/To/Date）。于是左栏出现源文件里不存在的字，右侧 md 里当然
    找不到，被误判成「md 漏内容」。现在改为渲染真实表头值，标签与
    parsers._msg 保持一致，且**原样输出、不翻译**。
    """
    import extract_msg
    m = extract_msg.Message(path)
    try:
        rows = []

        def _row(label, value):
            v = "" if value is None else str(value).strip()
            if not v or v.lower() in ("none", "null"):
                return
            rows.append("<div><b>%s:</b> %s</div>" % (_esc(label), _esc(v)))

        _row("Subject", getattr(m, "subject", None))
        _row("From", getattr(m, "sender", None))
        _row("To", getattr(m, "to", None))
        _row("Cc", getattr(m, "cc", None))
        _row("Date", getattr(m, "date", None))
        head = ("<div class='mail-head'>%s</div>" % "".join(rows)) if rows else ""
        html = _safe_html(_as_text(m.htmlBody) or "")
        body = html if html.strip() else \
            "<pre class='plain'>%s</pre>" % _esc(_as_text(m.body) or "")
    finally:
        try:
            m.close()
        except Exception:
            pass
    return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "extract-msg",
            "html": head + body}


def _eml_html(path):
    import email
    from email import policy
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        msg = email.message_from_file(f, policy=policy.default)
    subj = msg.get("Subject", "")
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                body = _safe_html(part.get_content())
                break
            if part.get_content_type() == "text/plain" and not body:
                body = "<pre class='plain'>%s</pre>" % _esc(part.get_content())
    else:
        c = msg.get_content()
        body = _safe_html(c) if msg.get_content_type() == "text/html" \
            else "<pre class='plain'>%s</pre>" % _esc(c)
    head = ("<div class='mail-head'><div><b>主题：</b>%s</div>"
            "<div><b>发件人：</b>%s</div></div>"
            % (_esc(subj), _esc(msg.get("From", ""))))
    return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "email",
            "html": head + body}


# ---------------------------------------------------------------- 纯文本
def _text_view(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        t = f.read(TEXT_MAX_CHARS)
    return {"kind": "text", "pages": 1, "total_pages": 1, "engine": "text",
            "text": t, "note": "已截断至前 %d 字符" % TEXT_MAX_CHARS
            if len(t) >= TEXT_MAX_CHARS else ""}


# ---------------------------------------------------------------- 压缩包
def _zip_view(path):
    import zipfile
    items = []
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            items.append({"name": i.filename,
                          "size": i.file_size,
                          "dir": i.filename.endswith("/")})
    html = "<ul class='zip-list'>" + "".join(
        "<li>%s<span class='sz'>%s</span></li>" % (_esc(x["name"]),
                                                   _fmt_size(x["size"]))
        for x in items[:500]) + "</ul>"
    return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "zipfile",
            "html": html, "items": items[:500],
            "note": "压缩包共 %d 项（解包后的内容由系统递归处理）" % len(items)}


def _fmt_size(n):
    if n >= 1048576:
        return "%.1f MB" % (n / 1048576.0)
    if n >= 1024:
        return "%.0f KB" % (n / 1024.0)
    return "%d B" % n


# ---------------------------------------------------------------- CAD
def _cad_view(path, page=1):
    """CAD 图纸：优先渲染图形（DXF→PNG），做不到就给提取的文字清单。

    ⚠️ 性能：DWG→DXF 转换 + matplotlib 渲染实测 8–15s，因此渲染结果**必须**先查缓存
    （PNG 已落 PREVIEW_CACHE），否则每次打开文件都要等十几秒。缓存 key 含 mtime/size，
    文件改动会自动失效。
    """
    from . import cad
    ext = _ext(path)
    key = _key(path, "cad")
    cp = os.path.join(PREVIEW_CACHE, "pv_%s.png" % key)
    if os.path.exists(cp) and os.path.getsize(cp) > 0:
        return {"kind": "image", "pages": 1, "total_pages": 1,
                "engine": "ezdxf-matplotlib", "note": "CAD 图纸渲染（矢量图）"}

    dxf = path
    tmp = None
    if ext == ".dwg":
        st = cad.converter_status()
        if not st.get("dwg_ready"):
            return {"kind": "unsupported", "pages": 1, "engine": CAD_ENGINE,
                    "note": "DWG 渲染需要转换器（LibreDWG 未就位或 ezdxf 缺失）"}
        try:
            tmp = cad.dwg_to_dxf(path)
        except Exception as e:
            return {"kind": "unsupported", "pages": 1, "engine": CAD_ENGINE,
                    "note": "DWG 转换失败：%s" % str(e)[:120]}
        if not tmp:
            return {"kind": "unsupported", "pages": 1, "engine": CAD_ENGINE,
                    "note": "DWG 转换失败（转换器无输出）"}
        dxf = tmp

    mb = _mb(dxf)
    png = None
    if mb <= DXF_MAX_MB:
        try:
            png = _dxf_render(dxf)
            note_err = ""
        except Exception as e:
            png = None
            note_err = str(e)[:100]
    else:
        note_err = "DXF 过大（%.0fMB）" % mb

    if png:
        try:
            with open(cp + ".tmp", "wb") as f:
                f.write(png)
            os.replace(cp + ".tmp", cp)
        except OSError:
            pass
        _cleanup(tmp)
        return {"kind": "image", "pages": 1, "total_pages": 1,
                "engine": "ezdxf-matplotlib", "note": "CAD 图纸渲染（矢量图）"}

    # 降级：文字清单
    try:
        txt = cad.extract_dxf(dxf) or ""
    except Exception:
        txt = ""
    _cleanup(tmp)
    lines = [l for l in txt.splitlines() if l.strip()]
    html = ("<div class='cad-note'>图形渲染不可用%s，以下为图纸中提取的文字实体"
            "（图签 / 技术说明 / 尺寸标注）：</div><ul class='cad-list'>%s</ul>"
            % (("：" + _esc(note_err)) if note_err else "",
               "".join("<li>%s</li>" % _esc(l) for l in lines[:800])))
    return {"kind": "html", "pages": 1, "total_pages": 1,
            "engine": CAD_ENGINE, "html": html or "<p class='muted'>（图纸中未提取到文字）</p>"}


def _cleanup(tmp):
    """清理 DWG 转换产物。必须**连目录一起删**——
    dwg_to_dxf 用 mkdtemp 建 qa_dwg_xxxx/ 目录，只删里面的 .dxf 会留下空目录，
    批量预览几百个 DWG 后就是几百个空目录堆在系统临时区。
    这里统一交给 cad.cleanup_dwg 处理（它只删自己 mkdtemp 建的 qa_dwg_* 目录）。
    """
    if not tmp:
        return
    try:
        cad.cleanup_dwg(tmp)
    except Exception:
        # 兜底：至少把文件删掉
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _dxf_render(dxf_path):
    """DXF → PNG（matplotlib Agg）。实体过多/渲染失败时抛异常，由调用方降级。

    渲染**所有布局**并按各自范围拼到一张图上：CAD 图纸的图签、图号、比例、
    技术说明通常在图纸空间（PaperSpace），只画模型空间会丢掉最关键的文字，
    用户就看不出「转换漏了哪张图签」。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend, layout as dlayout
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(dxf_path)
    layouts = [doc.modelspace()]
    for lo in doc.layouts:
        if lo.name == "Model":
            continue
        try:
            layouts.append(lo)
        except Exception:
            continue

    # 统计总实体数（超限直接降级，不硬攻）
    n_ent = 0
    for lo in layouts:
        try:
            n_ent += len(lo)
        except Exception:
            pass
    if n_ent > DXF_MAX_ENTITIES:
        raise RuntimeError("实体过多（%d）" % n_ent)

    # 每个布局一个 subplot，避免不同坐标系互相压扁
    n = len(layouts)
    fig = plt.figure(figsize=(9, 6.5 * min(n, 2)), dpi=110)
    try:
        for i, lo in enumerate(layouts):
            ax = fig.add_axes([0, 0, 1, 1 / n]) if n == 1 else \
                fig.add_axes([0, 1 - (i + 1) / n, 1, 1 / n])
            ax.set_axis_off()
            ax.set_title(lo.name, fontsize=7, color="#888")
            ctx = RenderContext(doc)
            Frontend(ctx, MatplotlibBackend(ax)).draw_layout(lo, finalize=True)
        import io
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, facecolor="white")
        return buf.getvalue()
    finally:
        plt.close(fig)


# ---------------------------------------------------------------- 统一入口
def info(path):
    """返回该文件的预览能力描述（页数 / 渲染方式 / 备注），供前端决定 UI。"""
    if not os.path.exists(path):
        return {"kind": "missing", "pages": 1, "engine": "", "note": "源文件不存在"}
    ext = _ext(path)
    try:
        if ext == ".pdf":
            return _pdf_info(path)
        if ext in _IMAGE_EXT:
            return _image_info(path)
        if ext == ".docx":
            return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "python-docx"}
        if ext in (".xlsx", ".xlsm"):
            try:
                names = _xlsx_sheets(path)
                return {"kind": "html", "pages": len(names), "total_pages": len(names),
                        "engine": "openpyxl", "sheets": names}
            except Exception as e:
                return {"kind": "unsupported", "pages": 1, "engine": "openpyxl",
                        "note": "工作簿打开失败：%s" % str(e)[:120]}
        if ext == ".csv":
            return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "csv"}
        if ext == ".pptx":
            from pptx import Presentation
            n = len(Presentation(path).slides)
            return {"kind": "html", "pages": n, "total_pages": n, "engine": "python-pptx",
                    "note": "按文本框坐标还原版式（图形/图片不渲染）"}
        if ext == ".msg":
            return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "extract-msg"}
        if ext == ".eml":
            return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "email"}
        if ext in (".dwg", ".dxf"):
            if ext == ".dxf":
                return {"kind": "image", "pages": 1, "total_pages": 1,
                        "engine": "ezdxf", "note": "CAD 图纸"}
            from . import cad
            st = cad.converter_status()
            if not st.get("dwg_ready"):
                return {"kind": "unsupported", "pages": 1, "engine": CAD_ENGINE,
                        "note": "DWG 需要转换器：%s" % (st.get("hint") or "未就绪")}
            key = _key(path, "cad")
            cp = os.path.join(PREVIEW_CACHE, "pv_%s.png" % key)
            return {"kind": "image", "pages": 1, "total_pages": 1,
                    "engine": "ezdxf-matplotlib",
                    "note": "CAD 图纸渲染（矢量图）" if os.path.exists(cp)
                            else "CAD 图纸（首次渲染约 10 秒，之后走缓存）"}
        if ext == ".zip":
            return {"kind": "html", "pages": 1, "total_pages": 1, "engine": "zipfile"}
        if ext in _TEXT_EXT:
            return {"kind": "text", "pages": 1, "total_pages": 1, "engine": "text"}
        if ext in _UNSUPPORTED:
            return {"kind": "unsupported", "pages": 1, "engine": "",
                    "note": _UNSUPPORTED[ext]}
        return {"kind": "unsupported", "pages": 1, "engine": "",
                "note": "暂不支持预览该格式（%s）" % (ext or "无扩展名")}
    except Exception as e:
        return {"kind": "unsupported", "pages": 1, "engine": "",
                "note": "预览失败：%s" % str(e)[:120]}


def content(path, page=1, sheet=0):
    """返回预览内容（html / text / items / image 定位）。

    带**时间预算**守卫：重型渲染（DWG 转换、几百页 PPTX、超大表格）超过
    RENDER_BUDGET_SEC 即返回可解释的降级结果，而不是让 HTTP 请求挂住。
    （子进程隔离成本高，这里用「超时即降级 + 磁盘缓存补偿」：首次可能等一下，
      之后命中缓存就是毫秒级。）
    """
    ext = _ext(path)
    page = max(1, int(page or 1))
    t0 = time.time()
    out = _content_inner(path, page, sheet, ext)
    dt = time.time() - t0
    if dt > RENDER_BUDGET_SEC and out.get("kind") not in ("unsupported", "missing"):
        # 只是慢，不是失败：结果仍可用，但明确告知用户已超预算
        out = dict(out)
        out["note"] = ((out.get("note") or "") +
                       "（本次渲染耗时 %.1fs，已超 %.0fs 预算，结果已缓存）"
                       % (dt, RENDER_BUDGET_SEC)).strip("（")
    return out


def _content_inner(path, page, sheet, ext):
    try:
        if ext == ".pdf":
            n = _pdf_info(path).get("pages", 1)
            page = min(page, n)
            return {"kind": "image", "pages": n, "page": page, "engine": "pymupdf-page"}
        if ext in _IMAGE_EXT:
            return {"kind": "image", "pages": 1, "page": 1, "engine": "pillow"}
        if ext == ".docx":
            return _docx_html(path)
        if ext in (".xlsx", ".xlsm"):
            return _xlsx_html(path, sheet)
        if ext == ".csv":
            return _csv_html(path)
        if ext == ".pptx":
            return _pptx_html(path, page)
        if ext == ".msg":
            return _msg_html(path)
        if ext == ".eml":
            return _eml_html(path)
        if ext in (".dwg", ".dxf"):
            return _cad_view(path, page)
        if ext == ".zip":
            return _zip_view(path)
        if ext in _TEXT_EXT:
            return _text_view(path)
        if ext in _UNSUPPORTED:
            return {"kind": "unsupported", "pages": 1, "engine": "",
                    "note": _UNSUPPORTED[ext]}
        return {"kind": "unsupported", "pages": 1, "engine": "",
                "note": "暂不支持预览该格式（%s）" % (ext or "无扩展名")}
    except Exception as e:
        return {"kind": "unsupported", "pages": 1, "engine": "",
                "note": "预览渲染失败：%s" % str(e)[:160]}


def image_bytes(path, page=1, dpi=110):
    """返回 (bytes, mime)。只服务「图像型」预览：PDF 页 / 图片 / CAD 渲染。"""
    ext = _ext(path)
    if ext == ".pdf":
        return _pdf_image(path, page, dpi)
    if ext in _IMAGE_EXT:
        return _image_bytes(path)
    if ext in (".dwg", ".dxf"):
        cp = os.path.join(PREVIEW_CACHE, "pv_%s.png" % _key(path, "cad"))
        if os.path.exists(cp):
            with open(cp, "rb") as f:
                return f.read(), "image/png"
        # 还没渲染过：先触发一次渲染（会落缓存），再读取
        _cad_view(path, page)
        if os.path.exists(cp):
            with open(cp, "rb") as f:
                return f.read(), "image/png"
        return b"", "image/png"
    return b"", "image/png"
