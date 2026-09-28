# 泄露定位清单（教学对照版本）

对应竞赛题目要求 5（泄露定位）。定位对象是 `experiments/ct_demo/` 里的
教学对照版本，**不是**平台正式使用的 `core/mlkem-native`。

## 结论摘要

| # | 位置 | 对应流程 | 状态 |
|---|---|---|---|
| 1 | `kyber/ref/poly.c` 的 `poly_frommsg` | 解封装中的重新加密：由明文字节重建多项式 | **已确认**，有反汇编证据 |
| 2 | 其余 `bt`/`test` 后紧跟跳转的函数 | Keccak 内部循环、`verify`、`cmov` 等 | **仅完成筛选，未逐个确认** |

只有第 1 项是本轮确认的泄露点。第 2 项是从全库扫描得到的候选清单，
需要在后续工作中逐个核对数据流，不应在报告中当作已确认的泄露点。

## 1 已确认：`poly_frommsg`

### 源码位置

- 定义：`experiments/clangover-poc/kyber/ref/poly.c:166`
- 调用点：`experiments/clangover-poc/kyber/ref/indcpa.c:269` 的
  `poly_frommsg(&k, m);`

### 对应流程

Kyber 解封装在重新加密阶段，需要把解密得到的明文消息 `m` 重新变成多项式：

```text
mlkem_dec
  -> crypto_kem_dec            (kem.c)
  -> indcpa_dec                (indcpa.c)
  -> poly_frommsg(&k, m)       (indcpa.c:269)   ← 定位点
```

`m` 由解密结果导出，本质上与私钥相关。`poly_frommsg` 对 `m` 的 256 位逐一
展开成 256 个系数，每一位都参与一次条件跳转，因此构成可利用的时序侧信道。

### 为什么会导致时间差异

源码写法本身是常数时间的掩码形式：

```c
mask = -(int16_t)((msg[i] >> j)&1);
r->coeffs[8*i+j] = mask & ((KYBER_Q+1)/2);
```

但 Clang 在 `-Os` 下把它降低成条件跳转（`clang 18.1.3`，x86-64）：

```asm
1bc:  movzbl (%rsi,%rax,1),%r8d
1c3:  bt     %ecx,%r8d        ; 取 msg[i] 的第 j 位到 CF
1c7:  jae    1ce              ; ← 依据该位跳转，秘密相关
1c9:  mov    $0x681,%edx
1ce:  mov    %dx,(%rdi,%rcx,2)
```

每处理一个系数就经历一次数据相关的条件跳转。分支预测是否命中、以及
每次迭代多做或跳过一次赋值，都会反映到运行时间上。

### 证据

命令：

```bash
cd experiments/ct_demo && make disasm
```

实测分支计数：

| 变体 | 总分支 | 秘密相关分支 |
|---|---:|---:|
| vuln（原样 `clang -Os`） | 3 | **1** |
| ct（改造后） | 1 | **0** |

vuln 的 3 个分支中，2 个是内外层循环控制，1 个是上面这条 `jae`。
ct 版只剩 1 个固定 32 次的外层循环控制，与输入无关。

### 触发条件（已实测）

| 编译器 | 优化选项 | 秘密相关分支 |
|---|---|---:|
| clang | `-O1` | 1 |
| clang | `-Os` | 1 |
| clang | `-O2` / `-O2 -fno-vectorize` | 0 |
| clang | `-O3` / `-O3 -fno-vectorize` | 0 |
| gcc | `-O1` / `-Os` / `-O2` / `-O3` | 0 |

所以触发窗口是 **Clang + `-O1`/`-Os`**。同一份源码用 GCC 编译时全程无分支，
Clang 在 `-O2`/`-O3` 下也不会引入该分支。报告中应写明这个边界，
不要把结论推广到所有编译配置。

## 2 待确认：全库筛选出的其他候选项

对教学对照版本的全部目标文件做了一次筛选，条件是"`bt`/`test` 之后紧跟
条件跳转"。命中的函数包括：

```text
pqcrystals_kyber512_ref_verify
pqcrystals_kyber512_ref_cmov
keccak_squeeze / keccak_squeezeblocks
pqcrystals_kyber_fips202_ref_shake128_init / _squeezeblocks
rej_uniform
polyvec_ntt / polyvec_invntt_tomont / polyvec_reduce
```

**这些尚未逐个确认，不能当作泄露点。** 已知的情况是：`verify` 与 `cmov`
的设计是固定长度遍历与掩码选择；Keccak 相关函数里命中的多是轮函数内部的
固定次数循环。但"筛选命中"不等于"与秘密相关"，需要逐个核对数据流后才能
下结论，这部分留作后续工作。

## 复现方式

```bash
cd experiments/ct_demo
make all        # 需要 clang；Makefile 已强制指定
make disasm     # 输出两个变体的 poly_frommsg 反汇编与分支计数
make test       # 确认改造没有改变语义（两构建输出逐字节相同）
```

改造后的源码副本保留在 `build/ct/poly.c`，可直接与
`experiments/clangover-poc/kyber/ref/poly.c` 逐行对比。差异只有一处，
在 `poly_frommsg` 内把 `const uint16_t byte = msg[i];` 提到内层循环之外。

## 边界说明

- 本清单针对的是教学对照版本，其结论**不适用于** `core/mlkem-native`。
- 分支计数按指令模式识别，属于启发式；数据流相关的判定是人工完成的。
- 改造依赖 Clang 的向量化行为，是**针对特定编译器版本的缓解**，
  不是常数时间性的证明。换编译器或优化级别都必须重新做反汇编核查。
