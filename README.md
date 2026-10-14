# ML-KEM 解封装时间侧信道检测与常数时间防护软件（最终版）

> 最终版本：`final-2026-10-14`。队员总览、功能清单、验收结果与答辩统一口径见 [FINAL_PROJECT_GUIDE.md](FINAL_PROJECT_GUIDE.md)。

本目录是桌面交付版本，入口为 `./run_desktop.sh`（`desktop_app/software.py`）。
前端与计算任务在同一台 Linux/WSL 主机执行，不依赖浏览器、HTTP 服务或校园网服务器地址。

从工作台进入三个主要任务：基本 ML-KEM 功能、时间检测与防护、输入样本生成。
环境自检、七个内置机制案例、外部库接入、向量验证、原生 C 计时、源码/二进制候选定位、六类模式化修复、回归验证和证据导出均有独立页面。

使用说明、C ABI、适用范围和验收命令见 [docs/SOFTWARE.md](docs/SOFTWARE.md)。
时间检测页可选函数级插桩，独立展示阶段辅助分析、A/A对照和诊断构建净开销；见 [docs/FUNCTION_TRACE.md](docs/FUNCTION_TRACE.md)。默认不开启，不替换原始库的正式计时。
实际验收结果在 `results/software/`，桌面窗口截图在 `results/software/ui-verification/`。
跨运行环境与GCC/Clang、-O2/-O3/-Os验证见 [docs/CROSS_ENVIRONMENT_AND_BUILD_VALIDATION_2026-10-13.md](docs/CROSS_ENVIRONMENT_AND_BUILD_VALIDATION_2026-10-13.md)。
六类受控机制的检测、定位、修复与同参数复测验收见 [docs/SIX_CASE_CLOSURE_2026-10-13.md](docs/SIX_CASE_CLOSURE_2026-10-13.md)。

## 服务器现有安装

```bash
cd /disk4/lsm/A1-13-MLKEM-Software-20261012
./run_desktop.sh
```

需在有显示服务的图形会话启动。无桌面服务器可以运行自动化验收，或配置图形会话/显示转发。
项目保留了早期代码供溯源，旧网页入口不属于本次软件启动路径。原服务器平台目录未覆盖。

## 验收边界

- 内置项由一个规范基线和六类受控机制案例构成，属于同一代码基础，不是七套独立算法。
- 内置目标逐项执行435项官方向量（按参数集筛选）；外部目标缺少确定性扩展接口时回退到60项解封装向量并注明范围。
- 自动修复覆盖完整匹配的比较提前结束、条件失败路径、数据相关循环、数据相关访存、条件分支和运行期除法。外部源码选择受支持构建适配器并重新编译，与输入库摘要完全一致后，可执行修复、功能回归、同样本复测和程序包导出。
- 功能通过、统计显著、修复效果得到支持是三个不同状态，分别记录。
- 报告不会用“未检出差异”宣称绝对安全或常数时间证明。

外部源码接入步骤和交付内容见 [docs/EXTERNAL_REPAIR.md](docs/EXTERNAL_REPAIR.md)。本轮服务器验收见 [EXTERNAL_REPAIR_ACCEPTANCE.md](EXTERNAL_REPAIR_ACCEPTANCE.md)。
