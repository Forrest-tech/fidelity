# -*- coding: utf-8 -*-
"""一键跑全部测试。

  python scripts/run_all_tests.py

三个套件：
  1. unit_tests.py        101 项 —— 核心比对算法（归一化/对齐/评分/字数/性能/并发）
  2. test_router.py        75 项 —— 格式路由分诊与降级
  3. ui_contract_check.py  74 项 —— API↔UI 契约（需服务已在 8000 运行）

任何一项失败即整体失败（非零退出码），可直接接 CI。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(script, need_service=False):
    print("\n" + "#" * 66)
    print("# 运行 %s" % script)
    if need_service:
        print("# （依赖本地 8000 服务；未启动会失败）")
    print("#" * 66)
    r = subprocess.run([PY, os.path.join(HERE, script)],
                       cwd=os.path.dirname(HERE))
    return r.returncode


def main():
    suites = [
        ("unit_tests.py", False),
        ("test_router.py", False),
        ("ui_contract_check.py", True),
    ]
    codes = {}
    for s, need in suites:
        codes[s] = run(s, need)

    print("\n" + "=" * 66)
    print("汇总")
    print("=" * 66)
    total_pass = 0
    for s, _ in suites:
        ok = codes[s] == 0
        print("  %-24s %s" % (s, "通过" if ok else "失败"))
        total_pass += ok
    print("-" * 66)
    print("  %d / %d 套件通过" % (total_pass, len(suites)))
    print("=" * 66)
    return 0 if total_pass == len(suites) else 1


if __name__ == "__main__":
    sys.exit(main())