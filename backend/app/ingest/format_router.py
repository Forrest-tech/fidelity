# -*- coding: utf-8 -*-
"""格式路由器：按「扩展名 + 内容探测」把每种文件分发到专用的算法/模型处理器。

用户要求（2026-10-04）：不同格式要匹配合适的模型和算法，而不是一个模型包打天下。
这里就是那个「算法模型库」的路由层——注册表模式，新格式只需注册一个 handler，
主评测流程（eval_one / handle_batch）完全不用动。

路由表：
  .pdf   有文本层        → **pymupdf 主**（实测最快，矢量 PDF 秒级）+ pypdf 兜底
                           + pdfplumber 仅小文件兜底 + 无文本层转 OCR
  .pdf   无文本层(扫描件) → ocr.extract_pdf_scanned（RapidOCR CPU + 预处理 + 置信度）
  .jpg/.png/.tif…        → ocr.extract_image
  .dxf                   → cad.extract_dxf（ezdxf 提取 TEXT/MTEXT/标注）
  .dwg                   → cad.extract_dwg（外部转换器可用时走 DXF 路线；否则返回 None→人工决定）
  .zip                   → zip_handler（解包递归，成员逐一走本路由）
  .docx/.xlsx/.pptx/.msg/.txt/.md → 既有 office/文本处理器
  .rfa/.rvt/.mp4/.bak…   → 无处理器 → None（进人工决定队列）
"""
import os

# 各处理器模块延迟导入：没装依赖不影响其他格式
from . import parsers as _p
from . import ocr, cad, zip_handler


# ---------- 扩展名分类 ----------
EXT_TEXT_OFFICE = {".docx", ".xlsx", ".xlsm", ".pptx", ".msg", ".txt", ".md", ".csv", ".rtf"}
EXT_IMAGE = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
EXT_CAD = {".dxf", ".dwg"}
EXT_UNSUPPORTED = {".rfa", ".rvt", ".mp4", ".avi", ".mov", ".bak", ".exe", ".dll", ".bin"}
EXT_ARCHIVE = {".zip", ".7z", ".rar"}


def classify(path: str) -> str:
    """返回路由 key（不读文件内容，仅扩展名快判）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in EXT_IMAGE:
        return "image"
    if ext in EXT_CAD:
        return "cad"
    if ext in EXT_ARCHIVE:
        return "archive"
    if ext in EXT_TEXT_OFFICE:
        return "office"
    if ext in EXT_UNSUPPORTED:
        return "unsupported"
    return "unknown"


def extract(path: str, max_pages=2000, meta=None) -> str:
    """统一入口：路由到对应处理器。返回 '' 表示无文本，None 不使用。

    meta 回写：engine（处理器名）、ocr_conf（平均置信度）、low_conf（bool）、
              partial（OCR/解包未完成即中断）、needs_human（True→人工决定队列）。
    """
    route = classify(path)
    if route == "pdf":
        return _pdf_route(path, max_pages, meta)
    if route == "image":
        return _image_route(path, meta)
    if route == "cad":
        return _cad_route(path, meta)
    if route == "archive":
        return zip_handler.extract(path, meta)
    if route == "office":
        ext = os.path.splitext(path)[1].lower()
        fn = {".docx": _p._docx, ".xlsx": _p._xlsx, ".xlsm": _p._xlsx,
              ".pptx": _p._pptx, ".msg": _p._msg}.get(ext)
        if fn is not None:
            if meta is not None:
                meta["engine"] = ext.lstrip(".")
            return fn(path)
        if meta is not None:
            meta["engine"] = "text"
        return _p._read_text(path)
    # unsupported / unknown：显式标「需人工决定」
    if meta is not None:
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "无扩展名"
        meta["engine"] = "none"
        meta["needs_human"] = True
        # ⚠️ 必须给**可执行的原因**（2026-10-04 补）。只标 needs_human 时，
        # 用户在「待决定」队列里看到 153 个 RFA 排着，却不知道为什么、也不知道
        # 该怎么做决定。原因是决策的前提，不是装饰。
        if route == "unsupported":
            meta["human_reason"] = (
                "%s 为专有二进制格式，无可靠自动文本提取方案 → "
                "请人工确认：是否改为导出/另存为可读格式后重新入库" % ext.upper())
        else:
            meta["human_reason"] = (
                "未知扩展名 .%s，系统无对应处理器 → "
                "请人工确认文件类型与去留" % ext)
    return ""


# 单文件 OCR 预算：页数与时间双重上限（评测批量跑时防拖垮）
OCR_PAGE_CAP = 60          # 一次最多 OCR 60 页，超出标 partial
OCR_TIME_BUDGET = 120.0    # 单文件 OCR 时间预算（秒）
# 判定「扫描件」的文本层下限：pypdf 全文少于此字符数 → 视为无文本层
SCAN_TEXT_FLOOR = 80


def _pdf_mupdf(path, max_pages):
    """PyMuPDF 抽文本。这是**当前实测最快的引擎**：
    4.6MB 矢量图 CAD 图纸 PDF —— pymupdf 1.97s vs pypdf 48.4s（快 25 倍）。
    历史教训：曾把 pypdf 设为主引擎（因为它比 pdfplumber 快），但在矢量图上
    pypdf 依然病态（单文件近 1 分钟），用户点开就以为系统卡死。
    """
    import pymupdf
    out = []
    with pymupdf.open(path) as d:
        n = min(d.page_count, max_pages or 2000)
        for i in range(n):
            try:
                out.append(d[i].get_text("text") or "")
            except Exception:
                out.append("")
    return "\n".join(out)


def _pdf_route(path, max_pages, meta):
    """PDF 分级策略（按实测速度排序，不按历史包袱）：

      1. pymupdf  主引擎 —— 最快，文本层质量足够，绝大多数 PDF 秒开
      2. pypdf    兜底 —— pymupdf 抛异常时用；纯 Python，兼容性广但慢
      3. OCR      无/极少文本层时（扫描件）走 RapidOCR
    """
    txt = ""
    try:
        txt = _pdf_mupdf(path, max_pages)
    except Exception:
        txt = ""
    if txt and len(txt.strip()) >= SCAN_TEXT_FLOOR:
        if meta is not None:
            meta["engine"] = "pymupdf"
        return txt

    # pymupdf 失败 → pypdf 兜底（只跑一次，绝不反复）
    if not txt.strip():
        try:
            txt = _p._pdf_pypdf(path, max_pages)
        except Exception:
            txt = ""
        if txt and len(txt.strip()) >= SCAN_TEXT_FLOOR:
            if meta is not None:
                meta["engine"] = "pypdf"
            return txt

    # 小文件且文本仍极少 → pdfplumber 兜底一次（布局感知，仅限小文件）
    try:
        mb = os.path.getsize(path) / 1048576.0
    except OSError:
        mb = 0.0
    if not (txt and txt.strip()) and 0 < mb <= _p.FALLBACK_MAX_MB:
        t2 = _p._pdf_pdfplumber(path, max_pages)
        if t2 and len(t2.strip()) >= SCAN_TEXT_FLOOR:
            if meta is not None:
                meta["engine"] = "pdfplumber"
            return t2
    # 有一定文本但很少：可能封面图+扫描正文 → 仍然走 OCR，与已有文本合并
    ocr_txt = ocr.extract_pdf_scanned(
        path, max_pages=min(max_pages, OCR_PAGE_CAP),
        time_budget=OCR_TIME_BUDGET, meta=meta)
    if ocr_txt:
        if meta is not None and not meta.get("engine"):
            meta["engine"] = "pymupdf+ocr"
        return ((txt or "") + "\n" + ocr_txt).strip()
    if txt and txt.strip():
        if meta is not None and not meta.get("engine"):
            meta["engine"] = "pymupdf"
        return txt
    if meta is not None and not meta.get("engine"):
        meta["engine"] = "none"
        meta["needs_human"] = True
    return ""


def _image_route(path, meta):
    txt, conf = ocr.extract_image(path)
    if meta is not None:
        meta["engine"] = "rapidocr"
        meta["ocr_conf"] = conf
        meta["low_conf"] = conf is not None and conf < ocr.LOW_CONF
        if not txt.strip():
            meta["needs_human"] = True
    return txt


def _cad_route(path, meta):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".dxf":
        txt = cad.extract_dxf(path)
        if meta is not None:
            meta["engine"] = "ezdxf"
            meta["needs_human_confirm"] = True  # CAD 提取结果按用户要求默认待人工确认
        return txt
    # .dwg：需要外部转换器（dwg2dxf / ODA），可用则转 DXF 再提取
    dxf_path = cad.dwg_to_dxf(path)
    if dxf_path:
        txt = cad.extract_dxf(dxf_path)
        if meta is not None:
            meta["engine"] = "dwg2dxf+ezdxf"
            meta["needs_human_confirm"] = True
        # 删除临时文件**及其所在目录**（只删文件会留下空目录）
        cad.cleanup_dwg(dxf_path)
        return txt
    if meta is not None:
        meta["engine"] = "none"
        meta["needs_human"] = True
        meta["human_reason"] = "DWG 需要转换器（dwg2dxf/ODA）或人工导出"
    return ""
