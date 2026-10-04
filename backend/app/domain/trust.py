# -*- coding: utf-8 -*-
"""可信度状态机（规格 §6）。

双门槛(D2)：可信 = 人工裁决「一致」 AND 自动分 S >= THRESH。
D3 引用：全部可引，但每条依据强制附带「状态 + 自动分」。
D8 审计：裁决变更写 file_trust_log（审核人 + 时间）。
"""
import os
from .. import db

THRESH = 80.0  # 双门槛阈值，可配

# 人工裁决取值
HUMAN_NONE = None
HUMAN_OK = "ok"            # 一致
HUMAN_DIFF_BIG = "diff_big"  # 差异大
HUMAN_REJECTED = "rejected"  # 不接受

HUMAN_LABEL = {HUMAN_OK: "一致", HUMAN_DIFF_BIG: "差异大", HUMAN_REJECTED: "不接受"}


def compute_state(human_verdict, auto_score):
    """返回 (state_key, 显示标签, 引用标注)。"""
    s = auto_score if auto_score is not None else None
    if human_verdict == HUMAN_REJECTED:
        return ("rejected", "不接受", "人工已否决")
    if human_verdict == HUMAN_DIFF_BIG:
        return ("diff_big", "差异大", "人工标记·差异大")
    if human_verdict == HUMAN_OK:
        if s is not None and s >= THRESH:
            return ("trusted", "可信", "人工已审·一致（自动 %.0f%%）" % s)
        return ("need_review", "待复核",
                "待复核（人工一致但自动 %.0f%%<%d）" % (s if s is not None else 0, THRESH))
    # 未审
    if s is None:
        return ("unreviewed", "未审", "未人工审核（无自动分）")
    return ("unreviewed", "未审", "未人工审核（自动 %.0f%%）" % s)


def set_verdict(rel, verdict, reviewer="local", note=""):
    """写人工裁决 + 审计日志。verdict ∈ {ok, diff_big, rejected, None(重置为未审)}。"""
    now = db.now()

    def _do():
        con = db.trust_rw()
        try:
            row = con.execute("SELECT trust_state, rev_no FROM file_trust WHERE rel=?", (rel,)).fetchone()
            old = row["trust_state"] if row else None
            rev = (row["rev_no"] or 0) + 1 if row else 1
            con.execute(
                "INSERT INTO file_trust(rel,trust_state,reviewer,reviewed_at,note,rev_no) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(rel) DO UPDATE SET "
                "trust_state=excluded.trust_state, reviewer=excluded.reviewer, "
                "reviewed_at=excluded.reviewed_at, note=excluded.note, rev_no=excluded.rev_no",
                (rel, verdict, reviewer, now, note, rev),
            )
            con.execute(
                "INSERT INTO file_trust_log(rel,from_state,to_state,reviewer,ts,note) VALUES(?,?,?,?,?,?)",
                (rel, old, verdict, reviewer, now, note),
            )
            con.commit()
            return rev
        finally:
            con.close()

    rev = db.trust_write(_do)
    return {"rel": rel, "trust_state": verdict, "reviewer": reviewer, "rev_no": rev}


# 参与写入的列（新增列时只需改这里 + db.py 的迁移列表）
_EVAL_COLS = ("auto_score", "coverage", "number_fidelity", "engine_b", "status",
              "fail_reasons", "flags", "src_chars", "md_chars", "src_words", "md_words")


def upsert_eval(rel, **kw):
    def _do():
        con = db.trust_rw()
        try:
            cols = list(_EVAL_COLS)
            vals = [kw.get(c) for c in cols]
            if "status" not in kw:
                vals[cols.index("status")] = "evaluated"
            ph = ",".join("?" * len(cols))
            upd = ",".join("%s=excluded.%s" % (c, c) for c in cols)
            con.execute(
                "INSERT INTO file_eval(rel,%s,evaluated_at) VALUES(?,%s,?) "
                "ON CONFLICT(rel) DO UPDATE SET %s, evaluated_at=excluded.evaluated_at"
                % (",".join(cols), ph, upd),
                (rel, *vals, db.now()))
            con.commit()
        finally:
            con.close()
    db.trust_write(_do)


def get_eval(rel):
    con = db.trust_rw()
    row = con.execute("SELECT * FROM file_eval WHERE rel=?", (rel,)).fetchone()
    con.close()
    return dict(row) if row else None


def get_trust(rel):
    con = db.trust_rw()
    row = con.execute("SELECT * FROM file_trust WHERE rel=?", (rel,)).fetchone()
    con.close()
    return dict(row) if row else {"trust_state": None, "reviewer": None, "note": None}


def salvage_list(limit=600):
    """列出「原转换产物是二进制字符串打捞」的文件。

    这类文件的 .md 里全是二进制碎片（AC1032/RdAkRdAkRdA…），不是文档内容，
    自动分必然很低。它们是**重新转换**的候选，而不是源文件本身有问题。
    """
    con = db.trust_rw()
    try:
        rows = con.execute(
            "SELECT rel, auto_score, engine_b, fail_reasons FROM file_eval "
            "WHERE flags='salvage' ORDER BY rel LIMIT ?", (limit,)).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def deferred_rels(rels):
    """返回这批 rel 中「被标记延后」的集合（用于后续回来补跑）。"""
    if not rels:
        return set()
    out = set()
    CHUNK = 400
    con = db.trust_rw()
    try:
        for i in range(0, len(rels), CHUNK):
            part = rels[i:i + CHUNK]
            ph = ",".join("?" * len(part))
            for (r,) in con.execute(
                    "SELECT rel FROM file_eval WHERE rel IN (%s) AND status='deferred'"
                    % ph, part):
                out.add(r)
    finally:
        con.close()
    return out


def evaluated_rels(rels):
    """返回这批 rel 中「已有最终评测结果」的集合（增量模式跳过用）。

    只跳过 status='evaluated'：not_applicable / human_decide / error / deferred
    都要重跑——引擎升级（如 OCR 上线）后，老的「不适用」文件能被新引擎重新处理。
    """
    if not rels:
        return set()
    out = set()
    CHUNK = 400
    con = db.trust_rw()
    try:
        for i in range(0, len(rels), CHUNK):
            part = rels[i:i + CHUNK]
            ph = ",".join("?" * len(part))
            for (r,) in con.execute(
                    "SELECT rel FROM file_eval WHERE rel IN (%s) AND status='evaluated'" % ph, part):
                out.add(r)
    finally:
        con.close()
    return out


# ---------- 人工决定：无法自动比对的文件，入不入库由用户拍板（2026-10-04 需求） ----------
# file_eval.status='human_decide'（及遗留 not_applicable）的文件进入决定队列；
# 决定记录在 ingest_decision 表：include(入库，进人工抽检/重跑) / exclude(不入库，排除)。
DECIDE_PENDING_STATUSES = ("human_decide", "not_applicable")


def set_decision(rel, decision, reviewer="local", note=""):
    """写入/更新入库决定 + 审计日志。decision ∈ {include, exclude, None(撤销)}。"""
    now = db.now()

    def _do():
        con = db.trust_rw()
        try:
            if decision is None:
                con.execute("DELETE FROM ingest_decision WHERE rel=?", (rel,))
                con.execute(
                    "INSERT INTO file_trust_log(rel,from_state,to_state,reviewer,ts,note) "
                    "VALUES(?,?,?,?,?,?)", (rel, "decided", "pending", reviewer, now, note or "撤销决定"))
            else:
                con.execute(
                    "INSERT INTO ingest_decision(rel,decision,reviewer,decided_at,note) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(rel) DO UPDATE SET "
                    "decision=excluded.decision, reviewer=excluded.reviewer, "
                    "decided_at=excluded.decided_at, note=excluded.note",
                    (rel, decision, reviewer, now, note))
                con.execute(
                    "INSERT INTO file_trust_log(rel,from_state,to_state,reviewer,ts,note) "
                    "VALUES(?,?,?,?,?,?)", (rel, "human_decide", decision, reviewer, now, note))
            con.commit()
        finally:
            con.close()

    db.trust_write(_do)
    return {"rel": rel, "decision": decision}


def decisions_map(rels):
    """批量查决定。返回 {rel: decision}。"""
    if not rels:
        return {}
    out = {}
    CHUNK = 400
    con = db.trust_rw()
    try:
        for i in range(0, len(rels), CHUNK):
            part = rels[i:i + CHUNK]
            ph = ",".join("?" * len(part))
            for r in con.execute(
                    "SELECT rel,decision FROM ingest_decision WHERE rel IN (%s)" % ph, part):
                out[r["rel"]] = r["decision"]
    finally:
        con.close()
    return out


def list_decisions(sid="n2", decision=None, limit=500):
    """决定队列：待决定（status=human_decide/not_applicable 且无决定）或按决定值过滤。

    返回项带：类型、原因、体积、评测引擎——用户据此判断是否值得入库。
    """
    from .. import config
    src = config.get_source(sid)
    if not src:
        return []
    con = db.trust_rw()
    try:
        if decision:
            rows = con.execute(
                "SELECT e.rel, e.status, e.fail_reasons, e.engine_b, d.decision, d.decided_at "
                "FROM file_eval e JOIN ingest_decision d ON d.rel=e.rel "
                "WHERE d.decision=? ORDER BY e.rel LIMIT ?", (decision, limit)).fetchall()
        else:
            ph = ",".join("?" * len(DECIDE_PENDING_STATUSES))
            rows = con.execute(
                "SELECT e.rel, e.status, e.fail_reasons, e.engine_b, "
                "NULL AS decision, NULL AS decided_at "
                "FROM file_eval e WHERE e.status IN (%s) "
                "AND e.rel NOT IN (SELECT rel FROM ingest_decision) "
                "ORDER BY e.rel LIMIT ?" % ph,
                (*DECIDE_PENDING_STATUSES, limit)).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        rel = r["rel"]
        sp = os.path.join(src["src_root"], rel)
        try:
            size = os.path.getsize(sp) if os.path.exists(sp) else 0
        except OSError:
            size = 0
        out.append({
            "rel": rel, "ext": os.path.splitext(rel)[1].lower(),
            "mb": round(size / 1048576.0, 2),
            "reason": r["fail_reasons"] or "", "engine": r["engine_b"] or "",
            "decision": r["decision"], "decided_at": r["decided_at"],
        })
    return out


def decision_stats():
    """决定队列计数：待决定 / 已入库 / 已排除。"""
    con = db.trust_rw()
    try:
        ph = ",".join("?" * len(DECIDE_PENDING_STATUSES))
        pending = con.execute(
            "SELECT count(*) FROM file_eval WHERE status IN (%s) "
            "AND rel NOT IN (SELECT rel FROM ingest_decision)" % ph,
            DECIDE_PENDING_STATUSES).fetchone()[0]
        include = con.execute(
            "SELECT count(*) FROM ingest_decision WHERE decision='include'").fetchone()[0]
        exclude = con.execute(
            "SELECT count(*) FROM ingest_decision WHERE decision='exclude'").fetchone()[0]
    finally:
        con.close()
    return {"pending": pending, "include": include, "exclude": exclude}


def trust_badge(rel):
    """给检索引用用的标注：状态 + 自动分 + 标签。"""
    ev = get_eval(rel) or {}
    tr = get_trust(rel)
    auto = ev.get("auto_score")
    state, label, badge = compute_state(tr.get("trust_state"), auto)
    return {"rel": rel, "state": state, "label": label, "badge": badge,
            "auto_score": auto, "trust_state": tr.get("trust_state"),
            "reviewer": tr.get("reviewer")}


def badges_bulk(rels):
    """一次性把整批文件的 badge 算出来（2 次查询，而不是 2N 次）。

    文件列表动辄上千个，逐个 trust_badge 会打出数千次查询，列表刷新明显变慢。
    """
    if not rels:
        return {}
    qs = ",".join("?" * len(rels))
    con = db.trust_rw()
    try:
        evs = {r["rel"]: r
               for r in con.execute(
                   "SELECT rel,auto_score,status,flags,src_chars,md_chars,src_words,md_words "
                   "FROM file_eval WHERE rel IN (%s)" % qs, rels)}
        trs = {r["rel"]: (r["trust_state"], r["reviewer"])
               for r in con.execute("SELECT rel,trust_state,reviewer FROM file_trust WHERE rel IN (%s)" % qs, rels)}
    finally:
        con.close()
    out = {}
    for rel in rels:
        ev = evs.get(rel)
        auto = ev["auto_score"] if ev is not None else None
        v, reviewer = trs.get(rel, (None, None))
        state, label, badge = compute_state(v, auto)
        out[rel] = {"rel": rel, "state": state, "label": label, "badge": badge,
                    "auto_score": auto, "trust_state": v, "reviewer": reviewer,
                    "status": ev["status"] if ev is not None else None,
                    "flags": (ev["flags"] or "") if ev is not None else "",
                    "src_chars": ev["src_chars"] if ev is not None else None,
                    "md_chars": ev["md_chars"] if ev is not None else None,
                    "src_words": ev["src_words"] if ev is not None else None,
                    "md_words": ev["md_words"] if ev is not None else None}
    return out


def totals():
    """全局字数总量（用于顶栏展示「源文 vs 入库」体量对比）。"""
    con = db.trust_rw()
    try:
        r = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(src_chars),0) sc, COALESCE(SUM(md_chars),0) mc, "
            "COALESCE(SUM(src_words),0) sw, COALESCE(SUM(md_words),0) mw "
            "FROM file_eval WHERE status='evaluated'").fetchone()
    finally:
        con.close()
    sc, sw = r["sc"], r["sw"]
    return {
        "files": r["n"],
        "src_chars": sc, "md_chars": r["mc"],
        "src_words": sw, "md_words": r["mw"],
        "char_ratio": round(100.0 * r["mc"] / sc, 1) if sc else None,
        "word_ratio": round(100.0 * r["mw"] / sw, 1) if sw else None,
    }
