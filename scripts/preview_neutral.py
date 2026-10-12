"""Render the actual desktop with existing evidence; no experiments are rerun."""
import os, sys, json
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_app'))
from software import MainWindow, apply_style
from PySide6.QtWidgets import QApplication
app = QApplication([])
apply_style(app)
w = MainWindow()
w.show()
out = ROOT / 'results/software/ui-neutral'
out.mkdir(parents=True, exist_ok=True)
def capture(page, name):
    w.nav.setCurrentRow(page)
    app.processEvents()
    assert w.grab().save(str(out / name))
capture(0, '01-home.png')
capture(1, '02-targets.png')
reports = []
for path in (ROOT / 'results/software').glob('*/report.json'):
    try:
        reports.append((path, json.loads(path.read_text())))
    except (OSError, ValueError):
        continue
for kind, page, name in [('basic',3,'03-basic.png'),('environment',2,'04-environment.png'),
                         ('detection',5,'05-timing.png'),('location',6,'06-location.png'),
                         ('repair',7,'07-repair.png')]:
    matches = [(p,d) for p,d in reports if d.get('kind') == kind
               and (kind != 'repair' or d.get('effect_confirmed'))
               and (kind != 'detection' or len(d.get('runs',[])) >= 3)]
    if not matches:
        continue
    path, d = sorted(matches, key=lambda x: str(x[0]))[-1]
    idx = w.targetBox.findData(d.get('target_id'))
    if idx >= 0:
        w.targetBox.setCurrentIndex(idx)
    if d.get('level'):
        w.levelBox.setCurrentText(str(d['level']))
    if d.get('runs'):
        r = d['runs'][0]
        w.pairs.setValue(r['pairs']); w.repeats.setValue(len(d['runs']))
        w.cpuBox.setCurrentText(str(r['cpu']))
        w.samplePath.setText(r.get('sample_manifest',''))
        w.category.setCurrentIndex(['changed_first_b64','changed_mid_b64','changed_last_b64'].index(r['category']))
    w.render_result(page,d)
    w.status.setText('历史实测结果 · ' + path.parent.name)
    capture(page,name)
w.refresh_history()
capture(8,'08-reports.png')
w.targetBox.setCurrentIndex(w.targetBox.findData('mlkem_native_baseline'))
assert w.tables[3].rowCount() == 0
print(out)
w.close()
