"""Headless acceptance for adaptive, network-noise and cross-build entries."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_app"))

from PySide6.QtWidgets import QApplication, QPushButton
from software import MainWindow

app = QApplication.instance() or QApplication([])
window = MainWindow()
buttons = {button.text() for button in window.findChildren(QPushButton)}
expected = {
    "运行自适应序贯检测",
    "运行网络噪声稳定性验证",
    "运行跨编译器 / 优化级别验证",
}
assert expected <= buttons, expected - buttons
assert window.adaptiveTable.columnCount() == 7
assert window.networkTable.columnCount() == 7
assert window.crossBuildTable.columnCount() == 7
assert window.tabs[5].indexOf(window.adaptiveTable) >= 0
assert window.tabs[5].indexOf(window.networkTable) >= 0
assert window.tabs[5].indexOf(window.crossBuildTable) >= 0
print("ADVANCED_VALIDATION_UI_PASS")
