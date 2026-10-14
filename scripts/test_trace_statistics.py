import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from stats import compare_two_classes
import random
rng=random.Random(42); jitter=[rng.randrange(80,120) for _ in range(10000)]
for a,b in [([0]*10000,[0]*10000),([0]*10000,[100]*10000),([100]*10000,[0]*10000),([0]*10000,jitter)]:
    r=compare_two_classes(a,b,orders=[i%2 for i in range(10000)],alpha=.05/7)
    assert r['paired']['paired_mean_difference_ns']>=0 if b[0]>=a[0] else r['paired']['paired_mean_difference_ns']<0
    if a==b: assert not r['verdict']['statistically_significant']
    if b is jitter: assert r['verdict']['statistically_significant'] and '不可定义' in r['verdict']['text']
    print('PASS zero-baseline',a[0],b[0],r['paired']['paired_mean_difference_ns'])
