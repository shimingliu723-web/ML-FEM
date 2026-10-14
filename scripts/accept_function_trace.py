import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from software_service import make_samples, BUILTINS, detect, new_run, save
from function_trace import run_trace
cpu=min(os.sched_getaffinity(0))
sample=make_samples('mlkem_native_baseline','512',512)
results=[]
for target in BUILTINS:
    print('START',target,flush=True)
    r=run_trace(target,'512',sample['report_json'],10000,cpu,3,2)
    results.append(r)
    print('PASS',target,r['correctness']['official_vectors']['passed'],r['report_json'],flush=True)
report=save(new_run('trace-acceptance'),{'success':True,'results':results})
print('SUMMARY',report['report_json'],flush=True)
