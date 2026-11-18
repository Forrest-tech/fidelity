"""Download the OCR models the distill pipeline needs (once), pinned by revision and SHA-256.

    python scripts/fetch_ocr_models.py            # into data/models (or $FIDELITY_OCR_MODELS)

The file is written to a temporary name and only kept when its size and hash match.
"""
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.distill import ocr as O  # noqa: E402


def main() -> int:
    if O.en_rec_model():
        print(f"ok: {O.EN_REC['file']} already present and verified in {O.MODEL_DIR}")
        return 0
    os.makedirs(O.MODEL_DIR, exist_ok=True)
    dest = os.path.join(O.MODEL_DIR, O.EN_REC["file"])
    tmp = dest + ".part"
    print(f"downloading {O.EN_REC['url']} ({O.EN_REC['size'] / 1e6:.1f} MB)")
    req = urllib.request.Request(O.EN_REC["url"], headers={"User-Agent": "fidelity-ocr-fetch"})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if os.path.getsize(tmp) != O.EN_REC["size"] or O.sha256(tmp) != O.EN_REC["sha256"]:
        os.remove(tmp)
        print("error: downloaded model does not match the pinned size/SHA-256; nothing kept")
        return 1
    os.replace(tmp, dest)
    print(f"ok: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
