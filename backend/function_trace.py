"""Opt-in diagnostic builds; never replaces the selected original binary."""
import base64
import csv
import json
import os
import re
import shutil
import statistics
import struct
import subprocess
from pathlib import Path

BASE_STAGES = ['私钥结构检查','内部解密','派生重加密材料','重加密','完整输入比较','拒绝材料派生','最终结果选择']
MECHANISM_STAGES = {
    'mlkem_native_baseline': '基线比较观察点',
    'case_compare_early': '比较提前结束观察点',
    'case_conditional_failure': '条件失败路径观察点',
    'case_variable_loop': '数据相关循环观察点',
    'case_memory_index': '数据相关访存观察点',
    'case_conditional_branch': '数据相关分支观察点',
    'case_variable_division': '运行期除法观察点',
}
RUNTIME = r'''
#define _GNU_SOURCE
#include <stdint.h>
#include <time.h>
#include <stdlib.h>
static _Thread_local uint64_t started[8],elapsed[8];
static uint64_t tick(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC_RAW,&t))abort();return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
void mlkem_trace_begin(int i){started[i]=tick();}
void mlkem_trace_end(int i){elapsed[i]+=tick()-started[i];}
void mlkem_trace_reset(void){for(int i=0;i<8;i++)elapsed[i]=0;}
void mlkem_trace_read(uint64_t*out){for(int i=0;i<8;i++)out[i]=elapsed[i];}
'''

def _wrap_once(text, needle, before, after, label):
    if text.count(needle) != 1:
        raise ValueError('不支持的源码布局：'+label)
    return text.replace(needle, before+needle+after, 1)

def _instrument_mechanism(source, target_id):
    """Add the eighth, case-specific probe without changing algorithm outputs."""
    begin='mlkem_trace_begin(7); '
    end=' mlkem_trace_end(7);'
    kem=source/'mlkem/src/kem.c'
    verify=source/'mlkem/src/verify.h'
    compress=source/'mlkem/src/compress.h'
    if target_id in ('mlkem_native_baseline','case_compare_early'):
        text=kem.read_text()
        needle='fail = mlk_ct_memcmp(ct, tmp, MLKEM_INDCCA_CIPHERTEXTBYTES);'
        kem.write_text(_wrap_once(text,needle,begin,end,'比较观察点'))
    elif target_id=='case_conditional_failure':
        text=kem.read_text()
        needle='''if (fail == 0) {
  mlk_memcpy(ss, kr, MLKEM_SYMBYTES);
} else {
  mlk_memcpy(tmp, sk + MLKEM_INDCCA_SECRETKEYBYTES - MLKEM_SYMBYTES, MLKEM_SYMBYTES);
mlk_memcpy(tmp + MLKEM_SYMBYTES, ct, MLKEM_INDCCA_CIPHERTEXTBYTES);
mlk_hash_j(ss, tmp, MLKEM_SYMBYTES + MLKEM_INDCCA_CIPHERTEXTBYTES);
}'''
        kem.write_text(_wrap_once(text,needle,begin,end,'条件失败路径'))
    elif target_id=='case_variable_loop':
        text=verify.read_text()
        needle='''size_t rounds = r ? 64u : 4096u;
  for (i = 0; i < rounds; i++) { sink ^= (uint8_t)i; }'''
        verify.write_text(_wrap_once(text,needle,begin,end,'数据相关循环'))
    elif target_id=='case_memory_index':
        text=verify.read_text()
        needle='''size_t case_stride = (size_t)(r != 0) * 8192u;
  for (i = 0; i < 4096u; i++) {
    observed ^= case_table[(i * case_stride) & 4194303u];
  }'''
        verify.write_text(_wrap_once(text,needle,begin,end,'数据相关访存'))
    elif target_id=='case_conditional_branch':
        text=kem.read_text()
        needle='''if (fail != 0) {
      for (case_i = 0; case_i < 1024u; case_i++) {
        case_marker = case_marker * 1664525u + 1013904223u + (uint32_t)case_i;
      }
    }'''
        kem.write_text(_wrap_once(text,needle,begin,end,'数据相关分支'))
    elif target_id=='case_variable_division':
        text=verify.read_text()
        needle='''if (r != 0) {
    for (i = 0; i < 1024u; i++) {
      quotient_sink ^= (0xf123456789abcdefULL + (uint64_t)i) / case_divisor;
    }
  }'''
        verify.write_text(_wrap_once(text,needle,begin,end,'运行期除法'))
    else:
        # User implementations retain the seven common stages until a mechanism adapter is supplied.
        return False
    for path in (kem,verify,compress):
        if path.is_file():
            text=path.read_text()
            if 'void mlkem_trace_begin(int);' not in text:
                path.write_text('void mlkem_trace_begin(int);\nvoid mlkem_trace_end(int);\n'+text)
    return True

def run_trace(target_id, level, sample_report, pairs, cpu, repeats, category):
    from software_service import ROOT, CLASSES, PARAMETERS, new_run, save, digest, load_samples, validate_basic
    from repair_manager import _source_root
    from target_manager import get_target
    from stats import compare_two_classes, percentile
    target=get_target(target_id)
    if not 100<=int(pairs)<=100000 or not 1<=int(repeats)<=10 or int(category) not in (1,2,3) or cpu not in os.sched_getaffinity(0):
        raise ValueError('插桩实验参数不合法')
    directory=new_run('function-trace')
    source=directory/'src'
    shutil.copytree(_source_root(target_id),source/'mlkem')
    random_source=ROOT/'core/randombytes.c' if target_id=='mlkem_native_baseline' else ROOT/'targets'/target_id/'src/randombytes.c'
    shutil.copy2(random_source,source/'randombytes.c')
    profile=ROOT/'targets'/target_id/'build_profile.json'
    optimization=json.loads(profile.read_text()).get('optimization_flags','-O3') if profile.exists() else '-O3'
    suffix=' -fPIC -std=c99 -Wall -Wextra -Wpedantic'
    if optimization.endswith(suffix): optimization=optimization[:-len(suffix)]
    if optimization not in ('-Os','-O2','-O3','-O1','-O0'): raise ValueError('插桩暂不支持该构建优化配置')
    flags=['gcc',optimization,'-fPIC','-std=c99','-Wall','-Wextra','-Wpedantic','-I'+str(source/'mlkem'),'-DMLK_CONFIG_NAMESPACE_PREFIX=mlkem','-DMLK_CONFIG_PARAMETER_SET='+level,'-shared',str(source/'mlkem/mlkem_native.c'),str(source/'randombytes.c')]
    rebuilt=directory/'original-rebuilt.so'
    subprocess.run(flags+['-o',str(rebuilt)],check=True,capture_output=True)
    original=target.library_for(level)
    if digest(rebuilt)!=digest(original): raise ValueError('源码重构与所选原始库摘要不一致，拒绝对无对应关系的源码插桩')
    mechanism_instrumented=_instrument_mechanism(source,target_id)
    kem=source/'mlkem/src/kem.c'; text=kem.read_text()
    start=text.index('int mlk_kem_dec('); body=text[start:]
    expressions=[r'ret\s*=\s*mlk_kem_check_sk\([^;]+;',r'ret\s*=\s*mlk_indcpa_dec\([^;]+;',r'mlk_hash_g\([^;]+;',r'ret\s*=\s*mlk_indcpa_enc\([^;]+;',r'fail\s*=\s*mlk_ct_memcmp\([^;]+;',r'mlk_hash_j\([^;]+;',r'mlk_ct_cmov_zero\([^;]+;|mlk_memcpy\(ss,\s*kr,\s*MLKEM_SYMBYTES\);']
    for i,pattern in enumerate(expressions):
        matches=list(re.finditer(pattern,body))
        if len(matches)!=1: raise ValueError('不支持的解封装源码布局：阶段'+str(i))
        m=matches[0]; body=body[:m.start()]+'mlkem_trace_begin('+str(i)+'); '+m.group()+' mlkem_trace_end('+str(i)+');'+body[m.end():]
    prefix='' if 'void mlkem_trace_begin(int);' in text else 'void mlkem_trace_begin(int);\nvoid mlkem_trace_end(int);\n'
    kem.write_text(prefix+text[:start]+body)
    stage_names=BASE_STAGES+[MECHANISM_STAGES.get(target_id,'用户实现机制观察点（未适配）')]
    runtime=source/'trace_runtime.c'; runtime.write_text(RUNTIME)
    instrumented=directory/'instrumented.so'
    command=flags+[str(runtime),'-o',str(instrumented)]
    subprocess.run(command,check=True,capture_output=True)
    # Functional acceptance uses the actual diagnostic library, not the original.
    from mlkem_service import MLKEM
    from software_vectors import validate_official
    engine=MLKEM(level,library_path=instrumented)
    passed=0
    for _ in range(100):
        kp=engine.keygen(record=False); en=engine.encaps(kp['public_key'],record=False); de=engine.decaps(en['ciphertext'],kp['secret_key'],record=False)
        passed+=en['shared_secret']==de['shared_secret']
    official=validate_official(target_id,[level],{level:instrumented})
    correctness={'roundtrips_passed':passed,'roundtrips_total':100,'official_vectors':official}
    if passed!=100 or not official or not official['success']: raise ValueError('插桩库功能或公开向量验证未通过')
    runner=directory/'trace_measure'
    subprocess.run(['gcc','-O2','-std=c11',str(ROOT/'experiments/function_trace_measure.c'),'-ldl','-o',str(runner)],check=True,capture_output=True)
    manifest,samples=load_samples(sample_report,level); params=PARAMETERS[level]
    rounds=[]
    for control in (True,False):
      for round_index in range(repeats):
        private=directory/'inputs.bin'; fd=os.open(private,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
          with os.fdopen(fd,'wb') as f:
            f.write(struct.pack('<I',len(samples)))
            for row in samples:
              for key,n in [('secret_key_b64',params.secret_key)]+[(k,params.ciphertext) for k in CLASSES]:
                raw=base64.b64decode(row['normal_b64' if control and key in CLASSES else key],validate=True)
                if len(raw)!=n: raise ValueError('输入长度不正确')
                f.write(raw)
          raw_csv=directory/f'{"control" if control else "classes"}-{round_index+1}.csv'
          subprocess.run(['taskset','-c',str(cpu),str(runner),str(original),str(instrumented),level,str(private),str(pairs),str(42+round_index),str(raw_csv),str(category)],check=True,capture_output=True,timeout=600)
        finally: private.unlink(missing_ok=True)
        with raw_csv.open() as f: data=list(csv.DictReader(f))
        calibration_csv=Path(str(raw_csv)+'.probes.csv')
        with calibration_csv.open() as f: calibration=list(csv.DictReader(f))
        empty=[int(r['empty_ns']) for r in calibration]; probes=[int(r['probe_pairs_ns']) for r in calibration]
        probe_calibration={'raw_csv':str(calibration_csv),'probe_pairs':8,'probe_pairs_p50_ns':percentile(probes,.5),'empty_p50_ns':percentile(empty,.5),'estimated_added_p50_ns':percentile(probes,.5)-percentile(empty,.5),'scope':'空探针参考成本，不等于实际调用中的精确开销；不从阶段观测值中扣除。'}
        values=lambda name:[int(r[name]) for r in data]
        order=values('order'); stage_results=[]; overhead=[]
        for i,name in enumerate(stage_names):
          a,b=values(f'valid_stage_{i}'),values(f'changed_stage_{i}')
          st=compare_two_classes(a,b,orders=order,alpha=.05/8)
          stage_results.append({'stage':name,'valid_mean_ns':statistics.fmean(a),'changed_mean_ns':statistics.fmean(b),'statistics':st})
        for cls in ('valid','changed'):
          a,b=values('original_'+cls+'_ns'),values('instrumented_'+cls+'_ns')
          overhead.append({'class':cls,'original_mean_ns':statistics.fmean(a),'instrumented_mean_ns':statistics.fmean(b),'original_p50_ns':percentile(a,.50),'instrumented_p50_ns':percentile(b,.50),'original_p95_ns':percentile(a,.95),'instrumented_p95_ns':percentile(b,.95),'overhead_percent':100*(statistics.fmean(b)/statistics.fmean(a)-1),'statistics':compare_two_classes(a,b,orders=values(cls+'_impl_order'))})
        rounds.append({'round':round_index+1,'control':control,'raw_csv':str(raw_csv),'raw_sha256':digest(raw_csv),'stages':stage_results,'overhead':overhead,'probe_calibration':probe_calibration,'cpu_migrations':sum(x!=cpu for x in values('cpu'))})
    if digest(original)!=digest(rebuilt): raise ValueError('实验期间原始库发生变化，拒绝接受结果')
    result={'kind':'function-trace','success':True,'target_id':target_id,'level':level,'pairs':pairs,'cpu':cpu,'repeats':repeats,'category':CLASSES[category],'sample_sha256':manifest['csv_sha256'],'original_sha256':digest(original),'rebuilt_sha256':digest(rebuilt),'instrumented_sha256':digest(instrumented),'source_binary_verified':True,'mechanism_instrumented':mechanism_instrumented,'stage_names':stage_names,'build_command':command,'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],'correctness':correctness,'rounds':rounds,'stage_alpha':.05/8,'scope':'独立诊断构建，阶段计时包括探针成本；仅辅助定位，不能代替原始库计时或证明常数时间。8个阶段使用Bonferroni阈值0.05/8；95%区间仅为逐项区间。零值表示该路径未执行该调用。仅记录时长、类别和公开实验元数据，不记录内部值。'}
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4.4),constrained_layout=True)
    classes=[r for r in rounds if not r['control']]
    controls=[r for r in rounds if r['control']]
    auxiliary=[]
    for i,name in enumerate(stage_names):
        ds=[r['stages'][i]['statistics']['paired']['paired_mean_difference_ns'] for r in classes]
        repeated=len(classes)>=3 and all(r['stages'][i]['statistics']['verdict']['statistically_significant'] for r in classes) and (all(x>0 for x in ds) or all(x<0 for x in ds))
        stable=all(not r['stages'][i]['statistics']['verdict']['statistically_significant'] and r['stages'][i]['statistics']['verdict']['tests_agree'] for r in controls)
        auxiliary.append({'stage':name,'repeated_difference':repeated,'same_input_control_passed':stable,'candidate':repeated and stable and all(r['cpu_migrations']==0 for r in rounds)})
    result['auxiliary_analysis']=auxiliary
    candidates=[r['stage'] for r in auxiliary if r['candidate']]
    result['interpretation']='重复差异候选：'+('、'.join(candidates) if candidates else '未形成通过同输入对照的重复候选')+'；仅辅助分析。开销为诊断构建净耗时变化，可受代码布局影响而为负；空探针成本另见报告。'
    for r in classes:
        diffs=[s['statistics']['paired']['paired_mean_difference_ns'] for s in r['stages']]
        axes[0].plot(range(8),diffs,'o-',label='Round '+str(r['round']))
    axes[0].axhline(0,color='gray',linestyle='--'); axes[0].set(xticks=range(8),xticklabels=['Check','Decrypt','Derive','Reencrypt','Compare','Reject','Select','Mechanism'],ylabel='Modified - normal (ns)',title='Instrumented stage differences'); axes[0].tick_params(axis='x',rotation=30); axes[0].legend()
    for j,cls in enumerate(('valid','changed')):
        axes[1].plot([r['round'] for r in classes],[r['overhead'][j]['overhead_percent'] for r in classes],'o-',label=cls)
    axes[1].set(xlabel='Round',ylabel='Mean overhead (%)',title='Instrumented vs original library'); axes[1].legend()
    result['chart_png']=str(directory/'instrumentation.png'); fig.savefig(result['chart_png'],dpi=180); plt.close(fig)
    return save(directory,result)
