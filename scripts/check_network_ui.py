#!/usr/bin/env python3
"""Headless acceptance check for the network-noise desktop entry."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QPushButton
from desktop_app.software import MainWindow


def main() -> int:
    app = QApplication([])
    window = MainWindow()
    button_texts = {button.text() for button in window.findChildren(QPushButton)}
    assert "运行网络噪声稳定性验证" in button_texts
    assert window.networkTable.columnCount() == 7
    assert window.networkPlot is not None
    print("NETWORK_UI_OK")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
