# 六类受控机制检测—定位—修复—复测闭环报告

结论：六类案例全部完成基本功能验证、三轮正式检测、源码/二进制定位、模式化修复和同参数三轮复测。总体状态：通过。

| 案例 | 修复规则 | 修复前平均绝对差值(ns) | 修复后(ns) | 降低比例 | 正确性 | 闭环 |
|---|---|---:|---:|---:|---|---|
| 比较提前结束 | early_return_compare | 298.62 | 5.69 | 98.09% | 通过 | 通过 |
| 条件失败路径 | conditional_rejection_path | 2672.84 | 6.21 | 99.77% | 通过 | 通过 |
| 数据相关循环 | data_dependent_loop | 5573.13 | 2.62 | 99.95% | 通过 | 通过 |
| 数据相关访存 | data_dependent_memory | 6864.10 | 6.84 | 99.90% | 通过 | 通过 |
| 条件分支 | data_dependent_branch | 2433.59 | 6.81 | 99.72% | 通过 | 通过 |
| 运行期除法路径 | variable_time_division | 6515.11 | 0.99 | 99.98% | 通过 | 通过 |

## 统一实验条件

- ML-KEM-512，同一批512组等长样本；每轮10000对，三轮独立重复。
- 固定CPU核心，CLOCK_MONOTONIC_RAW仅包围解封装调用；预热2000对。
- 每轮同时执行A/A同输入对照；原始计时全部保存，不做事后异常值剔除。
- 修复前后使用相同样本摘要、类别、样本量、种子、核心和统计规则。
- 所有修复产物均重新编译，并通过三个参数集各100次自测及适用公开向量验证。

## 证据

- 汇总JSON：`results/acceptance/six-case-closure-final/report.json`
- 对比图：`results/acceptance/six-case-closure-final/six-case-before-after.png`
- 各案例原始报告与补丁路径记录在汇总JSON中。
- 函数级插桩验收：`results/acceptance/20261013-204010-function-trace-seven-cases.json`。

## 边界

这些是同一规范实现基础上的六类受控机制案例，用于验证软件的检测、定位和修复链路，不代表六套独立ML-KEM算法，也不据此声称任意第三方源码均可自动修复。
