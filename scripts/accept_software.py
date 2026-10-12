"""Server acceptance: real target calls, local desktop service, evidence retained."""
import sys,json,os,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from software_service import (BUILTINS,validate_basic,make_samples,detect,repair,import_target,export_report,new_run,save,environment)

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['basic','timing'],required=True);args=ap.parse_args()
    folder=new_run('acceptance-'+args.phase); checks=[]
    def record(name,data):
        checks.append({'name':name,'result':data});save(folder,{'kind':'acceptance','phase':args.phase,'checks':checks});print(name, json.dumps({k:data.get(k) for k in ['success','conclusion','report_json','effect_confirmed']},ensure_ascii=False),flush=True)
    if args.phase=='basic':
        for target in BUILTINS:
            r=validate_basic(target,['512','768','1024'],100);record(target,r)
            if not r['success']:raise RuntimeError(target+' failed')
        custom_id='custom_accept_'+str(int(time.time()))
        record('external_import',import_target(custom_id,'外部接入验收（基线副本）',str(ROOT/'backend/lib/libmlkem{level}.so'),['512','768','1024']))
    else:
        cpu=min(os.sched_getaffinity(0)); record('environment',environment(cpu))
        corpus=make_samples('mlkem_native_baseline','512',512);record('samples',corpus)
        for target in BUILTINS:
            record('timing_'+target,detect(target,'512',corpus['report_json'],10000,cpu,3))
        for target in ['variant_early_return','variant_early_return_while','variant_early_return_xor']:
            r=repair(target,'512',corpus['report_json'],10000,cpu,3);record('repair_'+target,r)
            if not r['success']:raise RuntimeError('repair correctness failed')
            evidence=export_report(r['report_json'])
            with zipfile.ZipFile(evidence['zip']) as z:
                assert all('samples.csv' not in n and 'inputs.bin' not in n for n in z.namelist())
            record('export_'+target,evidence)
        for level in ['768','1024']:
            sample=make_samples('mlkem_native_baseline',level,512)
            record('level_'+level,detect('variant_early_return',level,sample['report_json'],10000,cpu,3))
        for category in [1,3]:record('category_'+str(category),detect('variant_early_return','512',corpus['report_json'],10000,cpu,3,category))
    print('ACCEPTANCE_REPORT',folder/'report.json',flush=True)
if __name__=='__main__':main()
