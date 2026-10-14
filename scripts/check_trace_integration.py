import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
from software_service import make_samples,detect,save,new_run,export_report,digest
from function_trace import run_trace
from target_manager import get_target
cpu=min(os.sched_getaffinity(0))
s=make_samples('mlkem_native_baseline','512',512)
library=get_target('variant_early_return').library_for('512'); before=digest(library)
off=detect('variant_early_return','512',s['report_json'],1000,cpu,1,2,instrument=False)
assert off['instrumentation'] is None
on=detect('variant_early_return','512',s['report_json'],10000,cpu,3,2,instrument=True)
assert on['instrumentation']['success'],on['instrumentation']
assert digest(library)==before
assert len(on['instrumentation']['rounds'])==6
assert not list(Path(on['instrumentation']['report_json']).parent.glob('*.bin'))
extra=[]
for level in ('768','1024'):
  sample=make_samples('mlkem_native_baseline',level,32)
  for target in ('mlkem_native_baseline','variant_early_return'):
    r=run_trace(target,level,sample['report_json'],1000,cpu,1,2)
    assert r['correctness']['official_vectors']['passed']==145
    extra.append(r['report_json'])
custom=next((p.parent.name for p in (ROOT/'targets').glob('custom_rejection_*/target.json')),None)
if custom:
  r=run_trace(custom,'512',s['report_json'],10000,cpu,3,2)
  extra.append(r['report_json'])
  print('CONDITIONAL',r['report_json'],flush=True)
export=export_report(on['report_json'])
import zipfile
with zipfile.ZipFile(export['zip']) as z:
  assert any(n.endswith('function_trace.py') for n in z.namelist())
  assert any(n.endswith('classes-1.csv') for n in z.namelist())
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from desktop_app.software import MainWindow,apply_style
app=QApplication([]); apply_style(app); w=MainWindow(); w.show(); app.processEvents()
assert not w.instrumentBox.isChecked()
w.targetBox.setCurrentIndex(w.targetBox.findData(on['target_id'])); w.levelBox.setCurrentText(on['level'])
w.samplePath.setText(s['report_json']);w.nav.setCurrentRow(5); w.instrumentBox.setChecked(True);w.render_result(5,on);app.processEvents()
assert w.traceTable.rowCount()==42 and w.overheadTable.rowCount()==12
screens=new_run('trace-ui')
tabs=w.traceTable.parentWidget().parentWidget()
tabs.setCurrentWidget(w.traceTable);app.processEvents();w.grab().save(str(screens/'stages.png'))
tabs.setCurrentWidget(w.overheadTable);app.processEvents();w.grab().save(str(screens/'overhead.png'))
w.selection_changed(); assert w.traceTable.rowCount()==0 and not w.instrumentBox.isChecked()
result=save(new_run('trace-integration'),{'success':True,'on_report':on['report_json'],'off_report':off['report_json'],'extra_reports':extra,'export':export,'screenshots':str(screens),'checks':['optional-on-off','original-unchanged','temporary-inputs-deleted','other-parameter-sets','evidence-exports','qt-stage-and-overhead-tables','selection-clears-stale-results']})
print('INTEGRATION',result['report_json'],flush=True)
for r in on['instrumentation']['rounds']:
 if r['control']:continue
 print('ROUND',r['round'],'compare_diff_ns',r['stages'][4]['statistics']['paired']['paired_mean_difference_ns'],'overhead',[(v['class'],v['overhead_percent']) for v in r['overhead']],flush=True)
