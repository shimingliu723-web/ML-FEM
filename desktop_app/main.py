from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from binary_audit import binary_locate
from code_audit import diff_targets, locate_code, performance_compare
from env_check import assess_environment
from env_report import get_environment_report
from formal_timing import run_formal_timing
from mlkem_service import get_mlkem, run_known_answer_test
from repair_manager import generate_repair, repair_and_compare
from reporting import generate_markdown_report, report_payload
from sample_generator import generate_samples
from target_manager import list_targets, register_target, run_target_command

APP_TITLE = "ML-KEM 时间侧信道检测与防护工具"


class WorkerSignals(QObject):
    ok = Signal(object)
    err = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.ok.emit(self.fn())
        except Exception:
            self.signals.err.emit(traceback.format_exc())


class Card(QFrame):
    def __init__(self, title: str, value: str = "-"):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel(value)
        self.value.setObjectName("cardValue")
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set(self, value: Any) -> None:
        self.value.setText(str(value))


def button(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("primaryButton" if primary else "toolButton")
    b.setMinimumHeight(32)
    return b


def kv_table(rows: list[tuple[str, Any]]) -> QTableWidget:
    table = QTableWidget(len(rows), 2)
    table.setHorizontalHeaderLabels(["项目", "值"])
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.horizontalHeader().setStretchLastSection(True)
    for r, (k, v) in enumerate(rows):
        table.setItem(r, 0, QTableWidgetItem(str(k)))
        table.setItem(r, 1, QTableWidgetItem(str(v)))
    return table


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 820)
        self.pool = QThreadPool.globalInstance()
        self.targets: list[dict] = []
        self._build_ui()
        self.refresh_targets()
        self.log("程序启动", "本地桌面模式，不依赖远程服务器")

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(230)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(16, 18, 16, 16)
        title = QLabel("ML-KEM\n检测与防护工具")
        title.setObjectName("sideTitle")
        side_layout.addWidget(title)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        for name in ["总览", "目标接入", "环境自检", "基础功能", "样本生成", "时间检测", "泄露定位", "自动修复", "性能评估", "报告导出"]:
            QListWidgetItem(name, self.nav)
        self.nav.currentRowChanged.connect(self._switch_page)
        side_layout.addWidget(self.nav, 1)

        self.targetBox = QComboBox()
        self.levelBox = QComboBox()
        self.levelBox.addItems(["512", "768", "1024"])
        self.levelBox.setCurrentText("512")
        side_layout.addWidget(QLabel("目标实现"))
        side_layout.addWidget(self.targetBox)
        side_layout.addWidget(QLabel("参数集"))
        side_layout.addWidget(self.levelBox)
        refresh = button("刷新目标")
        refresh.clicked.connect(self.refresh_targets)
        side_layout.addWidget(refresh)

        main = QFrame()
        main.setObjectName("main")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(18, 16, 18, 12)
        header = QHBoxLayout()
        self.pageTitle = QLabel("总览")
        self.pageTitle.setObjectName("pageTitle")
        self.status = QLabel("就绪")
        self.status.setObjectName("statusLabel")
        header.addWidget(self.pageTitle, 1)
        header.addWidget(self.status)
        main_layout.addLayout(header)

        self.stack = QStackedWidget()
        self.pages = [
            self._overview_page(),
            self._target_page(),
            self._env_check_page(),
            self._crypto_page(),
            self._samples_page(),
            self._timing_page(),
            self._locate_page(),
            self._repair_page(),
            self._performance_page(),
            self._report_page(),
        ]
        for p in self.pages:
            self.stack.addWidget(p)
        main_layout.addWidget(self.stack, 1)

        self.logBox = QPlainTextEdit()
        self.logBox.setObjectName("logBox")
        self.logBox.setReadOnly(True)
        self.logBox.setMaximumHeight(130)
        main_layout.addWidget(self.logBox)

        outer.addWidget(side)
        outer.addWidget(main, 1)
        self.nav.setCurrentRow(0)

    def _overview_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        grid = QGridLayout()
        self.ovTarget = Card("当前目标")
        self.ovLevel = Card("参数集")
        self.ovMode = Card("运行模式", "本地离线 / 可复现实验")
        self.ovRoot = Card("项目目录", str(ROOT))
        for i, c in enumerate([self.ovTarget, self.ovLevel, self.ovMode, self.ovRoot]):
            grid.addWidget(c, i // 2, i % 2)
        layout.addLayout(grid)
        self.overviewText = QTextEdit(); self.overviewText.setReadOnly(True)
        self.overviewText.setHtml("""
        <h3>作品定位</h3>
        <p>本工具是面向 ML-KEM 解封装实现的本地可视化检测与防护软件，支持目标实现接入、基本功能验证、样本生成、时间检测、源码/二进制定位、模式化修复、复测和报告导出。</p>
        <p><b>输入：</b>内置或用户接入的 ML-KEM 实现、参数集、样本规则、计时次数、CPU 核、修复策略。</p>
        <p><b>输出：</b>功能验证结果、时间统计报告、定位证据、修复补丁、修复前后对比和可复现报告。</p>
        <p><b>交付特点：</b>不依赖队伍服务器；可在本地 Linux/WSL2 环境部署；现场演示可加载预置结果或运行小规模实验。</p>
        """)
        layout.addWidget(self.overviewText, 1)
        return page

    def _target_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        intro = QTextEdit(); intro.setReadOnly(True); intro.setMaximumHeight(115)
        intro.setHtml("""
        <p><b>模块作用：</b>管理平台内置目标，并接入用户自己的 ML-KEM 实现。</p>
        <p>被测实现需要提供可调用的动态库路径模板，例如 <code>/path/to/libmlkem{level}.so</code>；平台将基于该目标执行样本生成、时间检测、定位和报告流程。</p>
        """)
        layout.addWidget(intro)

        grid = QGridLayout()
        self.regId = QLineEdit("custom_mlkem")
        self.regName = QLineEdit("自定义 ML-KEM 实现")
        self.regRole = QComboBox(); self.regRole.addItems(["custom", "baseline", "contrast", "repaired"])
        self.regLevels = QLineEdit("512,768,1024")
        self.regLib = QLineEdit(str(ROOT / "backend" / "lib" / "libmlkem{level}.so"))
        self.regBuild = QLineEdit("make all")
        self.regSelftest = QLineEdit("")
        fields = [
            ("目标ID", self.regId), ("显示名称", self.regName), ("类型", self.regRole),
            ("参数集", self.regLevels), ("动态库路径模板", self.regLib),
            ("构建命令", self.regBuild), ("自测命令", self.regSelftest),
        ]
        for i, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(widget, i, 1)
        layout.addLayout(grid)

        row = QHBoxLayout()
        reg = button("注册/更新目标", True)
        build = button("构建当前目标")
        selftest = button("运行当前目标自测")
        refresh = button("刷新目标列表")
        reg.clicked.connect(lambda: self.run_task("注册目标", self.register_current_target, self.show_register_result))
        build.clicked.connect(lambda: self.run_task("构建当前目标", lambda: run_target_command(self.target(), "build"), self.show_json))
        selftest.clicked.connect(lambda: self.run_task("运行当前目标自测", lambda: run_target_command(self.target(), "selftest"), self.show_json))
        refresh.clicked.connect(lambda: self.run_task("刷新目标列表", lambda: {"targets": list_targets()}, self.show_targets))
        row.addWidget(reg); row.addWidget(build); row.addWidget(selftest); row.addWidget(refresh); row.addStretch()
        layout.addLayout(row)

        grid2 = QGridLayout()
        self.targetCards = {k: Card(k) for k in ["目标数量", "当前目标", "目标类型", "库文件状态", "配置文件", "说明"]}
        for i, c in enumerate(self.targetCards.values()): grid2.addWidget(c, i//3, i%3)
        layout.addLayout(grid2)
        self.targetOut = QTextEdit(); self.targetOut.setReadOnly(True)
        layout.addWidget(self.targetOut, 1)
        return page

    def _env_check_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.envCpuBox = QSpinBox(); self.envCpuBox.setRange(0, 255); self.envCpuBox.setValue(0)
        run = button("运行环境自检", True)
        run.clicked.connect(lambda: self.run_task("环境自检", lambda: assess_environment(self.envCpuBox.value()), self.show_env_check))
        row.addWidget(QLabel("目标 CPU")); row.addWidget(self.envCpuBox); row.addWidget(run); row.addStretch()
        layout.addLayout(row)
        grid = QGridLayout()
        self.envCards = {k: Card(k) for k in ["总体等级", "正式计时", "推荐用途", "虚拟化", "频率策略", "抖动指标"]}
        for i, c in enumerate(self.envCards.values()): grid.addWidget(c, i//3, i%3)
        layout.addLayout(grid)
        tip = QTextEdit(); tip.setReadOnly(True)
        tip.setMaximumHeight(110)
        tip.setHtml("""
        <p><b>模块作用：</b>判断当前环境是否适合作为正式高精度计时实验环境。</p>
        <p>普通 WSL2/虚拟机仍可用于功能演示、样本生成、定位和修复流程验证；正式计时结论建议在 CPU 调度稳定、可固定核心、后台干扰较低的 Linux 服务器或真实 Linux 主机上生成。</p>
        """)
        layout.addWidget(tip)
        self.envOut = QTextEdit(); self.envOut.setReadOnly(True)
        layout.addWidget(self.envOut, 1)
        return page

    def _crypto_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout()
        run_demo = button("运行完整流程", True)
        run_self = button("连续自测 20 次")
        run_vec = button("公开向量验证")
        run_demo.clicked.connect(self.run_demo)
        run_self.clicked.connect(lambda: self.run_task("连续自测", lambda: get_mlkem(self.level()).selftest(20), self.show_json))
        run_vec.clicked.connect(lambda: self.run_task("公开向量验证", run_known_answer_test, self.show_json))
        row.addWidget(run_demo); row.addWidget(run_self); row.addWidget(run_vec); row.addStretch()
        layout.addLayout(row)
        grid = QGridLayout()
        self.cryptoCards = {k: Card(k) for k in ["KeyGen", "Encaps", "Decaps", "结果一致", "公钥长度", "密文长度"]}
        for i, c in enumerate(self.cryptoCards.values()): grid.addWidget(c, i//3, i%3)
        layout.addLayout(grid)
        self.cryptoOut = QTextEdit(); self.cryptoOut.setReadOnly(True)
        layout.addWidget(self.cryptoOut, 1)
        return page

    def _samples_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.sampleCount = QSpinBox(); self.sampleCount.setRange(2, 10000); self.sampleCount.setValue(32)
        gen = button("生成测试样本", True)
        gen.clicked.connect(lambda: self.run_task("生成测试样本", lambda: generate_samples(self.target(), self.level(), self.sampleCount.value()), self.show_json))
        row.addWidget(QLabel("每类数量")); row.addWidget(self.sampleCount); row.addWidget(gen); row.addStretch()
        layout.addLayout(row)
        self.sampleOut = QTextEdit(); self.sampleOut.setReadOnly(True)
        layout.addWidget(self.sampleOut, 1)
        return page

    def _timing_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.timingPairs = QSpinBox(); self.timingPairs.setRange(100, 100000); self.timingPairs.setValue(1000)
        self.cpuBox = QSpinBox(); self.cpuBox.setRange(0, 255); self.cpuBox.setValue(0)
        run = button("运行时间检测", True)
        run.clicked.connect(lambda: self.run_task("时间检测", lambda: run_formal_timing(self.level(), self.timingPairs.value(), self.cpuBox.value(), self.target()), self.show_timing))
        row.addWidget(QLabel("配对次数")); row.addWidget(self.timingPairs); row.addWidget(QLabel("CPU")); row.addWidget(self.cpuBox); row.addWidget(run); row.addStretch()
        layout.addLayout(row)
        grid = QGridLayout()
        self.timingCards = {k: Card(k) for k in ["正常均值(ns)", "改动均值(ns)", "配对差(ns)", "是否可区分", "正式检验", "报告路径"]}
        for i,c in enumerate(self.timingCards.values()): grid.addWidget(c, i//3, i%3)
        layout.addLayout(grid)
        self.timingOut = QTextEdit(); self.timingOut.setReadOnly(True)
        layout.addWidget(self.timingOut, 1)
        return page

    def _locate_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout()
        src = button("源码定位", True); binb = button("二进制定位") ; diff = button("源码差异")
        src.clicked.connect(lambda: self.run_task("源码定位", lambda: locate_code(self.target()), self.show_json))
        binb.clicked.connect(lambda: self.run_task("二进制定位", lambda: binary_locate(self.target(), self.level(), "mlkem_dec"), self.show_json))
        diff.clicked.connect(lambda: self.run_task("源码差异", lambda: diff_targets(self.target(), "variant_repaired"), self.show_json))
        row.addWidget(src); row.addWidget(binb); row.addWidget(diff); row.addStretch(); layout.addLayout(row)
        self.locateOut = QTextEdit(); self.locateOut.setReadOnly(True)
        layout.addWidget(self.locateOut, 1)
        return page

    def _repair_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.repairId = QLineEdit("variant_early_return")
        self.repairPairs = QSpinBox(); self.repairPairs.setRange(100, 50000); self.repairPairs.setValue(1000)
        gen = button("生成修复目标")
        run = button("修复并复测", True)
        gen.clicked.connect(lambda: self.run_task("生成修复目标", lambda: generate_repair(self.repairId.text().strip(), overwrite=True, build=True, validate_pairs=100, cpu=self.cpuBox.value()), self.show_json))
        run.clicked.connect(lambda: self.run_task("修复并复测", lambda: repair_and_compare(self.repairId.text().strip(), self.level(), self.repairPairs.value(), self.cpuBox.value(), True), self.show_repair))
        row.addWidget(QLabel("待修复目标")); row.addWidget(self.repairId); row.addWidget(QLabel("配对次数")); row.addWidget(self.repairPairs); row.addWidget(gen); row.addWidget(run)
        layout.addLayout(row)
        grid = QGridLayout()
        self.repairCards = {k: Card(k) for k in ["修复目标", "补丁摘要", "修复前差值", "修复后差值", "修复前可区分", "修复后可区分"]}
        for i,c in enumerate(self.repairCards.values()): grid.addWidget(c, i//3, i%3)
        layout.addLayout(grid)
        self.repairOut = QTextEdit(); self.repairOut.setReadOnly(True)
        layout.addWidget(self.repairOut, 1)
        return page

    def _performance_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout(); self.perfPairs = QSpinBox(); self.perfPairs.setRange(100, 20000); self.perfPairs.setValue(1000)
        run = button("运行性能评估", True)
        run.clicked.connect(lambda: self.run_task("性能评估", lambda: performance_compare(self.level(), self.perfPairs.value(), self.cpuBox.value()), self.show_json))
        row.addWidget(QLabel("配对次数")); row.addWidget(self.perfPairs); row.addWidget(run); row.addStretch(); layout.addLayout(row)
        self.perfOut = QTextEdit(); self.perfOut.setReadOnly(True)
        layout.addWidget(self.perfOut, 1)
        return page

    def _report_page(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout()
        prev = button("查看报告预览")
        gen = button("生成 Markdown 报告", True)
        prev.clicked.connect(lambda: self.run_task("报告预览", report_payload, self.show_json))
        gen.clicked.connect(lambda: self.run_task("生成报告", generate_markdown_report, self.show_json))
        row.addWidget(prev); row.addWidget(gen); row.addStretch(); layout.addLayout(row)
        self.reportOut = QTextEdit(); self.reportOut.setReadOnly(True)
        layout.addWidget(self.reportOut, 1)
        return page

    def _switch_page(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        self.pageTitle.setText(self.nav.item(row).text())

    def target(self) -> str:
        return self.targetBox.currentData() or self.targetBox.currentText() or "mlkem_native_baseline"

    def level(self) -> str:
        return self.levelBox.currentText()

    def refresh_targets(self) -> None:
        self.targets = list_targets()
        current = self.target()
        self.targetBox.clear()
        for t in self.targets:
            self.targetBox.addItem(t["name"], t["id"])
        idx = self.targetBox.findData(current)
        if idx >= 0: self.targetBox.setCurrentIndex(idx)
        self.ovTarget.set(self.target()) if hasattr(self, "ovTarget") else None
        self.ovLevel.set("ML-KEM-" + self.level()) if hasattr(self, "ovLevel") else None
        self.update_target_cards() if hasattr(self, "targetCards") else None

    def selected_target_info(self) -> dict:
        current = self.target()
        for target in self.targets:
            if target.get("id") == current:
                return target
        return {}

    def update_target_cards(self) -> None:
        info = self.selected_target_info()
        libs = info.get("libraries", {})
        ok_count = sum(1 for ok in libs.values() if ok)
        lib_status = f"{ok_count}/{len(libs)} 已存在" if libs else "未检查"
        self.targetCards["目标数量"].set(len(self.targets))
        self.targetCards["当前目标"].set(info.get("id", self.target()))
        self.targetCards["目标类型"].set(info.get("role", "-"))
        self.targetCards["库文件状态"].set(lib_status)
        self.targetCards["配置文件"].set(info.get("config", "-"))
        self.targetCards["说明"].set(info.get("description", "-"))

    def register_current_target(self) -> dict:
        levels = [x.strip() for x in self.regLevels.text().split(",") if x.strip()]
        payload = {
            "id": self.regId.text().strip(),
            "name": self.regName.text().strip(),
            "role": self.regRole.currentText(),
            "levels": levels,
            "library_template": self.regLib.text().strip(),
            "build_command": self.regBuild.text().strip(),
            "selftest_command": self.regSelftest.text().strip(),
            "description": "用户通过桌面端接入的 ML-KEM 实现，可作为平台检测、定位和报告流程的输入目标。",
        }
        return register_target(payload)

    def run_task(self, name: str, fn: Callable[[], Any], on_ok: Callable[[Any], None]) -> None:
        self.status.setText(f"正在执行：{name}")
        self.log(name, "开始")
        worker = Worker(fn)
        worker.signals.ok.connect(lambda result: self._task_ok(name, result, on_ok))
        worker.signals.err.connect(lambda error: self._task_err(name, error))
        self.pool.start(worker)

    def _task_ok(self, name: str, result: Any, on_ok: Callable[[Any], None]) -> None:
        self.status.setText("就绪")
        on_ok(result)
        self.log(name, "完成")

    def _task_err(self, name: str, error: str) -> None:
        self.status.setText("执行失败")
        self.log(name, "失败")
        QMessageBox.critical(self, "执行失败", error[-3000:])

    def log(self, name: str, detail: str) -> None:
        self.logBox.appendPlainText(f"[{name}] {detail}")

    def show_json(self, result: Any) -> None:
        text = json.dumps(result, ensure_ascii=False, indent=2)
        page = self.stack.currentWidget()
        for box in page.findChildren(QTextEdit):
            box.setPlainText(text)
            return

    def show_register_result(self, result: Any) -> None:
        self.refresh_targets()
        target_id = result.get("target") if isinstance(result, dict) else None
        if target_id:
            idx = self.targetBox.findData(target_id)
            if idx >= 0:
                self.targetBox.setCurrentIndex(idx)
        self.show_json(result)

    def show_targets(self, result: Any) -> None:
        self.refresh_targets()
        self.show_json(result)

    def run_demo(self) -> None:
        def job():
            engine = get_mlkem(self.level())
            return engine.demo()
        self.run_task("完整流程", job, self.show_crypto)

    def show_crypto(self, result: dict) -> None:
        t = result.get("timings_ns", {})
        self.cryptoCards["KeyGen"].set(t.get("keygen"))
        self.cryptoCards["Encaps"].set(t.get("encaps"))
        self.cryptoCards["Decaps"].set(t.get("decaps"))
        self.cryptoCards["结果一致"].set("是" if result.get("matched") else "否")
        sizes = result.get("sizes", {})
        self.cryptoCards["公钥长度"].set(sizes.get("public_key"))
        self.cryptoCards["密文长度"].set(sizes.get("ciphertext"))
        safe = {k: v for k, v in result.items() if k not in {"public_key", "secret_key", "ciphertext", "encapsulated_secret", "decapsulated_secret"}}
        self.cryptoOut.setPlainText(json.dumps(safe, ensure_ascii=False, indent=2))

    def show_timing(self, result: dict) -> None:
        a = result["analysis"]
        verdict = result.get("statistical_analysis", {}).get("verdict", {})
        self.timingCards["正常均值(ns)"].set(round(a["valid"]["mean_ns"], 2))
        self.timingCards["改动均值(ns)"].set(round(a["changed"]["mean_ns"], 2))
        self.timingCards["配对差(ns)"].set(round(a["paired_mean_difference_ns"], 2))
        self.timingCards["是否可区分"].set("是" if a["statistically_distinguishable"] else "否")
        self.timingCards["正式检验"].set("显著" if verdict.get("statistically_significant") else "未显著")
        self.timingCards["报告路径"].set(result.get("report_json"))
        self.timingOut.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))

    def show_env_check(self, result: dict) -> None:
        grade_map = {"green": "绿色：适合正式计时", "yellow": "黄色：仅建议功能演示", "red": "红色：基础环境不完整"}
        self.envCards["总体等级"].set(grade_map.get(result.get("grade"), result.get("grade")))
        self.envCards["正式计时"].set("适合" if result.get("formal_timing_ready") else "不建议")
        self.envCards["推荐用途"].set(result.get("recommended_use"))
        virt = result.get("virtualization", {})
        self.envCards["虚拟化"].set(virt.get("virtualization_kind"))
        freq = result.get("cpu_frequency", {})
        self.envCards["频率策略"].set(freq.get("governor"))
        jitter = result.get("jitter_probe", {})
        self.envCards["抖动指标"].set(f"p95/median={jitter.get('p95_over_median')}, max/median={jitter.get('max_over_median')}")
        self.envOut.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))

    def show_repair(self, result: dict) -> None:
        s = result["summary"]
        r = result["repair"]
        self.repairCards["修复目标"].set(r["repaired_id"])
        self.repairCards["补丁摘要"].set(r["patch_sha256"][:16])
        self.repairCards["修复前差值"].set(round(s["before_diff_ns"], 2))
        self.repairCards["修复后差值"].set(round(s["after_diff_ns"], 2))
        self.repairCards["修复前可区分"].set("是" if s["before_distinguishable"] else "否")
        self.repairCards["修复后可区分"].set("是" if s["after_distinguishable"] else "否")
        self.repairOut.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))


def apply_style(app: QApplication) -> None:
    app.setStyleSheet(r"""
    QWidget { font-family: 'Microsoft YaHei', 'Noto Sans CJK SC', Arial; font-size: 13px; color: #1f2937; }
    #sidebar { background: #f7f8fb; border-right: 1px solid #e5e7eb; }
    #sideTitle { font-size: 20px; font-weight: 800; color: #312e81; padding-bottom: 14px; }
    #nav { background: transparent; border: 0; }
    #nav::item { padding: 10px 12px; border-radius: 8px; margin: 2px 0; }
    #nav::item:selected { background: #5b5ce2; color: white; }
    #main { background: white; }
    #pageTitle { font-size: 24px; font-weight: 800; }
    #statusLabel { color: #047857; font-weight: 600; }
    #card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 10px; }
    #cardTitle { color: #6b7280; font-size: 12px; }
    #cardValue { color: #111827; font-size: 18px; font-weight: 700; }
    #primaryButton { background: #5b5ce2; color: white; border: 0; border-radius: 7px; padding: 6px 14px; font-weight: 700; }
    #toolButton { background: #eef2ff; color: #3730a3; border: 1px solid #c7d2fe; border-radius: 7px; padding: 6px 12px; font-weight: 600; }
    QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit { border: 1px solid #d1d5db; border-radius: 6px; padding: 5px; background: #ffffff; }
    #logBox { background: #111827; color: #d1fae5; font-family: Consolas, monospace; }
    QGroupBox { font-weight: 700; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding: 8px; }
    """)


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    apply_style(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
