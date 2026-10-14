"""External source intake, actual repair, and independent delivery verification."""
import argparse, hashlib, json, os, shutil, subprocess, sys, time, uuid, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from software_service import import_target,validate_basic,make_samples,repair,locate,new_run,save,environment
from repair_delivery import compile_source,BRANCH_TAIL,export_program,repair_plan,verify_source
from repair_manager import _memcmp_block,_baseline_memcmp_block

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['source','timing'],default='source');args=parser.parse_args()
    if args.phase=='timing':
        source=json.loads(sorted((ROOT/'results/software').glob('*-external-source/report.json'))[-1].read_text())
        output=new_run('external-timing');results=[]
        cpu=min(os.sched_getaffinity(0))
        env=environment(cpu)
        for item in source['cases']:
            tid=item['target_id'];samples=make_samples(tid,'512',512)
            result=repair(tid,'512',samples['report_json'],10000,cpu,3,2)
            assert result['success']
            assert result['patch']['correctness']['vectors']['total']==435
            package=export_program(result['report_json'])
            results.append({'target_id':tid,'repair':result,'package':package})
            save(output,{'kind':'external-timing','environment':env,'cases':results,'success':len(results)==len(source['cases'])})
            print(tid,'BEFORE',result['mean_abs_diff_before_ns'],'AFTER',result['mean_abs_diff_after_ns'],'CONFIRMED',result['effect_confirmed'],flush=True)
        return
    output=new_run('external-source');cases=[];negatives=[]
    fixtures=output/'fixtures';fixtures.mkdir()
    for kind in ['compare','rejection','combined']:
        directory=fixtures/kind;shutil.copytree(ROOT/'targets/variant_early_return/src',directory/'src')
        verify=directory/'src/mlkem/src/verify.h'
        if kind=='rejection':
            text=verify.read_text();a,b,_=_memcmp_block(text);verify.write_text(text[:a]+_baseline_memcmp_block()+text[b:])
        if kind in ('rejection','combined'):
            kem=directory/'src/mlkem/src/kem.c';text=kem.read_text()
            anchor='fail = mlk_ct_memcmp(ct, tmp, MLKEM_INDCCA_CIPHERTEXTBYTES);'
            a=text.index(anchor)+len(anchor);b=text.index('\ncleanup:',a)
            kem.write_text(text[:a]+'\n\n'+BRANCH_TAIL+'\n'+text[b:])
        compile_source(directory,['512','768','1024'])
        tid='custom_'+kind+'_'+uuid.uuid4().hex[:6]
        imported=import_target(tid,'外部接入验收：'+kind,str(directory/'lib/libmlkem{level}.so'),
                    ['512','768','1024'],str(directory/'src/mlkem'),build_adapter='mlkem-native-scu-v1')
        assert imported['success'] and imported['source_build_verified'],imported
        full=validate_basic(tid,['512','768','1024'],100);assert full['success'] and full['vectors']['total']==435
        plans=repair_plan(tid);assert len(plans)==(2 if kind=='combined' else 1)
        from repair_delivery import generate
        rid='repair_accept_'+uuid.uuid4().hex[:8]
        patched=generate(tid,rid);assert patched['success'] and patched['correctness']['vectors']['total']==435
        # A source-only repair report allows delivery verification before timing; no timing success is claimed.
        r=save(new_run('repair'),{'kind':'repair','success':True,'target_id':tid,'repaired_id':rid,
            'patch':patched,'effect_confirmed':False,'conclusion':'源码修复及功能验收；计时验收另行执行'})
        package=export_program(r['report_json'])
        unpacked=output/('unpacked_'+kind);unpacked.mkdir()
        with zipfile.ZipFile(package['zip']) as z:
            manifest=json.loads(z.read('manifest.json'))
            for entry in manifest:
                assert hashlib.sha256(z.read(entry['file'])).hexdigest()==entry['sha256']
            assert not any(Path(n).name in ('samples.csv','inputs.bin') for n in z.namelist())
            from io import BytesIO
            with zipfile.ZipFile(BytesIO(z.read('verification/evidence.zip'))) as evidence:
                assert not any(Path(n).name in ('samples.csv','inputs.bin') for n in evidence.namelist())
            z.extractall(unpacked)
        before={l:hashlib.sha256((unpacked/'lib'/f'libmlkem{l}.so').read_bytes()).hexdigest() for l in ['512','768','1024']}
        subprocess.run(['bash',str(unpacked/'build.sh')],check=True,capture_output=True)
        assert all(hashlib.sha256((unpacked/'lib'/f'libmlkem{l}.so').read_bytes()).hexdigest()==before[l] for l in before)
        replay_id='custom_delivered_'+uuid.uuid4().hex[:6]
        replay=import_target(replay_id,'独立解包复编译验证',str(unpacked/'lib/libmlkem{level}.so'),list(before))
        replay_full=validate_basic(replay_id,list(before),100)
        assert replay_full['success'] and replay_full['vectors']['total']==435
        # Tampering the target source after verified intake must disable repair and export.
        source_file=ROOT/'targets'/tid/'src/mlkem/src/verify.h';original=source_file.read_bytes()
        source_file.write_bytes(original+b'\n/* changed after import */\n')
        try:
            try:generate(tid,'repair_should_reject_'+uuid.uuid4().hex[:6])
            except ValueError:negatives.append(kind+':source_tamper_rejected')
            else:raise AssertionError('tampered source accepted')
        finally:source_file.write_bytes(original)
        repaired_file=ROOT/'targets'/rid/'src/mlkem/src/verify.h';content=repaired_file.read_bytes()
        repaired_file.write_bytes(content+b'\n/* changed after regression */\n')
        try:
            try:export_program(r['report_json'])
            except ValueError:negatives.append(kind+':stale_program_export_rejected')
            else:raise AssertionError('stale repaired source exported')
        finally:repaired_file.write_bytes(content)
        # Equivalent but unadapted spelling must be refused, not guessed by a token search.
        source_file.write_bytes(original.replace(b'return 0xFF',b'return (uint8_t)255'))
        try:
            if kind=='compare':assert not repair_plan(tid);negatives.append('unknown_compare_refused')
        finally:source_file.write_bytes(original)
        cases.append({'kind':kind,'target_id':tid,'source_validation':imported,'basic':full,'patch':patched,
                      'program_package':package,'rebuild_and_vector_validation':replay_full})
        print(kind,'SOURCE+435VECTORS+REPAIR+EXPORT+REBUILD PASS',flush=True)
    # Wrong optimization -> different binary -> repair stays disabled.
    tid='custom_mismatch_'+uuid.uuid4().hex[:6];first=fixtures/'compare'
    mismatch=import_target(tid,'构建不对应负例',str(first/'lib/libmlkem{level}.so'),['512'],
                str(first/'src/mlkem'),build_adapter='mlkem-native-scu-v1',optimization='-O2')
    assert not mismatch['source_build_verified']
    try:
        from repair_delivery import generate
        generate(tid,'repair_mismatch_'+uuid.uuid4().hex[:6])
    except ValueError:negatives.append('binary_mismatch_rejected')
    else:raise AssertionError('mismatched source accepted')
    save(output,{'kind':'external-source','success':True,'cases':cases,'negative_checks':negatives,
         'scope':'三类同源受控外部工程，通过与用户相同接入路径。不是独立实现家族或任意源码修复证明。'})
    print('SOURCE_ACCEPTANCE',output,flush=True)
if __name__=='__main__':main()
