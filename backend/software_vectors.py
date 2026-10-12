"""Direct ACVP evaluation against the selected dynamic library, not a reference executable."""
import ctypes,json,hashlib
from pathlib import Path
from mlkem_service import MLKEM
from target_manager import get_target
ROOT=Path(__file__).resolve().parents[1]
DATASETS=['ML-KEM-keyGen-FIPS203','ML-KEM-encapDecap-FIPS203','ML-KEM-encapDecap-FIPS203-tr1']

def validate_official(target_id,levels):
    target=get_target(target_id); engines={}; sources=[]; results=[]
    for level in levels:
        e=MLKEM(level,target.library_for(level)); engines[level]=e
        for name,nargs in [('mlkem_keypair_derand',3),('mlkem_enc_derand',4),('mlkem_check_pk',1),('mlkem_check_sk',1)]:
            if not hasattr(e.lib,name):return None # external ABI may offer only randomized operations
            f=getattr(e.lib,name);f.argtypes=[ctypes.POINTER(ctypes.c_uint8)]*nargs;f.restype=ctypes.c_int
    def buf(value,length):
        raw=bytes.fromhex(value)
        if len(raw)!=length:raise ValueError('官方向量字段长度不匹配')
        return (ctypes.c_uint8*length).from_buffer_copy(raw)
    for dataset in DATASETS:
        directory=ROOT/'data/acvp'/dataset
        prompt=json.loads((directory/'prompt.json').read_text());expected=json.loads((directory/'expectedResults.json').read_text())
        answers={(g['tgId'],t['tcId']):t for g in expected['testGroups'] for t in g['tests']}
        for name in ['prompt.json','expectedResults.json']:
            path=directory/name;sources.append({'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        for group in prompt['testGroups']:
            level=group['parameterSet'].replace('ML-KEM-','')
            if level not in engines:continue
            e=engines[level];p=e.params;operation=group.get('function','keyGeneration')
            for case in group['tests']:
                ans=answers[(group['tgId'],case['tcId'])];passed=False
                if operation=='keyGeneration':
                    pk=e._array(p.public_key);sk=e._array(p.secret_key)
                    rc=e.lib.mlkem_keypair_derand(pk,sk,buf(case['d']+case['z'],64))
                    passed=rc==0 and bytes(pk)==bytes.fromhex(ans['ek']) and bytes(sk)==bytes.fromhex(ans['dk'])
                elif operation=='encapsulation':
                    ct=e._array(p.ciphertext);ss=e._array(32)
                    rc=e.lib.mlkem_enc_derand(ct,ss,buf(case['ek'],p.public_key),buf(case['m'],32))
                    passed=rc==0 and bytes(ct)==bytes.fromhex(ans['c']) and bytes(ss)==bytes.fromhex(ans['k'])
                elif operation=='decapsulation':
                    if 'dk' in case:sk=buf(case['dk'],p.secret_key)
                    else:
                        pk=e._array(p.public_key);sk=e._array(p.secret_key)
                        if e.lib.mlkem_keypair_derand(pk,sk,buf(case['d']+case['z'],64))!=0:raise ValueError('种子展开执行失败')
                    ss=e._array(32);rc=e.lib.mlkem_dec(ss,buf(case['c'],p.ciphertext),sk)
                    passed=rc==0 and bytes(ss)==bytes.fromhex(ans['k'])
                elif operation=='decapsulationKeyCheck':
                    passed=(e.lib.mlkem_check_sk(buf(case['dk'],p.secret_key))==0)==ans['testPassed']
                elif operation=='encapsulationKeyCheck':
                    passed=(e.lib.mlkem_check_pk(buf(case['ek'],p.public_key))==0)==ans['testPassed']
                else:raise ValueError('未适配的官方向量操作：'+operation)
                results.append({'index':len(results)+1,'level':group['parameterSet'],'operation':operation,'dataset':dataset,
                  'tgId':group['tgId'],'tcId':case['tcId'],'passed':bool(passed),'reason':operation+'：'+('与公开期望结果一致' if passed else '与公开期望结果不一致')})
    passed=sum(r['passed'] for r in results)
    return {'target_id':target_id,'total':len(results),'passed':passed,'failed':len(results)-passed,'success':bool(results) and passed==len(results),'results':results,'sources':sources,
      'scope':'直接调用所选目标的确定性KeyGen/Encaps、Decaps及输入检查接口；不导出实际或期望秘密值'}
