"""Produce a report-friendly summary strictly from saved experiment results."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
results=ROOT/'results/software'
source_path=sorted(results.glob('*-external-source/report.json'))[-1]
timing_path=sorted(results.glob('*-external-timing/report.json'))[-1]
source=json.loads(source_path.read_text());timing=json.loads(timing_path.read_text())
lines=['# 外部源码修复与程序交付验收','',f'软件目录：`{ROOT}`','',
       '三类工程均为同一源码家族的受控变体，经外部接入界面同一服务路径导入。','',
       '| 外部工程 | 原程序向量 | 修复程序向量 | 交付包解压重编译向量 |',
       '|---|---:|---:|---:|']
for c in source['cases']:
    phases=[c['basic'],c['patch']['correctness'],c['rebuild_and_vector_validation']]
    assert all(d['success'] for d in phases)
    lines.append('|'+c['kind']+'|'+'|'.join(f"{d['vectors']['passed']}/{d['vectors']['total']}" for d in phases)+'|')
lines+=['','每次完整验证同时包含512/768/1024各100次随机流程自测。',
        '', '| 工程 | 修复前平均绝对配对差ns | 修复后ns | 前/后环境及对照通过 | 本轮支持改善 |',
        '|---|---:|---:|---|---|']
for c in timing['cases']:
    r=c['repair']
    lines.append(f"|{c['target_id']}|{r['mean_abs_diff_before_ns']:.2f}|{r['mean_abs_diff_after_ns']:.2f}|{r['before']['formal_environment']}/{r['after']['formal_environment']}|{r['effect_confirmed']}|")
lines+=['','每类修复前后各3轮，每轮10000对解封装调用，另有同规模A/A相同输入对照。',
        '效果未确认的轮次保留；不能只凭均值降低下结论。功能通过不等于证明绝对常数时间。','',
        '负向检查：'+', '.join(source['negative_checks'])+'。','',
        f'源码验收：`{source_path}`',f'计时验收：`{timing_path}`','',
        '适用范围：mlkem-native SCU构建适配器；完整匹配的比较早退和条件拒绝派生路径。任意实现、汇编、其他错误处理需另行适配。',
        '交付：ZIP含源码、实测库、补丁、构建脚本、验证报告、原始计时证据包及文件摘要；不含实验样本私有材料。','']
receipt=ROOT/'EXTERNAL_REPAIR_ACCEPTANCE.md';receipt.write_text('\n'.join(lines),encoding='utf-8')
print('\n'.join(lines));print('RECEIPT',receipt)
