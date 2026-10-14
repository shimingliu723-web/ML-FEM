import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for p in sorted((ROOT/'results/software').glob('*-detection/report.json')):
    d=json.loads(p.read_text())
    print(p.parent.name,d['target_id'],'env',d['formal_environment'])
    for r in d['runs']:
        a=r['analysis'];v=r['statistics']['verdict']
        print(' ',round(a['paired_mean_difference_ns'],2),[round(x,2) for x in a['paired_difference_ci95_ns']], 'agree',v['tests_agree'],'significant',v['statistically_significant'])
for p in sorted((ROOT/'results/software').glob('*-repair/report.json')):
    d=json.loads(p.read_text()); print('REPAIR',d['target_id'],d.get('effect_confirmed'),d.get('mean_abs_diff_before_ns'),d.get('mean_abs_diff_after_ns'))
