# -*- coding: utf-8 -*-
"""格式路由与预览单元测试。

与 `unit_tests.py` 分工：那边锁「比对算法」，这边锁「分发逻辑」。

为什么必须有（用户 2026-10-04 要求）：
`format_router.classify()` 是整个质检系统的入口分诊 —— 一个文件的命运
（自动评分 / 进人工队列 / 判为不适用）全由它决定。此前**完全没有测试**：
扩展名集合被人加一个新后缀、或某格式的 handler 抛异常被静默吞掉，
都不会有任何测试报错，只会在 1193 条评测记录里悄悄产出错误结果。

重点锁三件事：
  1. classify 对每个扩展名的分诊结果（错一分诊 = 错一整类文件的结论）
  2. 不支持格式必须**显式标 needs_human**，绝不能静默返回空字符串假装「无内容」
     —— 那会让系统把「我不会处理」误报成「这文件是空的」，是最危险的一类错
  3. meta 回写完整性（engine / needs_human / ocr_conf 等前端依赖）

运行：  python scripts/test_router.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingest import format_router as R  # noqa: E402

_RESULTS = []


def check(name, cond, detail=""):
    _RESULTS.append((name, bool(cond), detail))


def eq(name, got, want):
    check(name, got == want, "got=%r want=%r" % (got, want))


# ============================================================== 1. 扩展名分诊
def test_classify():
    print("\n== 1. classify 扩展名分诊 ==")
    table = [
        # (文件名, 期望 route)
        ("a.pdf", "pdf"),
        ("a.PDF", "pdf"),
        ("a.jpg", "image"), ("a.JPEG", "image"), ("a.png", "image"),
        ("a.tif", "image"), ("a.tiff", "image"), ("a.bmp", "image"),
        ("a.webp", "image"),
        ("a.dxf", "cad"), ("a.DWG", "cad"),
        ("a.zip", "archive"), ("a.7z", "archive"), ("a.rar", "archive"),
        ("a.docx", "office"), ("a.xlsx", "office"), ("a.xlsm", "office"),
        ("a.pptx", "office"), ("a.msg", "office"),
        ("a.txt", "office"), ("a.md", "office"), ("a.csv", "office"),
        ("a.rtf", "office"),
        ("a.rfa", "unsupported"), ("a.RFA", "unsupported"),
        ("a.rvt", "unsupported"), ("a.mp4", "unsupported"),
        ("a.exe", "unsupported"), ("a.dll", "unsupported"), ("a.bin", "unsupported"),
        ("a.unknown_ext", "unknown"),
        ("noextension", "unknown"),
        # 双扩展名只看最后一个
        ("a.tar.gz", "unknown"),
    ]
    for name, want in table:
        got = R.classify(name)
        eq("classify(%s)" % name, got, want)

    # 路径形式的 rel（含目录）也要正确
    eq("含目录路径", R.classify("Code/Code/3500/AS NZS 3500.1-2021.pdf"), "pdf")
    eq("Windows 路径", R.classify(r"n2_Technical\Tundish\file.dwg"), "cad")


# ============================================== 2. 不支持格式必须标 needs_human
def test_unsupported_marks_human():
    print("\n== 2. 不支持格式显式标记（关键安全属性）==")
    # 用真实存在的假文件：extract 不该崩，且必须 needs_human
    for ext in (".rfa", ".rvt", ".mp4", ".exe"):
        p = os.path.join(tempfile.gettempdir(), "nonexistent_test" + ext)
        meta = {}
        try:
            out = R.extract(p, meta=meta)
        except Exception as e:
            check("不支持格式 %s 不抛异常" % ext, False, repr(e))
            continue
        check("不支持格式 %s 不抛异常" % ext, True)
        eq("不支持格式 %s 返回空串" % ext, out, "")
        eq("不支持格式 %s engine=none" % ext, meta.get("engine"), "none")
        check("不支持格式 %s 标 needs_human" % ext,
              meta.get("needs_human") is True,
              "meta=%r" % meta)
        check("不支持格式 %s 给人工原因" % ext,
              bool(meta.get("human_reason")), "meta=%r" % meta)

    # 未知扩展名同样要显式标，不能静默
    meta = {}
    R.extract(os.path.join(tempfile.gettempdir(), "x.qqq"), meta=meta)
    check("未知扩展名标 needs_human", meta.get("needs_human") is True, meta)


# ================================================== 3. 不存在文件必须优雅降级
def test_missing_file_graceful():
    print("\n== 3. 不存在文件优雅降级 ==")
    ghost = os.path.join(tempfile.gettempdir(), "definitely_not_here_20261004.pdf")
    meta = {}
    try:
        out = R.extract(ghost, meta=meta)
        check("不存在 PDF 不抛异常", True)
        check("不存在 PDF 返回空或短文本", len(out or "") < 200, len(out or ""))
    except Exception as e:
        check("不存在 PDF 不抛异常", False, repr(e))

    for ext in (".docx", ".xlsx", ".msg", ".dwg", ".zip", ".png"):
        p = os.path.join(tempfile.gettempdir(), "ghost_20261004" + ext)
        try:
            R.extract(p, meta={})
            check("不存在 %s 不抛异常" % ext, True)
        except Exception as e:
            check("不存在 %s 不抛异常" % ext, False, repr(e))


# ============================================================ 4. 文本类真实文件
def test_text_roundtrip():
    print("\n== 4. 文本/office 路由真实往返 ==")
    # 造一个真实 .txt，确认 office 路由能读出内容并标 engine=text
    fd, p = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write("Fire hydrant spacing 3 m\nPipe diameter 100 mm\n")
        meta = {}
        out = R.extract(p, meta=meta)
        check("txt 读出内容", "100 mm" in (out or ""), repr(out[:80]))
        eq("txt engine 标 text", meta.get("engine"), "text")
        check("txt 有内容则不标 needs_human", not meta.get("needs_human"), meta)
    finally:
        os.unlink(p)

    # 真实 .docx（openpyxl/python-docx 已在依赖里，造最小文档）
    try:
        import docx
        fd, p2 = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        d = docx.Document()
        d.add_paragraph("Sprinkler hydraulic calculation")
        d.add_paragraph("Pipe size 100 mm")
        d.save(p2)
        meta = {}
        out = R.extract(p2, meta=meta)
        check("docx 读出内容", "hydraulic" in (out or "").lower(), repr(out[:80]))
        eq("docx engine 标 docx", meta.get("engine"), "docx")
        os.unlink(p2)
    except ImportError:
        check("python-docx 可用", False, "依赖缺失")


# ============================================================== 5. CAD 路由标记
def test_cad_marks_confirm():
    print("\n== 5. CAD 路由需人工确认 ==")
    # 造一个最小 DXF（ezdxf 可读），确认 needs_human_confirm 被置位
    try:
        import ezdxf
        fd, p = tempfile.mkstemp(suffix=".dxf")
        os.close(fd)
        doc = ezdxf.new()
        doc.modelspace().add_text("FIRE HYDRANT 100mm")
        doc.saveas(p)
        meta = {}
        out = R.extract(p, meta=meta)
        eq("dxf engine 标 ezdxf", meta.get("engine"), "ezdxf")
        check("dxf 标需人工确认", meta.get("needs_human_confirm") is True, meta)
        check("dxf 提取到文字", "HYDRANT" in (out or "").upper(), repr(out[:80]))
        os.unlink(p)
    except ImportError:
        check("ezdxf 可用", False, "依赖缺失")


# ============================================================ 6. CAD 临时目录清理
def test_dwg_tmp_cleanup():
    print("\n== 6. DWG 临时目录清理（回归：曾泄漏 694 个目录）==")
    import tempfile as _tf
    from app.ingest import cad

    # 模拟 dwg_to_dxf 成功时留下的临时目录
    d = _tf.mkdtemp(prefix="qa_dwg_")
    p = os.path.join(d, "drawing.dxf")
    with open(p, "w", encoding="utf-8") as f:
        f.write("dummy dxf content")
    check("清理前目录存在", os.path.isdir(d))
    check("清理前文件存在", os.path.isfile(p))

    cad.cleanup_dwg(p)
    check("文件已删除", not os.path.isfile(p))
    # 这是关键：只删文件会留下空目录，批量跑完就是几百个
    check("**临时目录也一并删除**", not os.path.isdir(d),
          "目录残留: %s" % d)

    # 幂等：重复调用不报错
    try:
        cad.cleanup_dwg(p)
        check("重复清理幂等不报错", True)
    except Exception as e:
        check("重复清理幂等不报错", False, repr(e))

    # None / 不存在的路径必须安全
    try:
        cad.cleanup_dwg(None)
        cad.cleanup_dwg(os.path.join(d, "nope.dxf"))
        check("None/不存在路径安全", True)
    except Exception as e:
        check("None/不存在路径安全", False, repr(e))

    # ⚠️ 绝不能删用户目录：非 qa_dwg_ 前缀的目录必须原样保留
    keep = _tf.mkdtemp(prefix="user_data_")
    kf = os.path.join(keep, "important.dxf")
    with open(kf, "w", encoding="utf-8") as f:
        f.write("user file")
    cad.cleanup_dwg(kf)
    check("非 qa_dwg_ 目录的文件不被删", os.path.isfile(kf),
          "用户文件被误删: %s" % keep)
    import shutil as _sh
    _sh.rmtree(keep, ignore_errors=True)


# =========================================================== 7. 预算常量
def test_constants():
    print("\n== 7. 预算常量 ==")
    check("OCR_PAGE_CAP 为正整数", isinstance(R.OCR_PAGE_CAP, int) and R.OCR_PAGE_CAP > 0,
          R.OCR_PAGE_CAP)
    check("OCR_TIME_BUDGET 为正数", R.OCR_TIME_BUDGET > 0, R.OCR_TIME_BUDGET)
    check("SCAN_TEXT_FLOOR 为正整数", isinstance(R.SCAN_TEXT_FLOOR, int)
          and R.SCAN_TEXT_FLOOR > 0, R.SCAN_TEXT_FLOOR)
    print("   OCR_PAGE_CAP=%d OCR_TIME_BUDGET=%.0fs SCAN_TEXT_FLOOR=%d"
          % (R.OCR_PAGE_CAP, R.OCR_TIME_BUDGET, R.SCAN_TEXT_FLOOR))


# ============================== 8. OCR 单页硬超时（防推理死循环把批次拖死）
def test_ocr_page_timeout():
    """回归：2026-10-05 一个 29 页扫描件让任务卡死 2.5 小时。

    根因是 time_budget 只在每页开始前检查，单页推理卡死则预算永不生效。
    修复是 ocr_image_with_timeout()：子进程隔离 + join(timeout) + terminate。
    这里只验证「接口与常量」，不真跑 OCR（要 90s 且依赖模型文件）。
    """
    print("\n== 8. OCR 单页硬超时 ==")
    from app.ingest import ocr
    check("PAGE_OCR_TIMEOUT 为正数", isinstance(ocr.PAGE_OCR_TIMEOUT, (int, float))
          and ocr.PAGE_OCR_TIMEOUT > 0, ocr.PAGE_OCR_TIMEOUT)
    check("ocr_image_with_timeout 存在", hasattr(ocr, "ocr_image_with_timeout"))
    check("_ocr_image_worker 存在（spawn 需要可导入目标）",
          hasattr(ocr, "_ocr_image_worker"))
    # 子进程目标必须是模块级函数：spawn 会重新 import 并按名字定位它，
    # 闭包/lambda 无法被定位，会在启动时直接报错。
    import types
    check("worker 是模块级函数（spawn 可定位）",
          isinstance(ocr._ocr_image_worker, types.FunctionType), type(ocr._ocr_image_worker))
    # 超时返回值契约：任何异常路径都必须给出 (str, None) 而不能抛
    try:
        r = ocr.ocr_image_with_timeout(None, timeout=2)
        check("坏输入返回 ('', None) 而不抛异常",
              isinstance(r, tuple) and len(r) == 2, r)
    except Exception as e:
        check("坏输入不抛异常", False, "%s: %s" % (type(e).__name__, str(e)[:40]))
    print("   PAGE_OCR_TIMEOUT=%.0fs（单页上限，超过即放弃该页并继续）"
          % ocr.PAGE_OCR_TIMEOUT)


# ======================= 9. 单实例锁不得因宿主钩子崩溃（回归：服务起不来）
def test_instance_lock_survives_hooks():
    """回归：2026-10-05 服务启动直接崩。

    WorkBuddy 这类宿主会给 os.remove 挂安全钩子，把删除拦下后抛 SystemExit。
    SystemExit 继承自 BaseException 而非 OSError，原来的
    `except OSError: pass` 捕不到，于是 claim() 在启动阶段就崩，
    表现为「服务起不来」，日志里只有一句无关的批量删除告警。

    修法：claim() 不再预删锁（_write_lock 本就是覆盖写，删是多余动作），
    release() 捕获 BaseException。
    """
    print("\n== 9. 单实例锁的宿主钩子健壮性 ==")
    from app import instance
    import inspect as _insp

    # claim() 的可执行代码里不应再有 os.remove（注释里提到不算）
    import ast as _ast
    def _calls_remove(fn):
        for node in _ast.walk(_ast.parse(_insp.getsource(fn))):
            if isinstance(node, _ast.Call):
                f = node.func
                name = getattr(f, "attr", None) or getattr(f, "id", None)
                if name in ("remove", "unlink", "rmdir"):
                    return True
        return False
    check("claim() 不再删除锁文件", not _calls_remove(instance.claim))

    # release() 捕获 BaseException（而非仅 OSError）
    rsrc = _insp.getsource(instance.release)
    check("release() 捕获 BaseException", "except BaseException" in rsrc,
          "只捕 OSError 会被 SystemExit 击穿")

    # 实测：把 os.remove 换成会抛 SystemExit 的桩，release 仍不应崩
    orig = instance.os.remove
    def boom(_p):
        raise SystemExit("simulated safe-delete hook")
    try:
        instance.os.remove = boom
        with open(instance.LOCK_PATH, "w", encoding="utf-8") as f:
            f.write('{"pid": %d, "heartbeat_at": 1}' % os.getpid())
        try:
            instance.release()
            check("release() 遇 SystemExit 不崩溃", True)
        except SystemExit:
            check("release() 遇 SystemExit 不崩溃", False, "SystemExit 透出了")
        except BaseException as e:
            check("release() 遇 SystemExit 不崩溃", False, type(e).__name__)
    finally:
        instance.os.remove = orig
        try:
            os.remove(instance.LOCK_PATH)
        except OSError:
            pass

    # claim() 在残留锁（上一步没能删掉）存在时仍应成功抢到
    with open(instance.LOCK_PATH, "w", encoding="utf-8") as f:
        f.write('{"pid": 999999, "heartbeat_at": 0}')
    try:
        ok, info = instance.claim(port=8000)
        check("残留锁存在时 claim 仍成功", ok, info)
        instance.release()
    finally:
        try:
            os.remove(instance.LOCK_PATH)
        except OSError:
            pass


# ==================================================================== 主流程
def main():
    print("=" * 62)
    print("格式路由单元测试 —— format_router.py")
    print("=" * 62)

    for fn in (test_classify, test_unsupported_marks_human,
               test_missing_file_graceful, test_text_roundtrip,
               test_cad_marks_confirm, test_dwg_tmp_cleanup, test_constants,
               test_ocr_page_timeout, test_instance_lock_survives_hooks):
        fn()

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = [(n, d) for n, ok, d in _RESULTS if not ok]

    print("\n" + "=" * 62)
    if failed:
        print("失败明细：")
        for n, d in failed:
            print("  ✗ %s" % n)
            if d:
                print("      %s" % d)
    print("结果：%d / %d 通过" % (passed, len(_RESULTS)))
    print("=" * 62)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())