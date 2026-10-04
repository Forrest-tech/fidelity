# -*- coding: utf-8 -*-
"""任务处理器：注册 compare / eval 任务。"""
import os
from .. import config
from ..domain import compare as cmp
from ..domain import trust
from .queue import queue
from ..ingest import parsers


def _paths_for(rel, sid="n2"):
    src = config.get_source(sid)
    if not src:
        raise RuntimeError("source %s not configured" % sid)
    src_path = os.path.join(src["src_root"], rel)
    md_path = parsers.md_path_for(src["md_root"], rel)
    return src_path, md_path


def eval_one(rel, sid="n2", defer_sec=0.0):
    """评测单个文件，返回状态串。任何异常都被转成 error 状态，绝不外抛。

    defer_sec > 0 时，若「抽取」这一步耗时超过该秒数，直接标记 deferred 并跳过，
    不再进入对齐/评分——把慢文件留到以后单独处理，先保证整批跑完。
    """
    import time as _t
    t0 = _t.time()
    src_path, md_path = _paths_for(rel, sid)
    if not os.path.exists(src_path):
        trust.upsert_eval(rel, status="error", fail_reasons="源文件不存在",
                          engine_b="pypdf")
        return "no_source"
    meta = {}
    src_text = parsers.extract_source_text_guarded(src_path, config.CACHE_DIR, meta=meta)
    engine = meta.get("engine") or "pypdf"
    if defer_sec and (_t.time() - t0) > defer_sec:
        trust.upsert_eval(rel, status="deferred",
                          fail_reasons="抽取耗时>%.0fs，延后处理" % defer_sec,
                          engine_b=engine)
        return "deferred"
    if src_text == parsers.TIMEOUT_SENTINEL:
        trust.upsert_eval(rel, status="deferred",
                          fail_reasons="大文件抽取超时(>%ds)，延后处理"
                                       % parsers.SUBPROC_TIMEOUT,
                          engine_b=engine)
        return "deferred"

    def _extra():
        """汇总路由器回写的元信息 → 失败原因备注。"""
        bits = []
        if meta.get("partial"):
            bits.append("OCR未完成(已处理%s/%s页)" % (
                meta.get("ocr_pages_done", "?"), meta.get("ocr_pages_total", "?")))
        if meta.get("low_conf"):
            bits.append("OCR低置信(平均%s)" % meta.get("ocr_conf"))
        if meta.get("low_conf_pages"):
            bits.append("低置信页:%s" % ",".join(map(str, meta["low_conf_pages"][:8])))
        if meta.get("needs_human_confirm"):
            bits.append("CAD提取·待人工确认")
        return ("；".join(bits) + "；") if bits else ""

    # 无处理器/无法识别 → 进人工决定队列（入不入库由用户拍板，不再一律算「不适用」）
    if not src_text.strip():
        if meta.get("needs_human"):
            reason = meta.get("human_reason") or "该格式无法自动比对，需人工决定是否入库"
            trust.upsert_eval(rel, status="human_decide",
                              fail_reasons=reason, engine_b=engine)
            return "human_decide"
        trust.upsert_eval(rel, status="not_applicable",
                          fail_reasons="源文无文本层/格式不适用",
                          engine_b=engine)
        return "not_applicable"
    # OCR 只跑了一部分 → 标延后，等补跑拿完整结果，避免用残缺文本打分误导
    if meta.get("partial") and not meta.get("ocr_conf"):
        trust.upsert_eval(rel, status="deferred",
                          fail_reasons="OCR未完成(已处理%s/%s页)，延后补跑"
                                       % (meta.get("ocr_pages_done", "?"),
                                          meta.get("ocr_pages_total", "?")),
                          engine_b=engine)
        return "deferred"
    raw_md = parsers.read_md_text(md_path) if os.path.exists(md_path) else ""
    md_text = cmp.strip_md_artifacts(raw_md)
    if not md_text.strip():
        trust.upsert_eval(rel, status="error", fail_reasons="缺少 .md 或为空",
                          engine_b=engine)
        return "no_md"
    # 原转换产物若是「二进制字符串打捞」，则低分的原因在转换侧而非源文件侧，
    # 必须单独标出来 —— 否则用户在 UI 里只看到一堆低分，不知道该去重新转换。
    flags = "salvage" if cmp.md_is_salvage(raw_md) else None
    salvage_note = "⚠原转换产物为二进制打捞(parser=salvage)，非真实内容→需重新转换；" if flags else ""
    r = cmp.evaluate(src_text, md_text)
    trust.upsert_eval(
        rel, auto_score=r["auto_score"], coverage=r["coverage"],
        number_fidelity=r["number_fidelity"], engine_b=engine,
        status="evaluated", flags=flags,
        src_chars=r["src_chars"], md_chars=r["md_chars"],
        src_words=r["src_words"], md_words=r["md_words"],
        fail_reasons=_extra() + salvage_note
        + "src_only=%d,md_only=%d" % (r["n_src_only"], r["n_md_only"]),
    )
    return "ok:%.1f" % (r["auto_score"] or 0)


def handle_compare(job, report):
    """对比一个文件：引擎B抽源文 vs .md，算自动分并落库。"""
    rel = job["rel"]
    sid = job["kind"].split(":", 1)[1] if ":" in job["kind"] else "n2"
    report(5, "定位文件")
    try:
        report(20, "引擎B抽取源文")
        st = eval_one(rel, sid)
    except Exception as e:
        trust.upsert_eval(rel, status="error", fail_reasons=str(e)[:300],
                          engine_b="pdfplumber")
        report(100, "评测异常：%s" % str(e)[:120])
        return
    report(100, "完成 %s" % st)


# ---------- 批量评测 ----------
# 延后策略（用户 2026-10-04 拍板：太大的先放一下，做好标记，后面再处理）
#   注意：实测表明「慢」的真凶是矢量密集的 CAD 图纸，而非体积本身，
#   所以除了体积阈值，还加了「单文件抽取耗时阈值」做兜底。
_DEFAULT_DEFER_MB = 20.0    # 体积 > 该值 → 延后（默认）
_DEFAULT_DEFER_SEC = 60.0   # 抽取耗时 > 该值 → 延后（默认）
_MAX_MB_HARD = 400.0        # 绝对硬上限，超过一律延后，绝不强攻

# 三种模式的默认参数
_MODES = {
    "all":    dict(defer_mb=_DEFAULT_DEFER_MB, defer_sec=_DEFAULT_DEFER_SEC),
    "force":  dict(defer_mb=_DEFAULT_DEFER_MB, defer_sec=_DEFAULT_DEFER_SEC),
    # 补跑延后：放宽限制，给足预算（用户随时可点，跑不完不影响主流程）
    "defer":  dict(defer_mb=_MAX_MB_HARD, defer_sec=0.0),
}


def _parse_spec(spec):
    """解析 job.rel 里编码的参数："<mode>|<defer_mb>|<defer_sec>"。"""
    parts = (spec or "").split("|")
    mode = (parts[0] or "all").strip() or "all"
    if mode not in _MODES:
        mode = "all"
    cfg = dict(_MODES[mode])
    try:
        if len(parts) > 1 and parts[1].strip():
            cfg["defer_mb"] = float(parts[1])
    except ValueError:
        pass
    try:
        if len(parts) > 2 and parts[2].strip():
            cfg["defer_sec"] = float(parts[2])
    except ValueError:
        pass
    return mode, cfg


def handle_batch(job, report):
    """批量评测一个数据源下的全部已转 .md 文件。

    - 按源文件体积升序：小文件先出结果，进度条早期就可见。
    - 大文件 / 慢文件标记 deferred 跳过：不拖垮整批，后续可单独补跑。
    - 单文件异常隔离：一个坏文件不会拖垮整批。
    """
    import time as _t
    sid = job["kind"].split(":", 1)[1] if ":" in job["kind"] else "n2"
    src = config.get_source(sid)
    if not src:
        raise RuntimeError("source %s not configured" % sid)
    mode, cfg = _parse_spec(job.get("rel"))
    defer_mb, defer_sec = cfg["defer_mb"], cfg["defer_sec"]

    report(2, "扫描文件…")
    md_root, src_root = src["md_root"], src["src_root"]
    items = []
    for dp, dn, fn in os.walk(md_root):
        if "_kb" in dp or "_review" in dp:
            continue
        for name in fn:
            if not name.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dp, name), md_root).replace("\\", "/")[:-3]
            sp = os.path.join(src_root, rel)
            try:
                size = os.path.getsize(sp) if os.path.exists(sp) else 0
            except OSError:
                size = 0
            items.append((size, rel))
    items.sort()  # 小文件优先

    if mode == "defer":
        pend = trust.deferred_rels([r for _, r in items])
        items = [(s, r) for s, r in items if r in pend]
    elif mode != "force":
        done = trust.evaluated_rels([r for _, r in items])
        items = [(s, r) for s, r in items if r not in done]
    # 用户已拍板「不入库」的文件：任何模式都不再跑（已入库 exclude 决定）
    if items:
        excluded = trust.decisions_map([r for _, r in items])
        items = [(s, r) for s, r in items if excluded.get(r) != "exclude"]

    total = len(items) or 1
    report(5, "模式=%s 待处理 %d 个 | 延后阈值 %.0fMB / %.0fs"
           % (mode, len(items), defer_mb, defer_sec))
    n_ok = n_skip = n_fail = n_def = n_decide = 0
    t_start = _t.time()
    for i, (size, rel) in enumerate(items):
        mb = size / 1048576.0 if size else 0.0
        if size and mb > defer_mb:
            trust.upsert_eval(rel, status="deferred",
                              fail_reasons="源文件过大(%.0fMB>%.0fMB)，延后处理"
                                           % (mb, defer_mb),
                              engine_b="pypdf")
            n_def += 1
        else:
            try:
                st = eval_one(rel, sid, defer_sec=defer_sec)
                if st.startswith("ok"):
                    n_ok += 1
                elif st == "not_applicable":
                    n_skip += 1
                elif st == "human_decide":
                    n_decide += 1
                elif st == "deferred":
                    n_def += 1
                else:
                    n_fail += 1
            except Exception as e:
                trust.upsert_eval(rel, status="error", fail_reasons=str(e)[:300],
                                  engine_b="pypdf")
                n_fail += 1
        pct = 5.0 + 93.0 * (i + 1) / total
        report(pct, "已完成 %d/%d · 成功%d 待决定%d 延后%d 失败%d · %s" % (
            i + 1, len(items), n_ok, n_decide, n_def, n_fail,
            rel.split("/")[-1][:32]))
    report(100, "批量完成(%s)：成功%d 待决定%d 延后%d 失败%d，用时%.0fs"
           % (mode, n_ok, n_decide, n_def, n_fail, _t.time() - t_start))


def handle_reconvert(job, report):
    """批量重新转换：把「二进制打捞」的 .md 用真实提取结果重写（写盘前自动备份）。

    spec: "all"（全量扫描）| "list|rel1|rel2|..."（显式清单）
    每个文件重写后立刻重评，用户马上能看到新的转化率。
    """
    import time as _t
    from ..ingest import reconvert as rc
    sid = job["kind"].split(":", 1)[1] if ":" in job["kind"] else "n2"
    spec = job.get("rel") or "all"
    report(2, "扫描打捞产物…")
    if spec.startswith("list|"):
        rels = [r for r in spec[len("list|"):].split("|") if r]
    else:
        rels = rc.scan_salvage(sid)
    total = len(rels) or 1
    report(5, "待重新转换 %d 个" % len(rels))
    n_ok = n_skip = n_fail = 0
    t0 = _t.time()
    for i, rel in enumerate(rels):
        try:
            good, msg = rc.reconvert_one(rel, sid, backup=True)
            if good:
                n_ok += 1
                try:
                    eval_one(rel, sid)
                except Exception:
                    pass
            else:
                # 提取不出内容（如 RFA 无开源解析器）→ 保留原状，交给人工决定队列
                n_skip += 1
                trust.upsert_eval(rel, status="human_decide",
                                  fail_reasons="重新转换失败：%s" % msg[:200],
                                  engine_b="reconvert")
        except Exception as e:
            n_fail += 1
            trust.upsert_eval(rel, status="error",
                              fail_reasons="重新转换异常：%s" % str(e)[:200],
                              engine_b="reconvert")
        pct = 5.0 + 93.0 * (i + 1) / total
        report(pct, "已处理 %d/%d · 成功%d 跳过%d 失败%d · %s"
               % (i + 1, len(rels), n_ok, n_skip, n_fail, rel.split("/")[-1][:32]))
    report(100, "重新转换完成：成功%d 无法提取%d 失败%d，用时%.0fs"
           % (n_ok, n_skip, n_fail, _t.time() - t0))


def register():
    queue.register("compare", handle_compare)
    queue.register("batch", handle_batch)
    queue.register("reconvert", handle_reconvert)
