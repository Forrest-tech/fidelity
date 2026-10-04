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
    """写人工裁决 + 审计日志。verdict ∈ {ok, diff_big, rejected, ""/None(撤销裁决)}。

    ⚠️ 撤销时必须**一并清空 reviewer 与 note，并删除该行**。
    早期版本只把 trust_state 置空、审核人姓名照旧留着，于是产生
    「某审核人审过、但没有结论」的幽灵记录 —— 界面上显示为"未审"，
    却在 reviewer_stats 里给该审核人记了工作量，审计账目对不上；
    badges/统计也会把它算成一条真实记录。
    「谁签的字」和「签了什么结论」必须同时存在或同时消失。
    审计日志（file_trust_log）保留 ——「曾经审过、后来撤销」这件事要留痕。
    """
    now = db.now()
    # 撤销：清空结论 ⇒ 身份与备注一并清空
    if not verdict:
        reviewer, note = "", ""

    def _do():
        con = db.trust_rw()
        try:
            row = con.execute("SELECT trust_state, rev_no FROM file_trust WHERE rel=?", (rel,)).fetchone()
            old = row["trust_state"] if row else None
            rev = (row["rev_no"] or 0) + 1 if row else 1
            # 撤销：直接删行。只置空会留下一条「无主空行」——
            # badges/统计仍会把它算成一条记录，界面上出现没有结论、
            # 没有审核人的幽灵条目。
            if not verdict:
                con.execute("DELETE FROM file_trust WHERE rel=?", (rel,))
            else:
                con.execute(
                    "INSERT INTO file_trust(rel,trust_state,reviewer,reviewed_at,note,rev_no) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(rel) DO UPDATE SET "
                    "trust_state=excluded.trust_state, reviewer=excluded.reviewer, "
                    "reviewed_at=excluded.reviewed_at, note=excluded.note, rev_no=excluded.rev_no",
                    (rel, verdict, reviewer, now, note, rev),
                )
            con.execute(
                "INSERT INTO file_trust_log(rel,from_state,to_state,reviewer,ts,note) VALUES(?,?,?,?,?,?)",
                (rel, old, verdict or None, reviewer, now, note),
            )
            con.commit()
            return rev
        finally:
            con.close()

    rev = db.trust_write(_do)
    return {"rel": rel, "trust_state": verdict, "reviewer": reviewer, "rev_no": rev}
