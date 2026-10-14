import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for folder in sorted((root/'data/acvp').glob('ML*')):
    for filename in ['prompt.json','expectedResults.json']:
        d=json.loads((folder/filename).read_text())
        print(folder.name,filename,type(d).__name__)
        if isinstance(d,list):d=d[-1]
        print('ROOT KEYS',list(d))
        for g in d.get('testGroups',[]):
            print({k:v for k,v in g.items() if k!='tests'},'n=',len(g['tests']),'keys=',list(g['tests'][0]))
