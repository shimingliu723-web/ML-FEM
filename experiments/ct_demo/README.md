# 教学对照版本（ClangOver 可变时间 / 常数时间改造）

## 这是什么

同一份 Kyber-512 参考实现的两个构建，只差 `poly_frommsg` 里一处写法：

| 变体 | 构建方式 | 用途 |
|---|---|---|
| `vuln` | 原样编译（`clang -Os`） | 阳性对照：存在秘密相关分支 |
| `ct` | 只把字节读取提到内层循环外 | 改造后：分支消失 |

两个库都导出 `mlkem_keypair` / `mlkem_enc` / `mlkem_dec`，符号名与平台的
`backend/lib/libmlkem{512,768,1024}.so` 一致，因此
`experiments/formal_timing.c` 和 `backend/stats.py` 都能直接复用，只需换一个
`.so` 路径，不必改任何采集或统计代码。

## 这不是什么（重要）

- **不是 FIPS 203 的 ML-KEM。** 底层是 Kyber 第三轮参考实现
  （pq-crystals/kyber `b628ba7`），只有参数长度与 ML-KEM-512 相同。
- **不是平台正式使用的实现。** 正式实现是 `core/mlkem-native`，
  源码层面就是常数时间设计（`mlk_ct_memcmp` / `mlk_ct_cmov_zero`）。
- **其测量结果不得混作 `mlkem-native` 的结论。** 这一点沿用
  `docs/FORMAL_TIMING_2026-09-27.md` 已经确立的口径：主实现实测没有稳定
  时间差异，所以"发现差异→定位→改造→复测"这条链路必须在一个明确标注为
  教学对照、与正式实现分离的可变时间版本上演示。

## 漏洞机制

`poly_frommsg` 在源码层面**已经是**常数时间写法：

```c
mask = -(int16_t)((msg[i] >> j)&1);
r->coeffs[8*i+j] = mask & ((KYBER_Q+1)/2);
```

但 Clang 在 `-Os` 下把它编译成：

```asm
1bc:  movzbl (%rsi,%rax,1),%r8d
1c3:  bt     %ecx,%r8d        ; 取 msg[i] 的第 j 位到 CF
1c7:  jae    1ce              ; ← 依据该位跳转
1c9:  mov    $0x681,%edx      ; (KYBER_Q+1)/2 = 1665
1ce:  mov    %dx,(%rdi,%rcx,2)
```

`bt` + `jae` 形成秘密相关的条件跳转。`msg` 是解封装过程中重新加密所用的
明文，因此这个分支与私钥信息相关，构成可利用的时序侧信道。

## 改造方式

只改动一处：把字节读取提到内层循环之外。

```c
for(i=0;i<KYBER_N/8;i++) {
  const uint16_t byte = msg[i];     /* ← 唯一的改动 */
  for(j=0;j<8;j++) {
    mask = -(int16_t)((byte >> j)&1);
    r->coeffs[8*i+j] = mask & ((KYBER_Q+1)/2);
  }
}
```

语义完全不变，但 Clang 改为把内层 8 次迭代整体向量化成无分支代码：

```asm
1d6:  movzbl (%rsi,%rax,1),%ecx
1de:  pshufd $0x0,%xmm4,%xmm4     ; 广播该字节
1ef:  pcmpeqd %xmm2,%xmm4         ; 用比较生成掩码
1fb:  pandn  %xmm3,%xmm5          ; 掩码选择 0 或 1665
1ff:  movdqu %xmm5,(%rdi)         ; 一次写 8 个系数
20e:  jne    1d6                  ; ← 仅剩固定 32 次的外层循环
```

改造由 `apply_ct_patch.py` 生成，脚本用精确文本替换，找不到预期片段时
**以非零退出码结束**，避免静默产出一个"其实仍是漏洞版"的改造版。

## 构建与验证

```bash
cd experiments/ct_demo
make all      # 构建两个库
make test     # 正确性 + 两构建等价性
make disasm   # 反汇编 poly_frommsg，给出分支计数证据
```

`make test` 的实际结果（clang 18.1.3、Linux x86-64）：

```text
正确性
  [通过] 正常密文解封装结果一致            检查 200 次
  [通过] 篡改密文返回非零错误码            检查 400 次
  [通过] 篡改密文结果不等于正常值          检查 200 次
等价性（改造未改变语义）
  [通过] 正常密文两构建输出逐字节相同      检查 200 次
  [通过] 篡改密文两构建输出逐字节相同      检查 200 次

全部通过
```

`make disasm` 的实际结果：

| 变体 | 总分支 | 秘密相关分支 |
|---|---:|---:|
| vuln | 3 | **1** |
| ct | 1 | **0** |

vuln 的 3 个分支 = 1 个秘密相关 + 2 个循环控制；ct 仅剩 1 个固定 32 次的
外层循环控制，与输入无关。

## 触发条件（已实测）

| 编译器 | 优化选项 | 秘密相关分支 |
|---|---|---:|
| clang | `-O1` | 1 |
| clang | `-Os` | 1 |
| clang | `-O2` | 0 |
| clang | `-O2 -fno-vectorize` | 0 |
| clang | `-O3` | 0 |
| clang | `-O3 -fno-vectorize` | 0 |
| gcc | `-O1` / `-Os` / `-O2` / `-O3` | 0 |

两点值得注意：

1. **只有 Clang 会引入这个分支。** 同一份源码用 GCC 编译时全程无分支，
   这正是该漏洞被称为 ClangOver 的原因。这也意味着本目录的 Makefile
   **必须强制使用 clang**——写 `CC ?= clang` 是无效的，因为 make 内建了
   `CC = cc` 的默认值，`?=` 永远不会生效，结果会用 gcc 构建，
   从而得到一个"看起来无泄露"的对照版，让复测结论完全反过来。
2. **Clang 在 `-O2`、`-O3` 下不会引入该分支。** 因此漏洞的触发窗口是
   Clang + `-O1`/`-Os`。报告中应如实写明这个边界，不要把结论推广到所有构建。

## 已知限制

- 分支计数是按"`bt`/`test` 之后紧跟条件跳转"识别的，属于启发式；判定某个
  分支是否真的与秘密相关仍需人工看数据流。这里是逐个函数人工确认过的。
- 改造后的代码依赖 Clang 的向量化行为。**这是针对特定编译器版本的缓解，
  不是常数时间性的证明。** 换编译器或换优化级别都应重新做反汇编核查。
- 本目录尚未接入平台页面与后端接口，目前只能通过命令行使用。

## 相关文档

- `docs/CT_LOCATION.md`：泄露定位清单（题目要求 5 的交付物）
- `docs/FORMAL_TIMING_2026-09-27.md`：正式实现（`mlkem-native`）的计时实验记录
- `experiments/clangover-poc/`：本目录复用的 Kyber 参考源码来源
