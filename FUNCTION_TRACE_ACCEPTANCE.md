# 函数级插桩服务器验收

软件目录：/disk4/lsm/A1-13-MLKEM-Software-20261012

## 七个已有源码版本

每版本：100次完整流程自测、当前512参数集145项公开向量；分类3轮×10000对，A/A对照3轮×10000对。原始库与诊断库交替测量，所有原始观察保留。

|版本|流程自测|公开向量|比较阶段平均配对差(ns)|正常类净开销(%)|变化类净开销(%)|7组空探针参考成本(ns)|
|---|---:|---:|---:|---:|---:|---:|
|mlkem_native_baseline|100/100|145/145|0.03|2.22|2.24|832.0|
|variant_early_return|100/100|145/145|-142.25|-3.54|-3.08|832.0|
|variant_early_return_while|100/100|145/145|-141.27|-3.44|-3.04|832.0|
|variant_early_return_xor|100/100|145/145|-141.74|-3.50|-3.01|830.5|
|variant_repaired|100/100|145/145|0.06|2.18|2.19|832.0|
|variant_repaired_while|100/100|145/145|-0.02|2.21|2.20|832.0|
|variant_repaired_xor|100/100|145/145|0.02|2.20|2.20|832.0|

## 集成验收

- optional-on-off：通过
- original-unchanged：通过
- temporary-inputs-deleted：通过
- other-parameter-sets：通过
- evidence-exports：通过
- qt-stage-and-overhead-tables：通过
- selection-clears-stale-results：通过

插桩分析：重复差异候选：完整输入比较、最终结果选择；仅辅助分析。开销为诊断构建净耗时变化，可受代码布局影响而为负；空探针成本另见报告。

原始库正式计时环境与对照是否全部通过：True。原始计时结论：重复观察到同方向差异。

额外验收覆盖768/1024参数集的规范与早退版本，以及已接入的条件拒绝派生源码版本。统计回归67项：58项通过，9项可选检查跳过；另有4项零基准边界测试通过。

注意：阶段计时属于诊断构建，只辅助分析。净开销包含重编译后的布局与缓存效应，可以为负，不代表探针本身加速程序。空探针成本仅为参考，不事后扣除。七阶段使用0.05/7阈值；未检出不等于常数时间证明。

## 证据路径

- 完整七版本报告：/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-214020-7f303314-trace-acceptance/report.json
- 集成报告：/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-214113-5e6bde4b-trace-integration/report.json
- 开启插桩检测报告：/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-214043-8e8b6dbc-detection/report.json
- 证据包：/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-214111-60378b49-export/evidence.zip
- 原生Qt窗口截图：/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-214113-793c7b35-trace-ui
- 阶段与开销结果图：/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-214029-7c5d1e55-function-trace/instrumentation.png

未推送GitHub。原文件备份在 backups/pre-function-trace-20261012。