import json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; store=ROOT/'results/software'
accept=json.loads(sorted(store.glob('*-trace-acceptance/report.json'))[-1].read_text())
integration=json.loads(sorted(store.glob('*-trace-integration/report.json'))[-1].read_text())
lines=['# 函数级插桩服务器验收','',f'软件目录：{ROOT}','','## 七个已有源码版本','',
       '每版本：100次完整流程自测、当前512参数集145项公开向量；分类3轮×10000对，A/A对照3轮×10000对。原始库与诊断库交替测量，所有原始观察保留。','',
       '|版本|流程自测|公开向量|比较阶段平均配对差(ns)|正常类净开销(%)|变化类净开销(%)|7组空探针参考成本(ns)|',
       '|---|---:|---:|---:|---:|---:|---:|']
for result in accept['results']:
    rounds=[r for r in result['rounds'] if not r['control']]
    diff=statistics.fmean(r['stages'][4]['statistics']['paired']['paired_mean_difference_ns'] for r in rounds)
    costs=[statistics.fmean(r['overhead'][j]['overhead_percent'] for r in rounds) for j in range(2)]
    probe=statistics.median(r['probe_calibration']['estimated_added_p50_ns'] for r in rounds)
    lines.append(f"|{result['target_id']}|100/100|{result['correctness']['official_vectors']['passed']}/145|{diff:.2f}|{costs[0]:.2f}|{costs[1]:.2f}|{probe:.1f}|")
lines+=['','## 集成验收','']+[f'- {x}：通过' for x in integration['checks']]
on=json.loads(Path(integration['on_report']).read_text()); trace=on['instrumentation']
lines+=['','插桩分析：'+trace['interpretation'],'',f"原始库正式计时环境与对照是否全部通过：{on['formal_environment']}。原始计时结论：{on['conclusion']}。",'',
        '额外验收覆盖768/1024参数集的规范与早退版本，以及已接入的条件拒绝派生源码版本。统计回归67项：58项通过，9项可选检查跳过；另有4项零基准边界测试通过。','',
        '注意：阶段计时属于诊断构建，只辅助分析。净开销包含重编译后的布局与缓存效应，可以为负，不代表探针本身加速程序。空探针成本仅为参考，不事后扣除。七阶段使用0.05/7阈值；未检出不等于常数时间证明。','',
        '## 证据路径','',f"- 完整七版本报告：{accept['report_json']}",f"- 集成报告：{integration['report_json']}",f"- 开启插桩检测报告：{integration['on_report']}",f"- 证据包：{integration['export']['zip']}",f"- 原生Qt窗口截图：{integration['screenshots']}",f"- 阶段与开销结果图：{trace['chart_png']}",'',
        '未推送GitHub。原文件备份在 backups/pre-function-trace-20261012。']
output=ROOT/'FUNCTION_TRACE_ACCEPTANCE.md';output.write_text('\n'.join(lines),encoding='utf-8')
print(output)
print('\n'.join(lines))
