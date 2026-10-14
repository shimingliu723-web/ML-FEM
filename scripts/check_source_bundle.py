import json,sys,tarfile,uuid,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
destination=ROOT/'results'/('packaging-smoke-'+uuid.uuid4().hex[:8]);destination.mkdir(parents=True)
with tarfile.open(ROOT/'MLKEM-Software-source.tar.gz') as archive:archive.extractall(destination,filter='data')
project=destination/'MLKEM-Software'
subprocess.run([sys.executable,'scripts/prepare_software.py'],cwd=project,check=True)
code="import sys;sys.path.insert(0,'backend');from software_service import validate_basic;r=validate_basic('mlkem_native_baseline',['512','768','1024'],20);assert r['success'] and r['vectors']['total']==435;print('RELOCATED_SOURCE_PASS')"
subprocess.run([sys.executable,'-c',code],cwd=project,check=True)
result={'success':True,'extracted_project':str(project),'all_seven_rebuilt':True,'baseline_full_vectors':435}
(ROOT/'results/software/source_bundle_check.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
