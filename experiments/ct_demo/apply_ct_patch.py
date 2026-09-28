#!/usr/bin/env python3
"""生成教学对照用的改造版 poly.c。

背景：Kyber 参考实现的 ``poly_frommsg`` 在源码层面已经是常数时间写法
（掩码 ``mask & ((KYBER_Q+1)/2)``），但 Clang 在 ``-Os`` 下会把它编译成
``bt`` + ``jae`` 的秘密相关分支。本脚本只做一处改动——把字节读取提到
内层循环之外——语义完全不变，但 Clang 会改为把内层 8 次迭代整体向量化成
无分支代码。

找不到预期片段时以非零退出码结束，避免静默产出一个"其实是漏洞版"的
改造版；这种错误如果被漏掉，后面的复测结论会完全反过来。

用法::

    python3 apply_ct_patch.py <原始 poly.c> <输出 poly.c>
"""

from __future__ import annotations

import sys
from pathlib import Path

ORIGINAL = """  for(i=0;i<KYBER_N/8;i++) {
    for(j=0;j<8;j++) {
      mask = -(int16_t)((msg[i] >> j)&1);
      r->coeffs[8*i+j] = mask & ((KYBER_Q+1)/2);
    }
  }"""

PATCHED = """  for(i=0;i<KYBER_N/8;i++) {
    /* 教学对照改造：把字节读取提到内层循环之外。
       语义与原始写法完全一致，但 Clang 不再把每位的掩码选择降低成
       bt/jae 条件跳转，而是把内层 8 次迭代整体向量化为无分支代码。 */
    const uint16_t byte = msg[i];
    for(j=0;j<8;j++) {
      mask = -(int16_t)((byte >> j)&1);
      r->coeffs[8*i+j] = mask & ((KYBER_Q+1)/2);
    }
  }"""


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    source, target = Path(argv[1]), Path(argv[2])
    if not source.is_file():
        print(f"错误：找不到输入文件 {source}", file=sys.stderr)
        return 2
    text = source.read_text(encoding="utf-8")
    count = text.count(ORIGINAL)
    if count != 1:
        print(
            f"错误：在 {source} 里找到 {count} 处预期的 poly_frommsg 片段，应为 1 处。"
            "源码可能已被改动，请核对后再生成改造版。",
            file=sys.stderr,
        )
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace(ORIGINAL, PATCHED, 1), encoding="utf-8")
    print(f"已生成改造版：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
