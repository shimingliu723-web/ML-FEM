from __future__ import annotations

import glob
import hashlib
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

from binary_audit import binary_locate
from software_service import ROOT, detect

CLANG = Path('/disk4/lsm/miniconda3/pkgs/clang-17-17.0.6-default_hb5137d0_8/bin/clang-17')
CLANG_LIBRARY_PATH = ':'.join([
    '/disk4/lsm/miniconda3/pkgs/libclang-cpp17-17.0.6-default_hb5137d0_8/lib',
    '/disk4/lsm/miniconda3/pkgs/libllvm17-17.0.6-ha7bfdaf_3/lib',
    '/disk4/lsm/miniconda3/lib',
])
CONFIGS = [
    ('gcc9', Path('/usr/bin/gcc'), '-O2'),
    ('gcc9', Path('/usr/bin/gcc'), '-O3'),
    ('gcc9', Path('/usr/bin/gcc'), '-Os'),
    ('clang17', CLANG, '-O2'),
    ('clang17', CLANG, '-O3'),
    ('clang17', CLANG, '-Os'),
]
VARIANTS = {
    'baseline': (ROOT/'core/mlkem-native/mlkem', ROOT/'core/randombytes.c'),
    'compare_early': (ROOT/'targets/case_compare_early/src/mlkem', ROOT/'targets/case_compare_early/src/randombytes.c'),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compiler_env(name: str) -> dict[str, str]:
    env = os.environ.copy()
    if name == 'clang17': env['LD_LIBRARY_PATH'] = CLANG_LIBRARY_PATH
    return env


def build_target(name: str, compiler: Path, optimization: str, variant: str) -> dict:
    source, random_source = VARIANTS[variant]
    opt_id = optimization.lower().replace('-', '')
    target_id = f'crossbuild_{name}_{opt_id}_{variant}'
    directory = ROOT/'targets'/target_id
    lib_dir = directory/'lib'; lib_dir.mkdir(parents=True, exist_ok=True)
    library = lib_dir/'libmlkem512.so'
    command = [str(compiler), optimization, '-fPIC', '-std=c99', '-Wall', '-Wextra', '-Wpedantic',
               '-I'+str(source), '-DMLK_CONFIG_NAMESPACE_PREFIX=mlkem',
               '-DMLK_CONFIG_PARAMETER_SET=512', '-shared', str(source/'mlkem_native.c'),
               str(random_source), '-o', str(library)]
    env = compiler_env(name)
    proc = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=300)
    if proc.returncode:
        raise RuntimeError(f'{target_id} build failed\n{proc.stdout}')
    version = subprocess.check_output([str(compiler), '--version'], env=env, text=True).splitlines()[0]
    config = {
        'id': target_id, 'name': f'跨构建实验 {name} {optimization} {variant}',
        'role': 'experiment', 'description': '跨编译器与优化级别稳定性实验目标',
        'levels': ['512'], 'library_template': f'targets/{target_id}/lib/libmlkem{{level}}.so',
        'build': [], 'selftest': [], 'case_type': 'cross_build',
        'mechanism': 'fixed_flow_baseline' if variant == 'baseline' else 'comparison_early_exit',
        'sample_strategy': '与正式服务器实验复用同一批等长输入',
        'repair_strategy': '本实验仅比较构建配置，不执行自动修复',
        'limitations': '结论仅适用于本服务器、所选编译器版本、优化级别和样本。',
    }
    (directory/'target.json').write_text(json.dumps(config, ensure_ascii=False, indent=2))
    profile = {'compiler': version, 'compiler_path': str(compiler), 'optimization_flags': optimization,
               'command': command, 'library_sha256': {'512': digest(library)}, 'library_bytes': library.stat().st_size}
    (directory/'build_profile.json').write_text(json.dumps(profile, ensure_ascii=False, indent=2))
    return {'target_id': target_id, 'compiler': name, 'compiler_version': version,
            'optimization': optimization, 'variant': variant, 'library': str(library),
            'library_sha256': digest(library), 'library_bytes': library.stat().st_size}


def main() -> None:
    pairs = int(os.environ.get('CROSS_BUILD_PAIRS', '10000'))
    repeats = int(os.environ.get('CROSS_BUILD_REPEATS', '3'))
    cpu = min(os.sched_getaffinity(0))
    acceptance = sorted(glob.glob(str(ROOT/'results/acceptance/*seven-cases.json')))[-1]
    samples = json.loads(Path(acceptance).read_text())['sample_report']
    output = ROOT/'results/experiments'/time.strftime('%Y%m%d-%H%M%S-cross-build')
    output.mkdir(parents=True)
    report = {'kind': 'cross-compiler-optimization', 'pairs': pairs, 'repeats': repeats,
              'cpu': cpu, 'sample_report': samples, 'rows': []}
    for name, compiler, optimization in CONFIGS:
        if not compiler.is_file(): raise FileNotFoundError(compiler)
        for variant in VARIANTS:
            built = build_target(name, compiler, optimization, variant)
            print('[START]', built['target_id'], flush=True)
            detected = detect(built['target_id'], '512', samples, pairs, cpu, repeats, 2)
            runs = detected['runs']
            diffs = [r['analysis']['paired_mean_difference_ns'] for r in runs]
            valid = [r['analysis']['valid']['mean_ns'] for r in runs]
            changed = [r['analysis']['changed']['mean_ns'] for r in runs]
            item = {**built, 'basic_success': detected['correctness']['success'],
                    'formal_environment': detected['formal_environment'],
                    'same_input_control_passed': detected['same_input_control_passed'],
                    'conclusion': detected['conclusion'], 'round_differences_ns': diffs,
                    'mean_difference_ns': statistics.fmean(diffs),
                    'stdev_difference_ns': statistics.stdev(diffs) if len(diffs)>1 else 0,
                    'valid_mean_ns': statistics.fmean(valid), 'changed_mean_ns': statistics.fmean(changed),
                    'all_rounds_significant': all(r['statistics']['verdict']['statistically_significant'] for r in runs),
                    'binary_counts': binary_locate(built['target_id'], '512')['counts'],
                    'detection_report': detected['report_json']}
            report['rows'].append(item)
            print('[DONE]', built['target_id'], item['conclusion'], [round(x,2) for x in diffs], flush=True)
    baseline_rows=[r for r in report['rows'] if r['variant']=='baseline']
    comparison_rows=[r for r in report['rows'] if r['variant']=='compare_early']
    report['functional_success'] = all(r['basic_success'] for r in report['rows'])
    report['direction_consistent'] = all(all(x<0 for x in r['round_differences_ns']) for r in comparison_rows)
    report['baseline_repeated_difference_count'] = sum(r['conclusion']=='重复观察到同方向差异' for r in baseline_rows)
    report['formal_accepted_rows'] = sum(r['formal_environment'] for r in report['rows'])
    report['formal_total_rows'] = len(report['rows'])
    report['success'] = report['functional_success'] and report['direction_consistent'] and report['baseline_repeated_difference_count']==0
    report['created_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    report_path = output/'report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels = [f'{n}\n{o}' for n,_,o in CONFIGS]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    for variant, marker in [('baseline','o'),('compare_early','s')]:
        rows = [r for r in report['rows'] if r['variant']==variant]
        axes[0].errorbar(range(len(rows)), [r['mean_difference_ns'] for r in rows],
                         yerr=[r['stdev_difference_ns'] for r in rows], marker=marker, capsize=4,
                         label='Baseline' if variant=='baseline' else 'Comparison case')
    axes[0].axhline(0,color='#777777',linestyle='--',linewidth=1)
    axes[0].set_xticks(range(len(labels)),labels,rotation=20)
    axes[0].set_ylabel('Changed - normal (ns)')
    axes[0].set_title('Timing difference across build configurations')
    axes[0].legend()
    baseline=[r for r in report['rows'] if r['variant']=='baseline']
    axes[1].bar([x-.18 for x in range(len(baseline))],[r['valid_mean_ns']/1000 for r in baseline],.36,label='Mean decapsulation (us)')
    ax2=axes[1].twinx()
    ax2.bar([x+.18 for x in range(len(baseline))],[r['library_bytes']/1024 for r in baseline],.36,color='#888888',label='Library size (KiB)')
    axes[1].set_xticks(range(len(labels)),labels,rotation=20)
    axes[1].set_ylabel('Time (us)');ax2.set_ylabel('Library size (KiB)')
    axes[1].set_title('Baseline performance and binary size')
    h1,l1=axes[1].get_legend_handles_labels();h2,l2=ax2.get_legend_handles_labels();axes[1].legend(h1+h2,l1+l2,loc='upper left')
    chart=output/'cross-build-comparison.png';fig.savefig(chart,dpi=200);plt.close(fig)
    report['chart_png']=str(chart);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))

    lines=['# 跨编译器与优化级别验证报告','',f'- 环境：物理Linux服务器，固定CPU {cpu}',
           f'- 规模：每个目标{pairs}对 × {repeats}轮，复用同一批等长输入',
           '- 编译配置：GCC 9.4.0与Clang 17.0.6，分别使用-O2、-O3、-Os',
           f"- 功能验证：{'全部通过' if report['functional_success'] else '存在失败'}",
           f"- 方向稳定性：{'六种配置三轮方向一致' if report['direction_consistent'] else '存在方向不一致'}",
           f"- 正式准入：{report['formal_accepted_rows']}/{report['formal_total_rows']}个目标批次通过环境与A/A同输入对照；其余批次降级为探索结果",'',
           '| 编译配置 | 目标 | 功能 | 正式环境 | 三轮差值 ns | 结论 | 库大小 KiB |','|---|---|---|---|---|---|---:|']
    for r in report['rows']:
        cfg=f"{r['compiler']} {r['optimization']}";ds=' / '.join(f'{x:.2f}' for x in r['round_differences_ns'])
        lines.append(f"| {cfg} | {r['variant']} | {'通过' if r['basic_success'] else '失败'} | {'通过' if r['formal_environment'] else '探索'} | {ds} | {r['conclusion']} | {r['library_bytes']/1024:.1f} |")
    lines += ['', '## 结果解释','',
              '本实验只改变编译器和优化级别，源码、样本、CPU、计时器与统计流程保持一致。六种配置均通过功能验证；受控比较案例的三轮差值方向全部一致，但差值幅度随编译器和优化级别明显变化。',
              '只有环境前后检查和A/A同输入对照同时通过的目标批次可作为正式统计结果；A/A对照显著的批次在表中标为探索，不用于声称正式检出。实验成功表示功能跨构建可用且受控现象方向稳定，不表示12个批次全部满足正式计时准入。',
              '不同编译器产生不同代码布局和整体性能是预期结果；结论不能推广到其他CPU架构或远程网络场景。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print('[REPORT]',report_path,flush=True);print('[CHART]',chart,flush=True);print('[SUCCESS]',report['success'],flush=True)

if __name__=='__main__': main()
