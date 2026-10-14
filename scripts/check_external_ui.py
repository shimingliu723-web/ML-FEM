"""Exercise the actual desktop intake, repair and save-as actions."""
import json,os,sys,time,uuid,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(ROOT/'desktop_app'))
from software import MainWindow,apply_style
from PySide6.QtWidgets import QApplication,QFileDialog
app=QApplication([]);apply_style(app);w=MainWindow();w.show()
out=ROOT/'results/software/external-ui';out.mkdir(parents=True,exist_ok=True)
source_report=sorted((ROOT/'results/software').glob('*-external-source/report.json'))[-1]
fixture=source_report.parent/'fixtures/rejection'
tid='custom_ui_'+uuid.uuid4().hex[:8]
w.regId.setText(tid);w.regName.setText('外部源码接入：条件拒绝路径')
w.regLib.setText(str(fixture/'lib/libmlkem{level}.so'));w.regSource.setText(str(fixture/'src/mlkem'))
w.buildAdapter.setCurrentIndex(1)
def wait():
    deadline=time.monotonic()+180
    while w.process is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
    assert w.process is None,'Qt task timeout'
    assert not w.last_error,w.last_error
def shot(page,name):
    w.nav.setCurrentRow(page);app.processEvents();assert w.grab().save(str(out/name))
w.import_target();wait();assert w.outputs[1]['source_build_verified']
shot(1,'01-external-intake.png')
w.targetBox.setCurrentIndex(w.targetBox.findData(tid));w.levelBox.setCurrentText('512')
w.launch('locate',{'target_id':tid,'level':'512'},6);wait()
assert 'conditional_rejection_path' in w.outputs[6]['source']['supported_repairs']
shot(6,'02-location.png')
w.launch('samples',{'target_id':tid,'level':'512','count':16},4);wait()
w.pairs.setValue(1000);w.repeats.setValue(1)
w.launch('repair',w.timing_args(),7);wait()
assert w.outputs[7]['success'] and not w.outputs[7]['effect_confirmed']
assert w.outputs[7]['patch']['correctness']['vectors']['total']==435
shot(7,'03-functional-repair.png')
destination=out/'user_saved_program.zip'
QFileDialog.getSaveFileName=staticmethod(lambda *a,**kw:(str(destination),'修复程序包 (*.zip)'))
w.export_repaired();wait();assert destination.is_file()
with zipfile.ZipFile(destination) as z:
    assert 'build.sh' in z.namelist() and 'verification/evidence.zip' in z.namelist()
shot(8,'04-program-export.png')
repair_report=w.outputs[7]['report_json']
w.targetBox.setCurrentIndex(w.targetBox.findData('mlkem_native_baseline'))
assert 7 not in w.outputs
assert w.tables[7].rowCount()==0
(out/'ui_check.json').write_text(json.dumps({'success':True,'import_target_id':tid,
    'repair_report':repair_report,'saved_program':str(destination),
    'actions':['verified_source_import','locate','repair_new_library','save_program_zip'],
    'selection_clears_stale_repair':True},indent=2))
print(out);w.close()
