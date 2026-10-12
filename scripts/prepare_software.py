"""Rebuild all shipped targets and record actual build provenance."""
import sys,json,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from software_service import BUILTINS,digest
from target_manager import run_target_command,get_target

def main():
    compiler=subprocess.check_output(['gcc','--version'],text=True).splitlines()[0]
    for name in BUILTINS:
        result=run_target_command(name,'build',timeout=300)
        if not result.get('success'):raise RuntimeError(f'Build failed: {name}: {result}')
        target=get_target(name)
        profile={'compiler':compiler,'optimization_flags':'-O3 -fPIC -std=c99 -Wall -Wextra -Wpedantic',
            'command':target.build,'library_sha256':{l:digest(target.library_for(l)) for l in target.levels},
            'source_family':'mlkem-native controlled variants; not independent implementations'}
        (ROOT/'targets'/name/'build_profile.json').write_text(json.dumps(profile,indent=2))
        print(name,'BUILD PASS',flush=True)
    subprocess.run(['gcc','-O2','-Wall','-Wextra',str(ROOT/'experiments/software_measure.c'),'-ldl','-o',str(ROOT/'experiments/software_measure')],check=True)
if __name__=='__main__':main()
