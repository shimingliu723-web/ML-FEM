# 软件版交付与验收记录

服务器目录：`/disk4/lsm/A1-13-MLKEM-Software-20261012`

启动：在本机图形会话执行 `./run_desktop.sh`。前端与计算任务在同一主机运行。

本文件记录本机验收。原平台目录没有覆盖；GitHub源码与服务器运行结果分别保存。新增外部源码修复与交付验收见 EXTERNAL_REPAIR_ACCEPTANCE.md。

## 功能与界面验收

- 七个内置目标各完成三个参数集100次自测，共2100次；均通过。
- 七个内置目标各执行同一官方库435项，共3045次向量执行；均通过。
- 外部接入使用基线动态库副本，验证符号检查和实际调用链；不能据此称为新增独立实现。
- Qt界面通过真实子进程依次运行：basic, environment, samples, detect, locate, repair, export。
- 三个修复产物均通过全部参数集自测和435项官方向量。
- 修复前后逐轮核对了样本摘要、种子、类别、次数、CPU和参数集一致。
- 所有最新导出ZIP的文件摘要验证通过，未包含样本秘密材料。

## 七目标计时实测

|目标|轮数×配对数|同输入对照|环境准入|实测结论|
|---|---|---|---|---|
|mlkem_native_baseline|3 × 10000|True|True|本次各轮未检出显著差异|
|variant_early_return|3 × 10000|False|False|重复观察到同方向差异|
|variant_early_return_while|3 × 10000|False|False|重复观察到同方向差异|
|variant_early_return_xor|3 × 10000|True|False|重复观察到同方向差异|
|variant_repaired|3 × 10000|False|False|本次各轮未检出显著差异|
|variant_repaired_while|3 × 10000|False|False|本次各轮未检出显著差异|
|variant_repaired_xor|3 × 10000|True|True|轮次结果不一致或轮数不足，需要进一步复测|

每轮另有同规模A/A对照；未通过对照或环境检查的结果只作探索。小差异与重复结果不一致均保留，不删除失败轮次。

## 三种修复闭环

|目标|修复前平均绝对差ns|修复后平均绝对差ns|功能回归|严格计时效果验收|
|---|---:|---:|---|---|
|variant_early_return|297.43|6.42|通过|通过|
|variant_early_return_while|303.27|6.37|通过|通过|
|variant_early_return_xor|298.20|5.42|通过|通过|

功能闭环已跑通不等于所有计时效果都已通过。不能将此表改写成“全部消除差异”或“对所有ML-KEM均有效”。

## 适用范围

- 源码修复覆盖完整匹配的三种比较写法和条件拒绝派生路径；其他结构需人工适配。
- 外部动态库通过统一C接口检测；支持的外部源码经重编译与输入库摘要完全一致后可修复，并导出完整程序包。
- 二进制页面提供候选控制流证据，不等于自动敏感数据流证明。
- 本次有512/768/1024对照；跨架构、远程网络和不同优化级别实验没有在本轮新增。
- 环境分级是工程预检，不能保证测量无噪声；未检出不等于常数时间证明。
- 创新效果的独立基线对照论证仍需在竞赛报告中另行完成。

## 可追溯文件

- 基础验收：`/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-180046-f214370c-acceptance-basic/report.json`
- 计时与修复验收：`/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/20261012-181520-f878b0c7-acceptance-timing/report.json`
- 界面验收：`/disk4/lsm/A1-13-MLKEM-Software-20261012/results/software/ui-verification/ui_check.json`
- 使用及接口说明：`docs/SOFTWARE.md`
- 桌面窗口截图：`results/software/ui-verification/`
