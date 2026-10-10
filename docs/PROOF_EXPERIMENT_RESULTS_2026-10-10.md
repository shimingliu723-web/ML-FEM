# A1-13 服务器证明性实验结果记录（2026-10-10）

## 实验环境

- 项目目录：`/disk4/lsm/A1-13-MLKEM-Platform`
- 运行编号：`20261010-141555`
- 参数集主实验：`ML-KEM-512`
- 固定 CPU：`0`
- 环境自检等级：`green`
- 结论：适合作为正式计时检测和修复前后对比实验环境
- CPU 频率策略：`powersave`
- 虚拟化类型：`none`
- 抖动指标 `p95/median`：`1.1485`

## 实验一：基本功能与公开测试向量

基础功能自测规模：每个参数集 100 次。

| 参数集 | 通过情况 | keygen 平均耗时 | encaps 平均耗时 | decaps 平均耗时 |
|---|---:|---:|---:|---:|
| ML-KEM-512 | 100/100 | 25434 ns | 28992 ns | 34266 ns |
| ML-KEM-768 | 100/100 | 42581 ns | 47238 ns | 54226 ns |
| ML-KEM-1024 | 100/100 | 65841 ns | 72279 ns | 80603 ns |

公开向量验证：

- 内置 KAT：`15/15 passed`
- 平台可直接导入的官方 decapsulation 向量：`60/60 passed`
- NIST ACVP/FIPS203 官方验证：`ALL GOOD! (435 cases in 1.1s)`

## 实验二：等长输入样本生成

- 样本类别：`normal`、`changed_mid`、`changed_first`、`changed_last`
- 每类数量：`512`
- ML-KEM-512 输入长度：`768 bytes`
- 设计原则：所有类别长度一致，只进行固定位置 1 bit 改动，不用截断或明显长度差异制造结果。

## 实验三：输入分类计时

目标实现：`variant_early_return`

| 类别 | mean | p50 | p95 | 相对 normal 均值差 |
|---|---:|---:|---:|---:|
| changed_first | 31560.42 ns | 31308.00 ns | 31395.00 ns | -574.67 ns |
| changed_mid | 31830.29 ns | 31599.00 ns | 31690.00 ns | -304.80 ns |
| changed_last | 32129.76 ns | 31885.00 ns | 31973.00 ns | -5.33 ns |
| normal | 32135.08 ns | 31881.00 ns | 31977.00 ns | 0.00 ns |

该实验用于证明“不同输入类别”的构造不是只停留在样本文件层面，而是实际完成了重复计时和分布统计。

## 实验四：正式时间检测

配对次数：`10000`

| 目标 | 配对均值差 | 是否明显可区分 | 说明 |
|---|---:|---|---|
| 规范实现 `mlkem_native_baseline` | -5.20 ns | 否 | 用于证明平台不会把规范实现误判为明显异常 |
| 对照实现 `variant_early_return` | -277.74 ns | 是 | 用于展示平台可以识别明显时间差异 |

统计结论摘要：主检验在 `α=0.05` 下判为存在差异，均值差 `-277.74 ns`。

## 实验五：定位证据

- 源码定位结果：`early_return`
- 对照实现条件跳转数量：`7`
- 规范实现条件跳转数量：`6`
- 定位说明：对照实现会在首个不同字节处退出；规范实现会完整扫描并用掩码汇总差异。

## 实验六：自动修复与复测闭环

| 阶段 | 配对均值差 | 是否明显可区分 |
|---|---:|---|
| 修复前 | -281.56 ns | 是 |
| 修复后 | 6.37 ns | 否 |

- 差值降低：`275.19 ns`
- 自动补丁摘要：`419d962577db54075db3...`
- 补丁文件：`/disk4/lsm/A1-13-MLKEM-Platform/targets/variant_repaired/repair.patch`

## 实验七：跨参数集对比

| 目标 / 参数集 | 配对均值差 | 是否明显可区分 |
|---|---:|---|
| mlkem_native_baseline / ML-KEM-512 | -8.28 ns | 否 |
| variant_early_return / ML-KEM-512 | -277.88 ns | 是 |
| mlkem_native_baseline / ML-KEM-768 | 26.44 ns | 否 |
| variant_early_return / ML-KEM-768 | -418.27 ns | 是 |
| mlkem_native_baseline / ML-KEM-1024 | -10.08 ns | 否 |
| variant_early_return / ML-KEM-1024 | -545.90 ns | 是 |

该实验可作为“跨配置/跨参数集稳定性”材料：规范实现三个参数集均未出现明显可区分；对照实现三个参数集均出现明显可区分。

## 本地保存的证明材料

已从服务器拉回本地：

```text
C:\Users\huawei\Downloads\A1-13-MLKEM\proof_results\20261010-141555
```

包含：

- `proof_suite_result.json`：完整机器可读实验报告；
- `PROOF_SUMMARY.md`：服务器自动生成的简要总结；
- `input_classification.svg`：输入分类计时图；
- `timing_multi_target.svg`：多目标检测对比图；
- `repair_before_after.svg`：修复前后对比图；
- `cross_parameter_comparison.svg`：跨参数集对比图。

## 总体验收结论

本轮服务器实验已经覆盖题目要求中的关键验证链路：

1. 基本 ML-KEM 功能正确；
2. 公开向量来源充分，ACVP 官方验证通过；
3. 等长输入样本生成完成；
4. 时间检测采用重复测量和统计检验；
5. 能定位到源码级和二进制级差异证据；
6. 自动修复后重新检测，明显差异被降低到不可区分；
7. 给出了修复前后性能与分位数数据；
8. 给出了跨参数集稳定性对比图；
9. 结果文件、原始 CSV、JSON、SVG 均可复现。

