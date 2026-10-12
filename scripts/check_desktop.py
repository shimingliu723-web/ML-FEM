"""Real Qt UI rendering and QProcess action smoke test, no generated mockup."""
import os,sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(ROOT/'desktop_app'))
from software import MainWindow,apply_style
from PySide6.QtWidgets import QApplication
app=QApplication([]);apply_style(app);w=MainWindow();w.show();app.processEvents()
out=ROOT/'results/software/ui-verification';out.mkdir(parents=True,exist_ok=True)
assert w.targetBox.count()>=7
def screenshot(page,name):
    w.nav.setCurrentRow(page);app.processEvents();w.grab().save(str(out/name))
screenshot(0,'01-home.png');screenshot(1,'02-targets.png')
w.targetBox.setCurrentIndex(w.targetBox.findData('variant_early_return_xor'));w.iterations.setValue(100);w.basicRange.setCurrentIndex(1);w.run_basic()
deadline=time.monotonic()+90
while w.process is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
assert w.process is None,'worker timeout'
assert not w.last_error,w.last_error
assert w.outputs[3]['target_id']=='variant_early_return_xor'
assert w.outputs[3]['success']
assert w.outputs[3]['vectors']['total']==435
screenshot(3,'03-basic.png')
def execute(action,args,page):
    w.launch(action,args,page);deadline=time.monotonic()+180
    while w.process is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
    assert w.process is None,action+' timeout'
    assert not w.last_error,(action,w.last_error)
    assert w.outputs[page].get('success',True),(action,'failed')
execute('environment',{'cpu':w.cpu()},2)
execute('samples',{'target_id':w.target(),'level':w.level(),'count':16},4)
assert w.samplePath.text()==w.outputs[4]['report_json']
w.pairs.setValue(1000);w.repeats.setValue(1)
execute('detect',w.timing_args(),5)
execute('locate',{'target_id':w.target(),'level':w.level()},6)
execute('repair',w.timing_args(),7)
assert w.outputs[7]['patch']['correctness']['vectors']['total']==435
assert not w.outputs[7]['effect_confirmed'],'one round must not be accepted as repeated evidence'
execute('export',{'report_path':w.outputs[7]['report_json']},8)
reports=[]
for path in (ROOT/'results/software').glob('*/report.json'):
    d=json.loads(path.read_text());reports.append((path,d))
for kind,page,name in [('environment',2,'04-environment.png'),('detection',5,'05-timing.png'),('location',6,'06-location.png'),('repair',7,'07-repair.png')]:
    matches=[(p,d) for p,d in reports if d.get('kind')==kind and (kind!='repair' or ('performance' in d and len(d['before']['runs'])>=3)) and (kind!='detection' or len(d.get('runs',[]))>=3)]
    if not matches:continue
    p,d=sorted(matches,key=lambda x:str(x[0]))[-1]
    idx=w.targetBox.findData(d.get('target_id'))
    if idx>=0:w.targetBox.setCurrentIndex(idx)
    if d.get('level'):w.levelBox.setCurrentText(str(d['level']))
    if d.get('runs'):
        r=d['runs'][0];w.category.setCurrentIndex(['changed_first_b64','changed_mid_b64','changed_last_b64'].index(r['category']))
    w.render_result(page,d);screenshot(page,name)
    if page==5:w.tabs[5].setCurrentIndex(2);screenshot(5,'05-timing-chart.png');w.tabs[5].setCurrentIndex(0)
w.refresh_history();screenshot(8,'08-reports.png')
# Selection cannot retain results of a previous target.
w.targetBox.setCurrentIndex(w.targetBox.findData('mlkem_native_baseline'))
assert w.tables[3].rowCount()==0
(out/'ui_check.json').write_text(json.dumps({'success':True,'target_selection_verified':True,'worker_actions':['basic','environment','samples','detect','locate','repair','export'],'screenshots':[p.name for p in out.glob('*.png')]},indent=2))
print(out);w.close()
