# 外部源码修复与程序交付验收

软件目录：`/disk4/lsm/A1-13-MLKEM-Software-20261012`

三类工程均为同一源码家族的受控变体，经外部接入界面同一服务路径导入。

| 外部工程 | 原程序向量 | 修复程序向量 | 交付包解压重编译向量 |
|---|---:|---:|---:|
|compare|435/435|435/435|435/435|
|rejection|435/435|435/435|435/435|
|combined|435/435|435/435|435/435|

每次完整验证同时包含512/768/1024各100次随机流程自测。

| 工程 | 修复前平均绝对配对差ns | 修复后ns | 前/后环境及对照通过 | 本轮支持改善 |
|---|---:|---:|---|---|
|custom_compare_0f46ce|285.45|9.49|True/True|False|
|custom_rejection_2e1030|2628.44|7.55|True/True|True|
|custom_combined_289a7f|2417.39|5.60|False/False|False|

每类修复前后各3轮，每轮10000对解封装调用，另有同规模A/A相同输入对照。
效果未确认的轮次保留；不能只凭均值降低下结论。功能通过不等于证明绝对常数时间。

负向检查：compare:source_tamper_rejected, compare:stale_program_export_rejected, unknown_compare_refused, rejection:source_tamper_rejected, rejection:stale_program_export_rejected, combined:source_tamper_rejected, combined:stale_program_export_rejected, binary_mismatch_rejected。

源码验收：`/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-205428-ec52aa0d-external-source/report.json`
计时验收：`/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-205456-3b623cd3-external-timing/report.json`

适用范围：mlkem-native SCU构建适配器；完整匹配的比较早退和条件拒绝派生路径。任意实现、汇编、其他错误处理需另行适配。
交付：ZIP含源码、实测库、补丁、构建脚本、验证报告、原始计时证据包及文件摘要；不含实验样本私有材料。
