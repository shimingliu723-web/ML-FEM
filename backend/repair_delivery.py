"""Build-verified source repair and portable program delivery for the native ABI."""
from pathlib import Path
import difflib, hashlib, json, re, shutil, subprocess, sys, uuid, zipfile

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'mlkem-native-scu-v1'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def source_manifest(directory):
    return {str(p.relative_to(directory)): sha(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}

def compile_source(directory, levels, optimization='-O3', output=None):
    if optimization not in ('-O2', '-O3'):
        raise ValueError('构建配置只支持 -O2 或 -O3')
    source = directory / 'src/mlkem'
    for p in (source/'mlkem_native.c', source/'src/kem.c', directory/'src/randombytes.c'):
        if not p.is_file(): raise ValueError('构建材料不完整：需要mlkem目录和相邻randombytes.c')
    output = output or directory/'lib'
    output.mkdir(parents=True, exist_ok=True)
    flags = [optimization,'-fPIC','-std=c99','-Wall','-Wextra','-Wpedantic',
             '-I'+str(source),'-DMLK_CONFIG_NAMESPACE_PREFIX=mlkem']
    for level in levels:
        command=['gcc',*flags,'-DMLK_CONFIG_PARAMETER_SET='+level,'-shared',
                 str(source/'mlkem_native.c'),str(directory/'src/randombytes.c'),
                 '-o',str(output/f'libmlkem{level}.so')]
        result=subprocess.run(command,capture_output=True,timeout=300)
        if result.returncode: raise ValueError('源码构建失败；请核对所选构建配置和源码完整性')
    return {'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],
            'optimization_flags':' '.join(flags[:6]),'build_adapter':PROFILE,
            'library_sha256':{l:sha(output/f'libmlkem{l}.so') for l in levels}}

def verify_source(target_id, optimization='-O3'):
    from target_manager import get_target
    target=get_target(target_id); directory=ROOT/'targets'/target_id
    original=source_manifest(directory/'src')
    output=directory/('rebuild_'+uuid.uuid4().hex[:8])
    try:
        profile=compile_source(directory,target.levels,optimization,output)
        imported={l:sha(target.library_for(l)) for l in target.levels}
        matched=all(profile['library_sha256'][l]==imported[l] for l in target.levels)
    finally:
        if output.exists(): shutil.rmtree(output)
    profile.update(source_sha256=original, imported_library_sha256=imported,
                   source_binary_verified=matched,
                   source_binary_correspondence='逐参数集重新编译与输入库SHA256完全一致' if matched else '重新编译的库与输入库不一致，自动修复未启用')
    (directory/'build_profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2))
    return profile

def normalized(text):
    text=re.sub(r'/\*[\s\S]*?\*/|//[^\n]*','',text)
    return re.sub(r'\s+','',text)

REJECTION_WORK = '''mlk_memcpy(tmp, sk + MLKEM_INDCCA_SECRETKEYBYTES - MLKEM_SYMBYTES, MLKEM_SYMBYTES);
mlk_memcpy(tmp + MLKEM_SYMBYTES, ct, MLKEM_INDCCA_CIPHERTEXTBYTES);
mlk_hash_j(ss, tmp, MLKEM_SYMBYTES + MLKEM_INDCCA_CIPHERTEXTBYTES);'''
BRANCH_TAIL = '''if (fail == 0) {
  mlk_memcpy(ss, kr, MLKEM_SYMBYTES);
} else {
  ''' + REJECTION_WORK + '''
}'''
FIXED_TAIL = REJECTION_WORK + '\nmlk_ct_cmov_zero(ss, kr, MLKEM_SYMBYTES, fail);\n'

def repair_plan(target_id):
    from repair_manager import _source_root, _memcmp_block, _baseline_memcmp_block
    root=_source_root(target_id); plans=[]
    verify=root/'src/verify.h'
    if verify.is_file():
        text=verify.read_text(); start,end,block=_memcmp_block(text)
        # Match entire known function implementation, not the presence of a return token.
        known=[]
        for name in ('variant_early_return','variant_early_return_while','variant_early_return_xor'):
            candidate=ROOT/'targets'/name/'src/mlkem/src/verify.h'
            known.append(normalized(_memcmp_block(candidate.read_text())[2]))
        if normalized(block) in known:
            plans.append({'kind':'early_return_compare','file':verify,'start':start,'end':end,
                          'replacement':_baseline_memcmp_block()})
        elif ('size_t rounds = r ? 64u : 4096u' in block and 'i < rounds' in block):
            plans.append({'kind':'data_dependent_loop','file':verify,'start':start,'end':end,
                          'replacement':_baseline_memcmp_block()})
        elif ('case_table[(i * case_stride)' in block and 'static volatile uint8_t case_table[4194304]' in block):
            plans.append({'kind':'data_dependent_memory','file':verify,'start':start,'end':end,
                          'replacement':_baseline_memcmp_block()})
        elif ('quotient_sink ^=' in block and '/ case_divisor' in block and 'i < 1024u' in block):
            plans.append({'kind':'variable_time_division','file':verify,'start':start,'end':end,
                          'replacement':_baseline_memcmp_block()})
    kem=root/'src/kem.c'
    if kem.is_file():
        text=kem.read_text()
        anchor='fail = mlk_ct_memcmp(ct, tmp, MLKEM_INDCCA_CIPHERTEXTBYTES);'
        start=text.find(anchor); end=text.find('\ncleanup:',start)
        if start>=0 and end>=0:
            start+=len(anchor)
            if normalized(text[start:end])==normalized(BRANCH_TAIL):
                plans.append({'kind':'conditional_rejection_path','file':kem,'start':start,'end':end,
                              'replacement':'\n\n  '+FIXED_TAIL+'\n'})
        marker='''
  {
    volatile uint32_t case_marker = 1u;
    size_t case_i;
    if (fail != 0) {
      for (case_i = 0; case_i < 1024u; case_i++) {
        case_marker = case_marker * 1664525u + 1013904223u + (uint32_t)case_i;
      }
    }
    __asm__ volatile("" : : "r"(case_marker));
  }'''
        marker_start=text.find(marker)
        if marker_start>=0:
            plans.append({'kind':'data_dependent_branch','file':kem,'start':marker_start,
                          'end':marker_start+len(marker),'replacement':''})
    compress=root/'src/compress.h'
    if compress.is_file():
        text=compress.read_text()
        variable='''volatile uint32_t case_divisor = MLKEM_Q;
  return (uint8_t)((((uint32_t)u * 2u + MLKEM_Q / 2u) / case_divisor) % 2u);'''
        fixed='''uint32_t d0 = (uint32_t)u * 1290168;
  /* Unsigned shifting by 31 positions leaves only the top bit. */
  return (uint8_t)((d0 + ((uint32_t)1u << 30)) >> 31);'''
        start=text.find(variable)
        if start>=0:
            plans.append({'kind':'variable_time_division','file':compress,'start':start,
                          'end':start+len(variable),'replacement':fixed})
    return plans

def generate(target_id, repaired_id):
    from target_manager import get_target
    from software_service import validate_basic
    target=get_target(target_id); before=ROOT/'targets'/target_id
    if target.role=='custom':
        profile=json.loads((before/'build_profile.json').read_text())
        if not profile.get('source_binary_verified'):
            raise ValueError('外部源码尚未通过重新编译与输入库摘要一致性验证')
        if profile['source_sha256']!=source_manifest(before/'src'):
            raise ValueError('源码在接入后发生变化，需要重新接入并验证')
        if any(sha(target.library_for(l))!=profile['imported_library_sha256'][l] for l in target.levels):
            raise ValueError('输入库在接入后发生变化，需要重新验证')
    else:
        profile={'optimization_flags':'-O3'}
    plans=repair_plan(target_id)
    if not plans: raise ValueError('没有匹配完整受支持模式，需人工适配')
    destination=ROOT/'targets'/repaired_id
    shutil.copytree(before/'src',destination/'src')
    patch=[]
    for plan in plans:
        relative=plan['file'].relative_to(before)
        path=destination/relative; original=path.read_text()
        updated=original[:plan['start']]+plan['replacement']+original[plan['end']:]
        path.write_text(updated)
        patch.extend(difflib.unified_diff(original.splitlines(),updated.splitlines(),
                     fromfile='a/'+str(relative),tofile='b/'+str(relative),lineterm=''))
    patch_file=destination/'repair.patch';patch_file.write_text('\n'.join(patch)+'\n')
    optimization='-O2' if profile['optimization_flags'].startswith('-O2') else '-O3'
    config={'id':repaired_id,'name':'修复实现：'+target.name,'role':'repaired','levels':target.levels,
            'description':'从所选原目标源码应用已适配防护规则并重新编译',
            'library_template':f'targets/{repaired_id}/lib/libmlkem{{level}}.so',
            'build':['python3','backend/repair_delivery.py','build',repaired_id],
            'repair_from':target_id,'optimization':optimization,'selftest':[]}
    (destination/'target.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
    built=compile_source(destination,target.levels,optimization)
    built.update(source_sha256=source_manifest(destination/'src'),source_binary_verified=True)
    (destination/'build_profile.json').write_text(json.dumps(built,indent=2))
    correctness=validate_basic(repaired_id,target.levels,100)
    result={'success':correctness['success'],'before_id':target_id,'repaired_id':repaired_id,
            'repair_types':[p['kind'] for p in plans],'patch_file':str(patch_file),
            'patch_sha256':sha(patch_file),'correctness':correctness,'build':built,
            'input_library_sha256':{l:sha(target.library_for(l)) for l in target.levels}}
    (destination/'repair_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result

def export_program(report_path):
    from software_service import RESULTS, new_run, save
    p=Path(report_path).resolve(strict=True)
    if RESULTS.resolve() not in p.parents: raise ValueError('请选择软件生成的修复报告')
    report=json.loads(p.read_text())
    if report.get('kind')!='repair' or not report.get('success') or not report.get('patch',{}).get('correctness',{}).get('success'):
        raise ValueError('只有功能验证通过的修复产物可以导出')
    target_id=report['repaired_id'];directory=ROOT/'targets'/target_id
    profile=json.loads((directory/'build_profile.json').read_text())
    for level,expected in profile['library_sha256'].items():
        if sha(directory/'lib'/f'libmlkem{level}.so')!=expected:
            raise ValueError('修复库发生变化，导出已中止')
    if source_manifest(directory/'src')!=profile['source_sha256']:
        raise ValueError('修复源码发生变化，导出已中止')
    out=new_run('program-export'); archive=out/(target_id+'.zip'); manifest=[]
    config=json.loads((directory/'target.json').read_text())
    optimization=config.get('optimization','-O3')
    rebuild='''#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p lib
for level in '''+' '.join(config['levels'])+'''; do
  gcc '''+optimization+''' -fPIC -std=c99 -Wall -Wextra -Wpedantic -Isrc/mlkem -DMLK_CONFIG_NAMESPACE_PREFIX=mlkem -DMLK_CONFIG_PARAMETER_SET=$level -shared src/mlkem/mlkem_native.c src/randombytes.c -o lib/libmlkem${level}.so
done
'''
    from software_service import export_report
    evidence=export_report(str(p))
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        def put(name,content):
            z.writestr(name,content);manifest.append({'file':name,'sha256':hashlib.sha256(content).hexdigest()})
        for folder in ('src','lib'):
            for file in sorted((directory/folder).rglob('*')):
                if file.is_file(): put(str(file.relative_to(directory)),file.read_bytes())
        for name in ('repair.patch','target.json','build_profile.json','repair_report.json'):
            put(name,(directory/name).read_bytes())
        put('build.sh',rebuild.encode())
        put('verification/repair_comparison.json',p.read_bytes())
        put('verification/evidence.zip',Path(evidence['zip']).read_bytes())
        put('README.md',('修复程序交付包\n\n运行 bash build.sh 在本机重新编译。lib目录包含本次服务器产物，不能保证跨CPU/系统兼容。\n'
            'C接口：mlkem_keypair(pk,sk)、mlkem_enc(ct,ss,pk)、mlkem_dec(ss,ct,sk)。\n'
            '正确性、计时结论及适用范围见verification/repair_comparison.json。\n'
            '本轮是否支持计时改善：'+str(report['effect_confirmed'])+'。未检出不等于常数时间证明。\n').encode())
        license=ROOT/'core/mlkem-native/LICENSE'
        put('LICENSE',license.read_bytes())
        put('THIRD_PARTY.md',b'Source family: https://github.com/pq-code-package/mlkem-native\nModified files are recorded in repair.patch.\n')
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    return save(out,{'kind':'program-export','success':True,'target_id':target_id,'zip':str(archive),
                     'files':len(manifest),'effect_confirmed':report['effect_confirmed'],
                     'conclusion':'已导出修复源码、动态库、补丁、构建脚本和验证报告'})

if __name__=='__main__':
    target_id=sys.argv[2]
    from target_manager import get_target
    target=get_target(target_id);directory=ROOT/'targets'/target_id
    config=json.loads((directory/'target.json').read_text())
    compile_source(directory,target.levels,config.get('optimization','-O3'))
