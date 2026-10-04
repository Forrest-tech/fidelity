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


# --- 单页硬超时 -------------------------------------------------------
# 真实事故（2026-10-05）：一个 29 页纯扫描 PDF 让单个 compare 任务
# 卡在「引擎B抽取源文」超过 2.5 小时，updated_at 冻结、进度不动，
# 但 CPU 一直在烧 —— onnxruntime 推理进入了不可中断的死循环。
#
# 原来的 time_budget 只在「每页开始前」检查，一旦某页推理卡住，
# 预算检查永远等不到，于是整个批次被这一个文件永久拖住。
#
# 线程无法强杀，所以用子进程做隔离：父进程 join(timeout) 超时即 terminate。
PAGE_OCR_TIMEOUT = 90.0   # 单页 OCR 硬上限（秒）


def _ocr_image_worker(png_bytes, q):
    """子进程入口：跑一页 OCR，把 (text, conf) 放进队列。"""
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(png_bytes))
        q.put(ocr_image_obj(img))
    except Exception:
        q.put(("", None))
    finally:
        try:
            q.close()
        except Exception:
            pass


def ocr_image_with_timeout(img, timeout=PAGE_OCR_TIMEOUT):
    """带硬超时的单页 OCR。超时返回 ("", None)，绝不阻塞调用方。

    用子进程隔离 onnxruntime —— 推理卡死时线程无法中断，进程可以。

    降级说明：Windows 的 spawn 子进程需要 __main__ 可再导入，若当前入口
    无法 spawn（如 `python -c`），自动退回同进程调用并保证不抛异常。
    此时失去硬超时保护，但不会造成新的失败。
    """
    import io as _io
    try:
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
    except Exception:
        return "", None

    import multiprocessing as mp
    p = None
    try:
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        p = ctx.Process(target=_ocr_image_worker, args=(data, q))
        p.start()
    except Exception:
        # 无法起子进程时退回同步调用（宁可慢，不可崩）
        return ocr_image_obj(img)

    try:
        p.join(timeout)
        if p.is_alive():
            # 推理死循环：杀掉子进程，放弃这一页
            p.terminate()
            try:
                p.join(5)
            except Exception:
                pass
            if p.is_alive():
                try:
                    p.kill()
                except Exception:
                    pass
            return "", None
        if q.empty():
            return "", None
        try:
            return q.get_nowait()
        except Exception:
            return "", None
    finally:
        # 双保险：确保子进程一定被回收，不留孤儿进程烧 CPU
        try:
            if p.is_alive():
                p.terminate()
        except Exception:
            pass


def extract_pdf_scanned(path, max_pages=60, time_budget=120.0, meta=None):
    """扫描版 PDF：逐页渲染(200dpi) → 预处理 → OCR。

    三重保护：页数上限 + 整体时间预算 + **单页硬超时**。
    超出即返回已得文本并 meta["partial"]=True，绝不让一个扫描大文件拖垮整批。
    """
    import fitz  # PyMuPDF 渲染
    t0 = time.time()
    parts, confs, low_pages = [], [], []
    done = total = 0
    timed_out_pages = 0
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
            before = time.time()
            txt, conf = ocr_image_with_timeout(img)
            # 该页是否触发了硬超时（耗时接近上限且无结果）
            if not txt.strip() and (time.time() - before) >= PAGE_OCR_TIMEOUT * 0.9:
                timed_out_pages += 1
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
    if timed_out_pages and meta is not None:
        meta["ocr_timed_out_pages"] = timed_out_pages
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
