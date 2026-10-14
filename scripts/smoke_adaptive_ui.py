"""Headless smoke test for the adaptive-detection desktop integration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop_app.software import QApplication, MainWindow
import json


app = QApplication([])
window = MainWindow()
assert window.stack.count() == 9
assert window.targetBox.count() >= 7
timing_tab_titles = [window.tabs[5].tabText(i) for i in range(window.tabs[5].count())]
assert window.tabs[5].count() == 11
for required_title in (
    "创新检测轨迹",
    "自适应证据图",
    "网络稳定性",
    "网络对比图",
    "跨编译验证",
    "跨编译对比图",
):
    assert required_title in timing_tab_titles
assert window.adaptiveTable.columnCount() == 7
reports = sorted((Path(__file__).resolve().parents[1] / "results" / "software").glob("*-adaptive-detection/report.json"))
assert reports
data = json.loads(reports[-1].read_text(encoding="utf-8"))
target_index = window.targetBox.findData(data["target_id"])
assert target_index >= 0
window.targetBox.setCurrentIndex(target_index)
window.levelBox.setCurrentText(str(data["level"]))
window.samplePath.setText(data.get("sample_manifest", ""))
window.render_result(5, data)
assert window.adaptiveTable.rowCount() == len(data["stages"])
assert not window.adaptivePlot.pixmap().isNull()
window.nav.setCurrentRow(5)
window.tabs[5].setCurrentIndex(5)
window.resize(1380, 880)
window.show()
app.processEvents()
evidence_dirs = sorted((Path(__file__).resolve().parents[1] / "results" / "innovation").glob("*-adaptive-comparison"))
ui_capture = evidence_dirs[-1] / "experiment-13-software-ui.png" if evidence_dirs else reports[-1].parent / "adaptive-software-ui.png"
assert window.grab().save(str(ui_capture))
print({
    "pages": window.stack.count(),
    "targets": window.targetBox.count(),
    "timing_tabs": window.tabs[5].count(),
    "adaptive_columns": window.adaptiveTable.columnCount(),
    "adaptive_rows": window.adaptiveTable.rowCount(),
    "report_replay": True,
    "ui_capture": str(ui_capture),
    "success": True,
})
window.close()
