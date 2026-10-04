# -*- coding: utf-8 -*-
"""压缩包处理：解包到临时目录后逐成员走格式路由，汇总文本。

边界（防炸弹）：
  成员数上限 100、累计解压上限 512MB、嵌套 zip 不再递归（只记录名字）。
  每个成员的文本前加 "## 成员名" 头，保持溯源。
"""
import os
import tempfile

MAX_MEMBERS = 100
MAX_TOTAL_UNCOMPRESSED = 512 * 1024 * 1024  # 512MB


def extract(zip_path, meta=None):
    if not zip_path.lower().endswith(".zip"):
        # .rar/.7z 需要额外工具，先标人工决定
        if meta is not None:
            meta["engine"] = "none"
            meta["needs_human"] = True
            meta["human_reason"] = "%s 暂不支持自动解包" % os.path.splitext(zip_path)[1]
        return ""
    try:
        import zipfile
    except ImportError:
        return ""
    out_dir = tempfile.mkdtemp(prefix="qa_zip_")
    parts, n = [], 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            total = sum(i.file_size for i in infos)
            if total > MAX_TOTAL_UNCOMPRESSED:
                if meta is not None:
                    meta["engine"] = "zip"
                    meta["needs_human"] = True
                    meta["human_reason"] = "解压后体积过大(%.0fMB)" % (total / 1048576.0)
                return ""
            from . import format_router as fr
            for info in infos[:MAX_MEMBERS]:
                name = info.filename
                lower = name.lower()
                if lower.endswith(".zip"):
                    parts.append("## [嵌套压缩包] %s（未展开）" % name)
                    continue
                safe = name.replace("\\", "_").replace("/", "_").replace("..", "_")
                dest = os.path.join(out_dir, safe)
                try:
                    with zf.open(info) as src, open(dest, "wb") as dst:
                        dst.write(src.read())
                except Exception:
                    continue
                m = {}
                try:
                    txt = fr.extract(dest, max_pages=200, meta=m)
                except Exception:
                    txt = ""
                if txt and txt.strip():
                    n += 1
                    eng = m.get("engine", "")
                    parts.append("## %s%s\n%s" % (name, ("（引擎:%s）" % eng) if eng else "", txt))
                try:
                    os.remove(dest)
                except OSError:
                    pass
            if len(infos) > MAX_MEMBERS:
                parts.append("## [截断] 成员超过 %d 个，仅处理前 %d 个" % (MAX_MEMBERS, MAX_MEMBERS))
    except Exception:
        pass
    finally:
        try:
            os.rmdir(out_dir)
        except OSError:
            pass
    if meta is not None:
        meta["engine"] = "zip"
        if n == 0:
            meta["needs_human"] = True
    return "\n\n".join(parts)
