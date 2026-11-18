"""Throughput on this machine (spec Phase 6, "performance measured"): distil + verify a text PDF, and
OCR scanned pages with every installed engine. Run it on each machine and keep the reports.

    python scripts/perf_benchmark.py --pdf <text-layer PDF> --pages 40 --ocr-pages 3 --out ../docs/benchmarks/perf-<machine>
"""
import argparse
import json
import os
import platform
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def cut(pdf, n, dest):
    import pymupdf
    src = pymupdf.open(pdf)
    out = pymupdf.open()
    out.insert_pdf(src, from_page=0, to_page=min(n, src.page_count) - 1)
    out.save(dest)
    return out.page_count


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--pages", type=int, default=40)
    ap.add_argument("--ocr-pages", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="this machine", help="how the report names the machine (no hostnames)")
    a = ap.parse_args(argv)
    os.environ.setdefault("FIDELITY_VISUAL_SAMPLES", "0")
    from app.distill import ocr as O
    from app.distill import run as R
    res = {"machine": a.label, "platform": platform.platform(), "cpu": platform.processor(),
           "python": platform.python_version()}
    with tempfile.TemporaryDirectory() as tmp:
        sample = os.path.join(tmp, "sample.pdf")
        n = cut(a.pdf, a.pages, sample)
        out, cache = os.path.join(tmp, "out"), os.path.join(tmp, "cache")
        os.makedirs(out)
        os.makedirs(cache)
        t0 = time.time()
        r = R.distill_pdf(sample, "sample.pdf", out, "/bench", cache, log=lambda *_: None)
        dt = time.time() - t0
        res["text_pdf"] = {"pages": n, "seconds": round(dt, 1), "pages_per_minute": round(n / dt * 60, 1),
                           "verdict": r["verdict"]}
        ocr = {}
        for eng in O.available_engines():
            times = []
            for i in range(min(a.ocr_pages, n)):
                img = O.render_page(sample, i)
                if max(img.size) > O.MAX_SIDE:
                    k = O.MAX_SIDE / max(img.size)
                    img = img.resize((int(img.width * k), int(img.height * k)))
                t1 = time.time()
                eng.read(img)
                times.append(time.time() - t1)
            ocr[eng.name] = {"pages": len(times), "seconds_per_page": round(sum(times) / max(len(times), 1), 1)}
        res["ocr"] = ocr
    lines = [f"# Throughput — {res['machine']}", "", f"{res['platform']}; Python {res['python']}.", "",
             f"- Text PDF distil + verify: **{res['text_pdf']['pages_per_minute']} pages/min** "
             f"({res['text_pdf']['pages']} pages in {res['text_pdf']['seconds']} s, verdict {res['text_pdf']['verdict']})."]
    lines += [f"- OCR {k}: **{v['seconds_per_page']} s/page** ({v['pages']} pages, image ≤ {O.MAX_SIDE} px)." for k, v in ocr.items()]
    with open(a.out + ".json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    with open(a.out + ".md", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
