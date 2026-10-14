"""Render already-saved results; does not recollect timing data."""
import os,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'backend')]
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from desktop_app.software import MainWindow,apply_style
integration=json.loads(sorted((ROOT/'results/software').glob('*-trace-integration/report.json'))[-1].read_text())
data=json.loads(Path(integration['on_report']).read_text())
app=QApplication([]);apply_style(app);w=MainWindow();w.show()
idx=w.targetBox.findData(data['target_id']);assert idx>=0
w.targetBox.setCurrentIndex(idx);w.levelBox.setCurrentText(data['level'])
assert w.target()==data['target_id'] and data['target_id'] in w.context.text()
w.samplePath.setText(data['runs'][0]['sample_manifest']);w.instrumentBox.setChecked(True);w.nav.setCurrentRow(5)
w.render_result(5,data);app.processEvents()
assert w.traceTable.rowCount()==42 and w.overheadTable.rowCount()==12
output=Path(integration['screenshots'])
for tab,name in [(w.traceTable,'stages.png'),(w.overheadTable,'overhead.png')]:
 w.tabs[5].setCurrentWidget(tab);app.processEvents();assert w.grab().save(str(output/name))
print('CAPTURED',w.target(),output)
