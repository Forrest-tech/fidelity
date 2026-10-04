# -*- coding: utf-8 -*-
"""扫描件/图片 OCR 管线（引擎B 专用）。

选型依据（2026-10-04 调研，见对话记录）：
- OmniDocBench v1.6 上 VLM 类模型第一是 PaddleOCR-VL(96.3%)，但需要 GPU；
  本机 16GB 无独显，故选 RapidOCR——PaddleOCR PP-OCR 系列模型的 ONNX 移植，
  纯 CPU、安装轻（无 PaddlePaddle 框架）、自带 检测+方向分类+识别 与逐行置信度。
- 精度路线（用户拍板）：本地 CPU 为主；低置信页由 WorkBuddy 内置大模型兜底
  （见 vlm_fallback.py），仍失败则进人工队列。目标：清晰打印件字符级 99%，
  模糊件逼近后标记人工复核——诚实的上限，不虚报。

置信度约定：
  LOW_CONF = 0.85      文件级平均置信度低于此 → meta["low_conf"]=True
  PAGE_LOW_CONF = 0.80 页级平均置信度低于此 → 记入 low_conf_pages（供 VLM 兜底）
"""
import os
import time

LOW_CONF = 0.85
PAGE_LOW_CONF = 0.80

_ENGINE = None


def _engine():
    """懒加载单例：首次几秒初始化，之后常驻。未安装返回 None。"""
    global _ENGINE
    if _ENGINE == "unavailable":
        return None
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ENGINE = RapidOCR()
        except Exception:
            _ENGINE = "unavailable"
    return None if _ENGINE == "unavailable" else _ENGINE


def available() -> bool:
    return _engine() is not None


# ---------- 预处理（PIL 实现，不引入 OpenCV 重依赖） ----------
def _preprocess(img):
    """灰度 + 自对比度拉伸 + 小图放大。扫描件常见偏灰偏淡，拉伸后识别率显著提升。"""
    try:
        from PIL import Image, ImageOps
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img, cutoff=1)
        w, h = img.size
        if w < 1000:                       # 低分辨率扫描 → 放大 2 倍利于检测
            img = img.resize((w * 2, h * 2), Image.LANCZOS)
        return img
    except Exception:
        return img


def _to_ndarray(img):
    import numpy as np
    return np.asarray(img)


def ocr_image_obj(img):
    """对一张 PIL 图做 OCR。返回 (text, 平均置信度 or None)。"""
    eng = _engine()
    if eng is None:
        return "", None
    img = _preprocess(img)
    try:
        result, _elapse = eng(_to_ndarray(img))
    except Exception:
        return "", None
    if not result:
        return "", None
    lines, confs = [], []
    for item in result:
        try:
            # 兼容两种返回：[box, text, conf] 或 dict
            if isinstance(item, dict):
                txt, cf = item.get("text", ""), float(item.get("score", 0))
            else:
                txt, cf = item[1], float(item[2])
        except Exception:
            continue
        if txt.strip():
            lines.append(txt.strip())
            confs.append(cf)
    avg = round(sum(confs) / len(confs), 4) if confs else None
    return "\n".join(lines), avg


def extract_image(path, meta=None):
    """单图片文件 OCR。返回 (text, conf)。"""
    try:
        from PIL import Image
        img = Image.open(path)
        # 巨图限幅：超过 4000px 长边先缩小，防止内存/耗时失控
        img.thumbnail((4000, 4000))
        return ocr_image_obj(img)
    except Exception:
        return "", None


def extract_pdf_scanned(path, max_pages=60, time_budget=120.0, meta=None):
    """扫描版 PDF：逐页渲染(200dpi) → 预处理 → OCR。

    双预算保护（页数 + 时间）：超出即返回已得文本并 meta["partial"]=True，
    绝不让一个扫描大文件拖垮整批——与延后策略一致。
    """
    import fitz  # PyMuPDF 渲染
    t0 = time.time()
    parts, confs, low_pages = [], [], []
    done = total = 0
    try:
        doc = fitz.open(path)
        total = doc.page_count
        for i in range(min(total, max_pages)):
            if time.time() - t0 > time_budget:
                if meta is not None:
                    meta["partial"] = True
                break
            page = doc[i]
            pix = page.get_pixmap(dpi=200)
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(pix.tobytes("png")))
            except Exception:
                continue
            txt, conf = ocr_image_obj(img)
            done += 1
            if txt.strip():
                parts.append(txt)
                if conf is not None:
                    confs.append(conf)
                    if conf < PAGE_LOW_CONF:
                        low_pages.append(i + 1)
        doc.close()
    except Exception:
        pass
    # VLM 兜底：启用时对低置信页做 AI 二次识别（未启用则优雅跳过，保持人工复核标记）
    try:
        from . import vlm_fallback
        if vlm_fallback.enabled() and low_pages:
            for pno, png in render_pages_for_vlm(path, low_pages[:10]):
                vt = vlm_fallback.ocr_page_vlm(png)
                if vt:
                    parts.append(vt)
                    if meta is not None:
                        meta.setdefault("vlm_pages", []).append(pno)
    except Exception:
        pass
    if meta is not None:
        meta["engine"] = "rapidocr"
        meta["ocr_pages_done"] = done
        meta["ocr_pages_total"] = total
        if done < total:
            meta["partial"] = True
        if confs:
            meta["ocr_conf"] = round(sum(confs) / len(confs), 4)
            meta["low_conf"] = meta["ocr_conf"] < LOW_CONF
        if low_pages:
            meta["low_conf_pages"] = low_pages[:50]
    return "\n".join(parts)


def render_pages_for_vlm(path, page_numbers, dpi=200):
    """把指定页渲染成 PNG bytes 列表，供 VLM 兜底使用。"""
    out = []
    try:
        import fitz
        import io
        doc = fitz.open(path)
        for pno in page_numbers:
            if 1 <= pno <= doc.page_count:
                pix = doc[pno - 1].get_pixmap(dpi=dpi)
                out.append((pno, pix.tobytes("png")))
        doc.close()
    except Exception:
        pass
    return out
