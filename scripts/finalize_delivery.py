"""Derive delivery notes and a source bundle from actual acceptance results."""
import json,hashlib,tarfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'results/software'
def latest(suffix):
    path=sorted(RESULTS.glob('*-'+suffix+'/report.json'))[-1]
    return path,json.loads(path.read_text())
basic_path,basic=latest('acceptance-basic');timing_path,timing=latest('acceptance-timing')
ui_path=RESULTS/'ui-verification/ui_check.json';ui=json.loads(ui_path.read_text());assert ui['success']
builtins=[c['result'] for c in basic['checks'] if c['name']!='external_import']
assert len(builtins)==7 and all(r['success'] for r in builtins)
assert all(r['vectors']['total']==435 for r in builtins)
timings=[c for c in timing['checks'] if c['name'].startswith('timing_')]
repairs=[c for c in timing['checks'] if c['name'].startswith('repair_')]
assert len(timings)==7 and len(repairs)==3
for c in repairs:
    r=c['result'];assert r['success'] and r['patch']['correctness']['success']
    assert r['patch']['correctness']['vectors']['total']==435
    for before,after in zip(r['before']['runs'],r['after']['runs']):
        assert all(before[k]==after[k] for k in ['sample_sha256','seed','category','pairs','cpu','level'])

def assert_no_private_fields(value):
    if isinstance(value,dict):
        assert not {'sk','dk','secret_key','shared_secret','actual_shared_secret','encapsulated_secret','decapsulated_secret'} & set(value)
        for item in value.values():assert_no_private_fields(item)
    elif isinstance(value,list):
        for item in value:assert_no_private_fields(item)
assert_no_private_fields(basic);assert_no_private_fields(timing)
for c in timing['checks']:
    if c['name'].startswith('export_'):
        with zipfile.ZipFile(c['result']['zip']) as archive:
            for entry in json.loads(archive.read('manifest.json')):
                assert hashlib.sha256(archive.read(entry['file'])).hexdigest()==entry['sha256']
            assert not any(n.endswith(('inputs.bin','samples.csv')) for n in archive.namelist())

lines=['# 软件版交付与验收记录','',f'服务器目录：`{ROOT}`','',
 '启动：在本机图形会话执行 `./run_desktop.sh`。前端与计算任务在同一主机运行。','',
 '原平台目录没有覆盖；未推送 GitHub。当前交付包含桌面软件、源码、结果文件、原始计时、补丁、图表与实际 Qt 窗口截图。','',
 '## 功能与界面验收','',
 '- 七个内置目标各完成三个参数集100次自测，共2100次；均通过。',
 '- 七个内置目标各执行同一官方库435项，共3045次向量执行；均通过。',
 '- 外部接入使用基线动态库副本，验证符号检查和实际调用链；不能据此称为新增独立实现。',
 '- Qt界面通过真实子进程依次运行：'+', '.join(ui['worker_actions'])+'。',
 '- 三个修复产物均通过全部参数集自测和435项官方向量。',
 '- 修复前后逐轮核对了样本摘要、种子、类别、次数、CPU和参数集一致。',
 '- 所有最新导出ZIP的文件摘要验证通过，未包含样本秘密材料。','',
 '## 七目标计时实测','',
 '|目标|轮数×配对数|同输入对照|环境准入|实测结论|','|---|---|---|---|---|']
for c in timings:
    d=c['result'];lines.append(f"|{d['target_id']}|{len(d['runs'])} × {d['runs'][0]['pairs']}|{d.get('same_input_control_passed')}|{d['formal_environment']}|{d['conclusion']}|")
lines += ['','每轮另有同规模A/A对照；未通过对照或环境检查的结果只作探索。小差异与重复结果不一致均保留，不删除失败轮次。','',
 '## 三种修复闭环','',
 '|目标|修复前平均绝对差ns|修复后平均绝对差ns|功能回归|严格计时效果验收|','|---|---:|---:|---|---|']
for c in repairs:
    d=c['result'];lines.append(f"|{d['target_id']}|{d['mean_abs_diff_before_ns']:.2f}|{d['mean_abs_diff_after_ns']:.2f}|通过|{'通过' if d['effect_confirmed'] else '未满足；需继续复测'}|")
lines += ['','功能闭环已跑通不等于所有计时效果都已通过。不能将此表改写成“全部消除差异”或“对所有ML-KEM均有效”。','',
 '## 适用范围','',
 '- 源码自动修复覆盖已适配的三种比较写法；其他结构给出人工适配提示。',
 '- 外部动态库有统一C接口即可进行正确性和计时检测；可选源码用于已适配结构定位。',
 '- 二进制页面提供候选控制流证据，不等于自动敏感数据流证明。',
 '- 本次有512/768/1024对照；跨架构、远程网络和不同优化级别实验没有在本轮新增。',
 '- 环境分级是工程预检，不能保证测量无噪声；未检出不等于常数时间证明。',
 '- 创新效果的独立基线对照论证仍需在竞赛报告中另行完成。','',
 '## 可追溯文件','',f'- 基础验收：`{basic_path}`',f'- 计时与修复验收：`{timing_path}`',f'- 界面验收：`{ui_path}`',
 '- 使用及接口说明：`docs/SOFTWARE.md`','- 桌面窗口截图：`results/software/ui-verification/`','']
(ROOT/'DELIVERY.md').write_text('\n'.join(lines),encoding='utf-8')
bundle=ROOT/'MLKEM-Software-source.tar.gz'
roots=['backend','core','data','desktop_app','experiments','targets','tests','docs']
with tarfile.open(bundle,'w:gz') as tar:
    for name in roots:
        for path in (ROOT/name).rglob('*'):
            if not path.is_file() or path.is_symlink():continue
            if any(x in path.parts for x in ['__pycache__','.git','.acvp-data']):continue
            if path.suffix in ['.pyc','.so'] or path.name=='server.py':continue
            if name=='targets' and ('custom_' in str(path.relative_to(ROOT/'targets')) or 'repair_' in str(path.relative_to(ROOT/'targets'))):continue
            if name=='experiments' and path.suffix not in ['.c','.h']:continue
            tar.add(path,arcname='MLKEM-Software/'+str(path.relative_to(ROOT)))
    for name in ['Makefile','README.md','DELIVERY.md','requirements-desktop.txt','requirements-desktop-lock.txt','run_desktop.sh']:
        tar.add(ROOT/name,arcname='MLKEM-Software/'+name)
    for name in ['prepare_software.py','accept_software.py','check_desktop.py','finalize_delivery.py']:
        tar.add(ROOT/'scripts'/name,arcname='MLKEM-Software/scripts/'+name)
print('\n'.join(lines));print('SOURCE_BUNDLE',bundle)
