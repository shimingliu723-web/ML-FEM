"""Create seven explicit ML-KEM laboratory cases without deleting old targets."""
from __future__ import annotations
import hashlib,json,re,shutil,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TARGETS=ROOT/'targets'
BASE=ROOT/'core/mlkem-native/mlkem'
RANDOM=ROOT/'core/randombytes.c'

CASES={
 'case_compare_early':('比较函数早退','comparison_early_exit','正常输入与首/中/尾单比特等长变化；位置变化用于检验比较工作量是否随首个差异位置改变','完整扫描固定长度并汇总差异'),
 'case_conditional_failure':('条件失败处理路径','conditional_failure_path','正常输入与等长变化输入；检验成功路径和失败路径是否执行不同工作量','统一计算候选结果与拒绝结果，再用掩码选择'),
 'case_variable_loop':('数据相关循环','data_dependent_loop','正常输入与等长变化输入；检验循环次数是否受验证结果影响','固定循环上限并以掩码控制结果更新'),
 'case_memory_index':('数据相关内存访问','data_dependent_memory','正常输入重复访问同一缓存线，等长变化输入按固定次数跨缓存线访问；循环次数相同，仅访问地址由比较结果决定','固定范围扫描与掩码选择，或替换为既有常数时间原语'),
 'case_conditional_branch':('数据相关条件分支','data_dependent_branch','正常输入与等长变化输入；验证结果选择轻路径或固定工作量路径，用于检验控制流差异','消除条件跳转和分支专属工作，使用掩码选择并统一路径'),
 'case_variable_division':('输入相关运行期除法路径','variable_time_division','正常输入与等长变化输入；验证结果控制一个包含1024次运行期整数除法的有界工作段，并结合反汇编确认div/idiv','移除验证结果控制的除法工作段，恢复已验证的固定流程比较原语'),
}

def write_json(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def config(case_id,name,mechanism,sample,repair,flags='-O3'):
 return {'id':case_id,'name':'案例：'+name,'role':'contrast','description':'保持ML-KEM功能语义的受控实验实现，用于验证'+name+'的检测、定位和复测链路。',
  'levels':['512','768','1024'],'library_template':f'targets/{case_id}/lib/libmlkem{{level}}.so','build':['bash',f'targets/{case_id}/build.sh'],'selftest':[],
  'case_type':'controlled','mechanism':mechanism,'sample_strategy':sample,'repair_strategy':repair,'limitations':'受控案例，不代表独立算法实现或所有真实工程代码。','flags':flags}

def build_script(case_id,flags):
 return f'''#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/../.." && pwd)"
TARGET_DIR="$PROJECT_DIR/targets/{case_id}"
mkdir -p "$TARGET_DIR/lib"
CC="${{CC:-gcc}}"
COMMON_FLAGS="{flags} -fPIC -std=c99 -Wall -Wextra -Wpedantic -I$TARGET_DIR/src/mlkem -DMLK_CONFIG_NAMESPACE_PREFIX=mlkem"
for level in 512 768 1024; do
 "$CC" $COMMON_FLAGS -DMLK_CONFIG_PARAMETER_SET=$level -shared "$TARGET_DIR/src/mlkem/mlkem_native.c" "$TARGET_DIR/src/randombytes.c" -o "$TARGET_DIR/lib/libmlkem${{level}}.so"
done
'''

def make_base(case_id):
 d=TARGETS/case_id
 if d.exists(): shutil.rmtree(d)
 (d/'src').mkdir(parents=True);shutil.copytree(BASE,d/'src/mlkem');shutil.copy2(RANDOM,d/'src/randombytes.c')
 return d

def replace_compare(path,body):
 text=path.read_text()
 pattern=r'(static MLK_INLINE uint8_t mlk_ct_memcmp\([^\{]+\n\{).*?(\n\}\n\n/\*\*\n \* Copy len bytes)'
 out,n=re.subn(pattern,r'\1\n'+body+r'\2',text,count=1,flags=re.S)
 if n!=1: raise RuntimeError('comparison function layout changed')
 path.write_text(out)

def compile_case(case_id,flags='-O3'):
 d=TARGETS/case_id; script=d/'build.sh';script.write_text(build_script(case_id,flags));script.chmod(0o755)
 subprocess.run(['bash',str(script)],cwd=ROOT,check=True)
 write_json(d/'build_profile.json',{'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],
  'optimization_flags':flags+' -fPIC -std=c99 -Wall -Wextra -Wpedantic','build_adapter':'mlkem-native-scu-v1','source_family':'mlkem-native controlled mechanism case',
  'library_sha256':{level:sha(d/f'lib/libmlkem{level}.so') for level in ('512','768','1024')}})

def main():
 # Reuse the already accepted comparison source under an explicit case identity.
 d=TARGETS/'case_compare_early'
 if d.exists(): shutil.rmtree(d)
 shutil.copytree(TARGETS/'variant_early_return',d)
 write_json(d/'target.json',config('case_compare_early',*CASES['case_compare_early']))
 compile_case('case_compare_early')

 # Promote the independently accepted conditional-path fixture; originals stay preserved.
 d=TARGETS/'case_conditional_failure'
 if d.exists(): shutil.rmtree(d)
 shutil.copytree(TARGETS/'custom_rejection_2e1030',d)
 write_json(d/'target.json',config('case_conditional_failure',*CASES['case_conditional_failure']))
 compile_case('case_conditional_failure')

 common='''
  uint8_t r = 0, s = 0;
  size_t i;
  for (i = 0; i < len; i++) { r |= a[i] ^ b[i]; s ^= a[i] ^ b[i]; }
'''
 d=make_base('case_variable_loop')
 replace_compare(d/'src/mlkem/src/verify.h',common+'''
  volatile uint8_t sink = 0;
  size_t rounds = r ? 64u : 4096u;
  for (i = 0; i < rounds; i++) { sink ^= (uint8_t)i; }
  (void)sink;
  return (mlk_value_barrier_u8(mlk_ct_cmask_nonzero_u8(r) ^ s) ^ s);''')
 write_json(d/'target.json',config('case_variable_loop',*CASES['case_variable_loop']));compile_case('case_variable_loop')

 d=make_base('case_memory_index')
 replace_compare(d/'src/mlkem/src/verify.h',common+'''
  static volatile uint8_t case_table[4194304];
  static volatile uint8_t case_table_ready = 0;
  volatile uint8_t observed = 0;
  if (case_table_ready == 0) {
    for (i = 0; i < 512u; i++) { case_table[i * 8192u] = (uint8_t)i; }
    case_table_ready = 1;
  }
  size_t case_stride = (size_t)(r != 0) * 8192u;
  for (i = 0; i < 4096u; i++) {
    observed ^= case_table[(i * case_stride) & 4194303u];
  }
  __asm__ volatile("" : : "r"(observed));
  return (mlk_value_barrier_u8(mlk_ct_cmask_nonzero_u8(r) ^ s) ^ s);''')
 write_json(d/'target.json',config('case_memory_index',*CASES['case_memory_index']));compile_case('case_memory_index')

 d=make_base('case_conditional_branch')
 kem=d/'src/mlkem/src/kem.c';text=kem.read_text();needle='fail = mlk_ct_memcmp(ct, tmp, MLKEM_INDCCA_CIPHERTEXTBYTES);'
 addition=needle+'''\n  {
    volatile uint32_t case_marker = 1u;
    size_t case_i;
    if (fail != 0) {
      for (case_i = 0; case_i < 1024u; case_i++) {
        case_marker = case_marker * 1664525u + 1013904223u + (uint32_t)case_i;
      }
    }
    __asm__ volatile("" : : "r"(case_marker));
  }'''
 if text.count(needle)!=1:raise RuntimeError('kem comparison layout changed')
 kem.write_text(text.replace(needle,addition))
 write_json(d/'target.json',config('case_conditional_branch',*CASES['case_conditional_branch']));compile_case('case_conditional_branch')

 d=make_base('case_variable_division')
 replace_compare(d/'src/mlkem/src/verify.h',common+'''
  volatile uint64_t case_divisor = 3u + (uint64_t)r;
  volatile uint64_t quotient_sink = 0x7fffffffffffffffULL;
  if (r != 0) {
    for (i = 0; i < 1024u; i++) {
      quotient_sink ^= (0xf123456789abcdefULL + (uint64_t)i) / case_divisor;
    }
  }
  __asm__ volatile("" : : "r"(quotient_sink));
  return (mlk_value_barrier_u8(mlk_ct_cmask_nonzero_u8(r) ^ s) ^ s);''')
 write_json(d/'target.json',config('case_variable_division',*CASES['case_variable_division'],flags='-Os'));compile_case('case_variable_division','-Os')

 # Add explicit metadata to the normative baseline without touching its library.
 base_cfg=json.loads((TARGETS/'mlkem_native_baseline/target.json').read_text())
 base_cfg.update({'name':'案例：规范基线','case_type':'baseline','mechanism':'fixed_flow_baseline','sample_strategy':'同一批等长输入与A/A对照，用于建立测量基线','repair_strategy':'无需修改；作为其他案例的功能与计时参照','limitations':'未检出差异不等于绝对常数时间证明。'})
 write_json(TARGETS/'mlkem_native_baseline/target.json',base_cfg)
 print(json.dumps({'success':True,'cases':['mlkem_native_baseline']+list(CASES)},ensure_ascii=False))
if __name__=='__main__':main()
