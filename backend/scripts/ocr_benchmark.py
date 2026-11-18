"""Run the synthetic-scan OCR benchmark and write a report.

  python scripts/ocr_benchmark.py --pdf <text-layer PDF> --pages 1,5,9 --out ../docs/benchmarks/ocr
The source PDF is only read.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.distill import benchmark as B  # noqa: E402


SAMPLE = [
    "D2D13 Width of a required exit: The unobstructed width of a required exit must be not less than 1000 mm "
    "and, for a Class 9a building, not less than 1800 mm in a corridor used for patient movement.",
    "Table 3.4 gives the fire resistance level (FRL) of 120/120/120 for loadbearing walls, 90/90/90 for "
    "non-loadbearing walls and -/60/30 for doors. Sprinklers are required above an effective height of 25 m.",
    "The design wind speed is 45.5 m/s for region C; the live load on the floor is 3.0 kPa and the point load is 2.7 kN.",
]


def make_synthetic(path):
    import pymupdf
    doc = pymupdf.open()
    for i in range(3):
        pg = doc.new_page()
        para = "\n\n".join(SAMPLE[(i + k) % len(SAMPLE)] for k in range(len(SAMPLE)))
        text = f"Section {i + 1}\n\n" + para + "\n\n" + para
        pg.insert_textbox(pymupdf.Rect(60, 60, 540, 780), text, fontsize=11, fontname="helv")
    doc.save(path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", help="text-layer PDF to use as ground truth")
    ap.add_argument("--synthetic", action="store_true", help="generate a 3-page code-like PDF instead (CI)")
    ap.add_argument("--pages", default="1", help="1-based page numbers, comma separated")
    ap.add_argument("--out", required=True, help="output path without extension (.md and .json are written)")
    ap.add_argument("--degradations", default="", help="comma separated subset of " + ",".join(B.DEGRADATIONS))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    if a.synthetic:
        a.pdf = make_synthetic(os.path.abspath(a.out) + ".source.pdf")
        a.pages = "1,2,3"
    elif not a.pdf:
        ap.error("--pdf or --synthetic is required")
    pages = [int(x) - 1 for x in a.pages.split(",") if x.strip()]
    deg = {k: v for k, v in B.DEGRADATIONS.items() if not a.degradations or k in a.degradations.split(",")}
    res = B.run(a.pdf, pages, degradations=deg)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out + ".json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write(B.to_markdown(res))
    print(B.to_markdown(res))


if __name__ == "__main__":
    main()
