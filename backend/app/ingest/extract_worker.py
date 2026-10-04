# -*- coding: utf-8 -*-
"""大文件抽取子进程 worker。

用途：体积超过阈值的源文件（尤其是上百 MB 的 scanned PDF），pdfplumber 抽取
可能耗时数分钟甚至卡死。放在子进程里跑，父进程可超时强杀，避免拖垮整批任务。

用法：python extract_worker.py <源文件绝对路径> <缓存目录>
成功则把文本写入缓存并 exit 0。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(os.path.dirname(_HERE))  # .../fidelity/backend
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.ingest import parsers  # noqa: E402


def main():
    path = sys.argv[1]
    cache_dir = sys.argv[2]
    text = parsers.extract_source_text_cached(path, cache_dir)
    sys.stdout.write("OK %d\n" % len(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
