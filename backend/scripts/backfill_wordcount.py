# -*- coding: utf-8 -*-
"""一次性回填 file_eval 的字数统计字段（src_chars/md_chars/src_words/md_words）。

背景：字数指标是后加的列，之前评测过的文件这几个字段为空，导致全库总字数显示 0。
本脚本**不重跑对齐**（对齐是最贵的一步），只读磁盘上已有的抽取缓存 + .md 原文算字数，
因此很快（千级文件分钟级），且不修改任何业务数据（只 UPDATE 字数列）。

幂等：可重复运行，只补 NULL 的记录。
用法：
    python -m scripts.backfill_wordcount            # 全部
    python -m scripts.backfill_wordcount --limit 50 # 试跑
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db  # noqa: E402
from app.domain import compare as cmp  # noqa: E402
from app.ingest import parsers  # noqa: E402


def main():
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    db.init_trust()
    sid = sys.argv[sys.argv.index("--sid") + 1] if "--sid" in sys.argv else "n2"
    src = config.get_source(sid)
    if not src:
        print("source not found:", sid)
        return 1

    con = db.trust_rw()
    try:
        rows = con.execute(
            "SELECT rel FROM file_eval WHERE status='evaluated' AND src_chars IS NULL"
        ).fetchall()
    finally:
        con.close()
    rels = [r["rel"] for r in rows]
    if limit:
        rels = rels[:limit]
    print("to backfill: %d" % len(rels), flush=True)
    if not rels:
        # 幂等：没有待回填项就直接退出，不要空转。
        # （历史上脚本在无任务时仍占着后台任务名额，看起来像「卡住 44 分钟」）
        print("nothing to backfill, done.", flush=True)
        return 0

    t0 = time.time()
    done = 0
    skipped = 0
    # 批量写库：早期版本每个文件单独开连接 + commit，千级文件要十几分钟；
    # 改成收集 200 条一次 executemany，只在最后 commit 一次（几十秒）。
    pending = []

    def flush():
        if not pending:
            return
        c = db.trust_rw()
        try:
            c.executemany(
                "UPDATE file_eval SET src_chars=?, md_chars=?, src_words=?, md_words=? WHERE rel=?",
                pending)
            c.commit()
        finally:
            c.close()
        pending.clear()

    for i, rel in enumerate(rels):
        sp = os.path.join(src["src_root"], rel)
        mp = parsers.md_path_for(src["md_root"], rel)
        md_text = ""
        if os.path.exists(mp):
            try:
                md_text = cmp.strip_md_artifacts(parsers.read_md_text(mp))
            except Exception:
                md_text = ""
        if not md_text:
            skipped += 1
            continue
        # 源文：优先用抽取缓存（避免重跑 OCR/pypdf）
        meta = {}
        try:
            src_text = parsers.extract_source_text_cached(sp, config.CACHE_DIR, meta=meta)
        except Exception:
            skipped += 1
            continue
        s = cmp.count_text(src_text)
        m = cmp.count_text(md_text)
        pending.append((s["chars"], m["chars"], s["words"], m["words"], rel))
        done += 1
        if len(pending) >= 200:
            try:
                flush()
            except Exception as e:
                print("  flush failed: %s" % str(e)[:80])
        if (i + 1) % 200 == 0:
            # flush=True 关键：后台任务面板靠 stdout 显示进度，
            # 不刷新就会长时间看不到任何输出，被误判为「卡住」。
            print("  %d/%d  (%.1fs)" % (i + 1, len(rels), time.time() - t0), flush=True)
    try:
        flush()
    except Exception as e:
        print("final flush failed: %s" % str(e)[:80], flush=True)

    print("backfilled %d, skipped %d, %.1fs" % (done, skipped, time.time() - t0), flush=True)

    con = db.trust_rw()
    try:
        row = con.execute(
            "SELECT count(*) n, sum(src_chars) sc, sum(md_chars) mc FROM file_eval "
            "WHERE src_chars IS NOT NULL"
        ).fetchone()
    finally:
        con.close()
    print("files=%s src_chars=%s md_chars=%s" % (row["n"], row["sc"], row["mc"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
