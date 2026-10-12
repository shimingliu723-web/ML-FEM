from __future__ import annotations
import json, os, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from software_service import catalog, RESULTS
from PySide6.QtCore import Qt,QProcess,QUrl
from PySide6.QtGui import QFont,QFontDatabase,QPixmap,QDesktopServices,QPalette,QColor
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QGridLayout,
 QLabel,QPushButton,QComboBox,QSpinBox,QLineEdit,QPlainTextEdit,QTableWidget,QTableWidgetItem,
 QHeaderView,QStackedWidget,QListWidget,QFileDialog,QTabWidget,QProgressBar,QFrame)

NAMES=['工作台','实现管理','环境自检','基本功能与向量','输入样本','时间检测','代码定位','修复与对照','实验报告']
def label(text,name=''):
    w=QLabel(text); w.setWordWrap(True); w.setObjectName(name); return w
def button(text,fn,primary=False):
    w=QPushButton(text); w.clicked.connect(lambda:fn())
    if primary:w.setObjectName('primary')
    return w
def spin(a,b,v):
    w=QSpinBox(); w.setRange(a,b); w.setValue(v); return w
def table(headers):
    w=QTableWidget(0,len(headers)); w.setHorizontalHeaderLabels(headers); w.verticalHeader().hide()
    w.verticalHeader().setDefaultSectionSize(29); w.setAlternatingRowColors(True)
    w.setEditTriggers(QTableWidget.NoEditTriggers); w.setSelectionBehavior(QTableWidget.SelectRows)
    w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents); w.horizontalHeader().setStretchLastSection(True); return w
def fill(w,rows):
    w.setRowCount(len(rows))
    for i,row in enumerate(rows):
        for j,v in enumerate(row):
            s=f'{v:,.3f}' if isinstance(v,float) else str(v)
            item=QTableWidgetItem(s); item.setToolTip(s); w.setItem(i,j,item)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('ML-KEM 检测与防护软件'); self.resize(1380,880); self.setMinimumSize(1120,720)
        self.process=None; self.outputs={}; self.sample_by_level={}; self.current_report=''; self.last_error=''
        root=QWidget(); self.setCentralWidget(root); outer=QHBoxLayout(root); outer.setContentsMargins(0,0,0,0)
        side=QFrame(); side.setObjectName('sidebar'); side.setFixedWidth(195); sl=QVBoxLayout(side); sl.setContentsMargins(16,22,16,16)
        sl.addWidget(label('ML-KEM','brand')); sl.addWidget(label('检测 · 定位 · 防护','muted'))
        self.nav=QListWidget(); self.nav.addItems(NAMES); self.nav.currentRowChanged.connect(self.switch); sl.addWidget(self.nav,1)
        sl.addWidget(label('桌面软件 · 本机执行\n结果按实验独立保存','muted')); outer.addWidget(side)
        content=QWidget(); body=QVBoxLayout(content); body.setContentsMargins(16,14,16,12)
        top=QHBoxLayout(); self.heading=label('工作台','heading'); top.addWidget(self.heading,1)
        self.targetBox=QComboBox(); self.targetBox.setMinimumWidth(255); self.levelBox=QComboBox(); self.levelBox.addItems(['512','768','1024'])
        self.cpuBox=QComboBox(); self.cpuBox.addItems([str(n) for n in sorted(os.sched_getaffinity(0))] if hasattr(os,'sched_getaffinity') else ['0'])
        for name,w in [('实现',self.targetBox),('参数集',self.levelBox),('CPU',self.cpuBox)]:top.addWidget(label(name)); top.addWidget(w)
        body.addLayout(top); self.context=label('','context'); body.addWidget(self.context)
        self.stack=QStackedWidget(); self.layouts=[]; self.tables={}; self.details={}; self.summaries={}; self.tabs={}
        for name in NAMES:
            p=QWidget(); l=QVBoxLayout(p); l.setContentsMargins(0,8,0,0); self.layouts.append(l); self.stack.addWidget(p)
        self.build_pages(); body.addWidget(self.stack,1)
        self.progress=QProgressBar(); self.progress.setMaximumHeight(6); self.progress.setTextVisible(False); self.progress.hide(); body.addWidget(self.progress)
        self.status=label('就绪','status'); body.addWidget(self.status)
        self.logBox=QPlainTextEdit(); self.logBox.setReadOnly(True); self.logBox.setMaximumHeight(68); self.logBox.setObjectName('log'); body.addWidget(self.logBox)
        outer.addWidget(content,1); self.refresh_targets()
        self.targetBox.currentIndexChanged.connect(self.selection_changed); self.levelBox.currentIndexChanged.connect(self.selection_changed)
        self.nav.setCurrentRow(0); self.selection_changed(); self.refresh_history()
    def target(self):return self.targetBox.currentData()
    def level(self):return self.levelBox.currentText()
    def cpu(self):return int(self.cpuBox.currentText())
    def switch(self,i):
        if i>=0:self.stack.setCurrentIndex(i); self.heading.setText(NAMES[i])
    def row(self,i,*items):
        r=QHBoxLayout()
        for item in items:r.addWidget(label(item) if isinstance(item,str) else item)
        r.addStretch(); self.layouts[i].addLayout(r)
    def result_area(self,i,headers):
        self.summaries[i]=label('等待运行','summary'); self.layouts[i].addWidget(self.summaries[i]); tabs=QTabWidget(); self.tabs[i]=tabs
        self.tables[i]=table(headers); tabs.addTab(self.tables[i],'结果明细'); self.details[i]=QPlainTextEdit(); self.details[i].setReadOnly(True)
        tabs.addTab(self.details[i],'完整报告 / 证据'); self.layouts[i].addWidget(tabs,1); return tabs
    def build_pages(self):
        l=self.layouts[0]; l.addWidget(label('从正确性验证到修复复测，一套软件完成','hero'))
        l.addWidget(label('七个内置目标 + 外部接入。各模块通过目标指纹、样本摘要和报告编号串联。','muted')); grid=QGridLayout()
        for i,(title,desc,page) in enumerate([
          ('01  基础 ML-KEM 功能','选择实现 → 批量自测 → 导入公开 / 自有向量\n逐项比较期望结果，保存验证明细',3),
          ('02  时间检测与防护','环境自检 → 多轮计时 → 源码 / 二进制定位\n支持模式生成补丁 → 正确性回归 → 同样本复测',2),
          ('03  输入样本工作台','正常输入 + 首部 / 中部 / 尾部变化\n保持长度一致，在实现之间复用数据集',4)]):
            f=QFrame(); f.setObjectName('card'); box=QVBoxLayout(f); box.addWidget(label(title,'cardTitle')); box.addWidget(label(desc)); box.addWidget(button('进入模块',lambda p=page:self.nav.setCurrentRow(p),True)); grid.addWidget(f,0,i)
        l.addLayout(grid); overview=table(['软件能力','验收依据','适用范围'])
        fill(overview,[('基本功能','所选目标自测 + 公开向量逐项比较','512 / 768 / 1024；批量导入'),('环境测量','固定CPU的C探针、时钟开销、抖动和前后检查','Linux / WSL；计时结论受环境限制'),('时间检测','每轮CSV + 配对统计 + 95%区间','等长输入，默认10000对 × 3轮'),('定位与防护','源码规则 + 反汇编证据 + 补丁 + 正确性回归','自动修复覆盖已适配比较函数'),('可复现报告','目标/样本/计时器摘要 + 参数 + 原始数据包','结论来自实测；普通报告不含秘密材料')]); l.addWidget(overview,1)
        l.addWidget(label('七个内置目标属于同一代码基础的对照系列。未检出时间差异不能证明实现绝对常数时间。','muted'))
        self.layouts[1].addWidget(label('接入已编译的可信本地 .so 库；需导出 mlkem_keypair、mlkem_enc、mlkem_dec。接入后检查符号并验证功能。适配说明见 docs/SOFTWARE.md。'))
        self.regId=QLineEdit('custom_my_mlkem'); self.regName=QLineEdit('我的 ML-KEM 实现'); self.regLib=QLineEdit(); self.regLib.setPlaceholderText('/path/libmlkem{level}.so 或单个 .so')
        self.regLevels=QLineEdit('512,768,1024'); self.regCompiler=QLineEdit('unknown'); self.regFlags=QLineEdit('unknown'); self.regSource=QLineEdit(); self.regSource.setPlaceholderText('可选，包含src/verify.h和src/kem.c的源码目录'); g=QGridLayout()
        for i,(name,w) in enumerate([('目标ID',self.regId),('名称',self.regName),('参数集',self.regLevels),('库路径模板',self.regLib),('编译器（用户提供）',self.regCompiler),('编译选项（用户提供）',self.regFlags)]):g.addWidget(label(name),i//2,i%2*2); g.addWidget(w,i//2,i%2*2+1)
        self.layouts[1].addLayout(g); self.row(1,'源码定位（可选）',self.regSource,button('选择源码',self.pick_source)); self.row(1,button('选择库',self.pick_library),button('接入并验证',self.import_target,True),button('刷新',self.refresh_targets)); self.result_area(1,['目标ID','来源','参数集','库就绪'])
        self.row(2,button('测量当前环境',lambda:self.launch('environment',{'cpu':self.cpu()},2),True),'固定CPU C探针1000次 · 时钟开销 · 运行抖动 · 系统信息'); self.result_area(2,['检查项目','结果','说明'])
        self.iterations=spin(1,10000,100); self.basicRange=QComboBox(); self.basicRange.addItems(['当前参数集','所选实现的全部参数集'])
        self.row(3,'自测次数',self.iterations,self.basicRange,button('流程自测 + 公开向量',self.run_basic,True))
        self.vectorInput=QPlainTextEdit(); self.vectorInput.setMaximumHeight(90); self.vectorInput.setPlaceholderText('粘贴JSON数组/JSONL：level、ct、sk、ss（Base64）；ss为必需的期望结果。原始材料不写入日志。'); self.layouts[3].addWidget(self.vectorInput)
        self.row(3,button('读取向量文件',self.pick_vectors),button('验证输入向量',lambda:self.run_basic(True)),button('清空',self.vectorInput.clear),'最多5000条；逐项比较'); self.result_area(3,['类型/编号','参数集','通过/总数','结果或比较依据'])
        self.sampleCount=spin(1,4096,512); self.row(4,'每类数量',self.sampleCount,button('生成四类等长样本',lambda:self.launch('samples',{'target_id':self.target(),'level':self.level(),'count':self.sampleCount.value()},4),True))
        self.layouts[4].addWidget(label('样本清单用于检测与修复复测。实验材料受限权限保存在本机；报告只记录规则、数量和摘要。')); self.result_area(4,['类别','修改规则','数量','输入长度（字节）'])
        self.samplePath=QLineEdit(); self.samplePath.setPlaceholderText('先生成样本，或选择已有 samples.json'); self.row(5,'样本清单',self.samplePath,button('选择清单',self.pick_samples))
        self.pairs=spin(100,100000,10000); self.repeats=spin(1,10,3); self.category=QComboBox(); self.category.addItems(['首部单比特变化','中部单比特变化','尾部单比特变化']); self.category.setCurrentIndex(1)
        self.row(5,'每轮配对数',self.pairs,'轮数',self.repeats,self.category,button('环境检查并检测',lambda:self.launch('detect',self.timing_args(),5),True),button('进入定位',lambda:self.nav.setCurrentRow(6)))
        tabs=self.result_area(5,['轮次','正常均值ns','变化均值ns','配对差ns','95%区间ns','主检验','环境']); self.plot=QLabel(); self.plot.setAlignment(Qt.AlignCenter); tabs.addTab(self.plot,'分布与置信区间')
        self.row(6,button('定位所选实现',lambda:self.launch('locate',{'target_id':self.target(),'level':self.level()},6),True),button('进入修复',lambda:self.nav.setCurrentRow(7)))
        self.layouts[6].addWidget(label('源码模式对应重加密验证环节；反汇编列出候选控制流证据。条件跳转数量不能直接证明敏感依赖。')); self.result_area(6,['证据类型','位置 / 指令','说明'])
        self.layouts[7].addWidget(label('沿用时间检测页的样本、类别、配对数、轮数和CPU。原目标保留；补丁生成独立目标，全部支持参数集通过自测和公开向量后，再复测同一批输入。'))
        self.row(7,button('执行定位 → 修复 → 功能回归 → 对照',lambda:self.launch('repair',self.timing_args(),7),True)); self.result_area(7,['轮次 / 类别','修复前均值ns','修复后均值ns','前p50 / p95','后p50 / p95','开销%'])
        self.row(8,button('刷新记录',self.refresh_history),button('查看选中报告',self.open_report),button('在模块中查看',self.replay_report),button('导出选中证据包',self.export_selected,True),button('打开结果目录',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(RESULTS)))))
        self.result_area(8,['时间','模块','目标','结论 / 状态','报告路径']); self.tables[8].doubleClicked.connect(self.open_report)
    def refresh_targets(self):
        old=self.target(); self.targetBox.blockSignals(True); self.targetBox.clear(); self.targets=catalog()
        for t in self.targets:self.targetBox.addItem(t['name'],t['id'])
        i=self.targetBox.findData(old)
        if i>=0:self.targetBox.setCurrentIndex(i)
        self.targetBox.blockSignals(False); fill(self.tables[1],[(t['id'],t['origin'],','.join(t['levels']),f"{sum(t['libraries'].values())}/{len(t['libraries'])}") for t in self.targets])
    def selection_changed(self):
        info=next((t for t in self.targets if t['id']==self.target()),{}); levels=info.get('levels',['512','768','1024']); old=self.level()
        self.levelBox.blockSignals(True); self.levelBox.clear(); self.levelBox.addItems(levels)
        if old in levels:self.levelBox.setCurrentText(old)
        self.levelBox.blockSignals(False); self.context.setText(f"当前目标：{self.target()}  /  ML-KEM-{self.level()}  ·  {info.get('origin','')}")
        for p in (3,5,6,7):self.tables[p].setRowCount(0); self.details[p].clear(); self.summaries[p].setText('尚未对当前选择运行；不会沿用其他实现的结论。')
        self.plot.clear(); self.samplePath.setText(self.sample_by_level.get(self.level(),''))
    def pick_library(self):
        p,_=QFileDialog.getOpenFileName(self,'选择可信本地动态库',str(ROOT),'Linux library (*.so)')
        if p:self.regLib.setText(p)
    def import_target(self):
        self.launch('import',{'target_id':self.regId.text().strip(),'name':self.regName.text().strip(),'library_template':self.regLib.text().strip(),'levels':[s.strip() for s in self.regLevels.text().split(',')],'compiler':self.regCompiler.text(),'flags':self.regFlags.text(),'source_root':self.regSource.text().strip()},1)
    def pick_source(self):
        p=QFileDialog.getExistingDirectory(self,'选择用于定位的源码目录',str(ROOT))
        if p:self.regSource.setText(p)
    def pick_vectors(self):
        p,_=QFileDialog.getOpenFileName(self,'读取向量',str(ROOT/'data'),'Vectors (*.json *.jsonl)')
        if p:
            try:self.vectorInput.setPlainText(Path(p).read_text(encoding='utf-8'))
            except Exception:self.status.setText('无法读取文件')
    def run_basic(self,custom=False):
        levels=[self.level()] if self.basicRange.currentIndex()==0 else next(t['levels'] for t in self.targets if t['id']==self.target())
        args={'target_id':self.target(),'levels':levels,'iterations':self.iterations.value()}
        if custom:args['vector_text']=self.vectorInput.toPlainText()
        self.launch('basic',args,3)
    def pick_samples(self):
        p,_=QFileDialog.getOpenFileName(self,'选择样本清单',str(ROOT/'results/samples'),'Manifest (*.json)')
        if p:self.samplePath.setText(p)
    def timing_args(self):return {'target_id':self.target(),'level':self.level(),'sample_report':self.samplePath.text().strip(),'pairs':self.pairs.value(),'cpu':self.cpu(),'repeats':self.repeats.value(),'category':self.category.currentIndex()+1}
    def refresh_history(self):
        rows=[]
        for p in sorted(RESULTS.glob('*/report.json'),reverse=True)[:200]:
            try:
                d=json.loads(p.read_text()); rows.append((d.get('created_at',''),d.get('kind',''),d.get('target_id','环境'),d.get('conclusion',str(d.get('success','已记录'))),str(p)))
            except (OSError,ValueError):continue
        fill(self.tables[8],rows)
    def selected_report(self):
        r=self.tables[8].currentRow(); return self.tables[8].item(r,4).text() if r>=0 else self.current_report
    def open_report(self):
        p=self.selected_report()
        if p:self.details[8].setPlainText(Path(p).read_text()); self.summaries[8].setText(p); self.tabs[8].setCurrentIndex(1)
    def replay_report(self):
        p=self.selected_report()
        if not p:return
        d=json.loads(Path(p).read_text()); pages={'basic':3,'environment':2,'detection':5,'location':6,'repair':7}
        page=pages.get(d.get('kind'))
        if page is None:self.open_report();return
        self.refresh_targets();idx=self.targetBox.findData(d.get('target_id'))
        if idx>=0:self.targetBox.setCurrentIndex(idx)
        if d.get('level'):self.levelBox.setCurrentText(str(d['level']))
        if d.get('runs'):
            r=d['runs'][0];self.pairs.setValue(r['pairs']);self.repeats.setValue(len(d['runs']));self.cpuBox.setCurrentText(str(r['cpu']))
            self.samplePath.setText(r.get('sample_manifest',''))
            self.category.setCurrentIndex(['changed_first_b64','changed_mid_b64','changed_last_b64'].index(r['category']))
        self.render_result(page,d);self.nav.setCurrentRow(page);self.status.setText('历史结果回放：'+p)
    def export_selected(self):
        p=self.selected_report()
        if p:self.launch('export',{'report_path':p},8)
        else:self.status.setText('请先选择或生成报告')
    def launch(self,action,args,page):
        if self.process is not None:return
        self.last_error=''; self.nav.setCurrentRow(page); self.status.setText(f"正在执行 {NAMES[page]} · {args.get('target_id','本机环境')}")
        self.logBox.appendPlainText(time.strftime('%H:%M:%S')+f"  开始 {action} / {args.get('target_id','local')}")
        for w in (self.stack,self.targetBox,self.levelBox,self.cpuBox):w.setEnabled(False)
        self.progress.setRange(0,0); self.progress.show(); proc=QProcess(self); self.process=proc; self.pending=(action,page)
        proc.setWorkingDirectory(str(ROOT)); proc.setProgram(sys.executable); proc.setArguments([str(ROOT/'backend/software_service.py')])
        payload=json.dumps({'action':action,'args':args},ensure_ascii=False).encode('utf-8')
        proc.started.connect(lambda:(proc.write(payload),proc.closeWriteChannel())); proc.finished.connect(self.finished)
        proc.errorOccurred.connect(self.process_error); proc.start()
    def process_error(self,error):
        if error==QProcess.FailedToStart:self.finished(-1,QProcess.CrashExit)
        else:self.status.setText('工作进程异常，正在记录失败状态')
    def finished(self,code,exit_status):
        proc=self.process
        if proc is None:return
        action,page=self.pending; raw=bytes(proc.readAllStandardOutput()).decode('utf-8',errors='replace')
        try:
            d=json.loads(raw)
            if code or 'error' in d:raise ValueError(d.get('message','执行失败'))
            self.render_result(page,d); self.outputs[page]=d; self.current_report=d.get('report_json',self.current_report)
            self.status.setText('任务完成，结果已保存' if d.get('success',True) else '存在未通过项，请查看明细')
            self.logBox.appendPlainText(time.strftime('%H:%M:%S')+f"  完成 {action} · {d.get('report_json','见报告页')}")
            if action in {'import','repair'}:self.refresh_targets()
            self.refresh_history()
        except Exception as exc:
            self.last_error=str(exc) if raw.strip().startswith('{') else f'进程退出（{code}）；检查接口与依赖。输入内容未写入日志'
            self.status.setText(self.last_error); self.summaries[page].setText('未完成：'+self.last_error)
        finally:
            proc.deleteLater(); self.process=None
            for w in (self.stack,self.targetBox,self.levelBox,self.cpuBox):w.setEnabled(True)
            self.progress.hide()
    def render_result(self,p,d):
        self.details[p].setPlainText(json.dumps(d,ensure_ascii=False,indent=2)); summary=d.get('conclusion','')
        if p==1:summary='接入检查：'+('通过' if d.get('success') else '未通过，查看明细')
        elif p==2:
            n=d['native_probe']; summary=f"等级 {d['grade'].upper()} | p95/中位数 {n['p95_over_median']:.3f} | 时钟开销 {n['clock_overhead_median_ns']} ns | {d['conclusion']}"
            fill(self.tables[p],[(c['name'],'通过' if c['ok'] else '需关注',c['detail']) for c in d['checks']])
        elif p==3:
            rows=[('流程自测',r['level'],f"{r['passed']}/{r['total']}",'KeyGen → Encaps → Decaps，逐次比较') for r in d['selftests']]
            for r in d['selftests']:
                for operation,ns in r['mean_ns'].items():rows.append((operation,r['level'],f"{r['total']} 次调用",f'平均 {ns:.2f} ns（功能层测量，非正式C计时）'))
            rows += [(f"向量 {r['index']}",r['level'],'通过' if r['passed'] else '未通过',r['reason']) for r in d['vectors']['results']]; fill(self.tables[p],rows)
            summary=f"目标 {d['target_id']} | 向量 {d['vectors']['passed']}/{d['vectors']['total']} | {d['scope']}"
        elif p==4:
            fill(self.tables[p],[(n,r,d['count'],d['ciphertext_bytes']) for n,r in [('normal','正常生成'),('changed_first','首字节翻转1位'),('changed_mid','中间字节翻转1位'),('changed_last','末字节翻转1位')]])
            self.sample_by_level[self.level()]=d['report_json']; self.samplePath.setText(d['report_json']); summary=f"已生成 {d['count']*4} 条等长输入，已连接检测与复测。"
        elif p==5 and d.get('success'):
            rows=[]
            shown=[(f"A/A {i+1}",r) for i,r in enumerate(d.get('controls',[]))]+[(str(i+1),r) for i,r in enumerate(d['runs'])]
            for name,r in shown:
                a=r['analysis']; v=r['statistics']['verdict']; rows.append((name,a['valid']['mean_ns'],a['changed']['mean_ns'],a['paired_mean_difference_ns'],' ~ '.join(f'{x:.2f}' for x in a['paired_difference_ci95_ns']),'显著' if v['statistically_significant'] else ('检验不一致' if not v['tests_agree'] else '未显著'),'预检通过' if d['formal_environment'] else '探索测量'))
            fill(self.tables[p],rows); self.plot.setPixmap(QPixmap(d['runs'][-1]['chart_png']).scaled(1010,390,Qt.KeepAspectRatio,Qt.SmoothTransformation)); summary=d['conclusion']+'。'+d['scope']
        elif p==6:
            s=d['source']; b=d['binary']; rows=[('源码模式',s['compare_style'],s['summary'])]
            rows += [(f['title'],f['path'],'匹配行：'+str(f['matches']) if f['found'] else '未找到') for f in s['findings']]
            rows += [('二进制候选',f['line'],f['note']) for f in b['findings']]; fill(self.tables[p],rows); summary=s['summary']+' '+d['scope']
        elif p==7 and 'performance' in d:
            fill(self.tables[p],[(f"{r['round']} / {r['class']}",r['before_mean_ns'],r['after_mean_ns'],f"{r['before_p50_ns']:.1f} / {r['before_p95_ns']:.1f}",f"{r['after_p50_ns']:.1f} / {r['after_p95_ns']:.1f}",r['overhead_percent']) for r in d['performance']])
            summary=f"{d['conclusion']}。补丁目标 {d['repaired_id']}；平均绝对差 {d['mean_abs_diff_before_ns']:.2f} → {d['mean_abs_diff_after_ns']:.2f} ns"
        elif p==8:summary=f"证据包 {d.get('zip','')} · 文件数 {d.get('files','')}"
        self.summaries[p].setText(summary or d.get('reason','已完成；查看完整报告'))
    def closeEvent(self,e):
        if self.process is not None:self.status.setText('任务仍在执行，请等待结果保存后关闭'); e.ignore()
        else:e.accept()

def apply_style(app):
    fonts=QFontDatabase.families(); chosen=next((f for f in ['Noto Sans CJK SC','WenQuanYi Micro Hei','Droid Sans Fallback','Microsoft YaHei'] if f in fonts),'Sans Serif')
    app.setFont(QFont(chosen,10)); app.setStyle('Fusion')
    palette=QPalette()
    for role,color in [(QPalette.Window,'#f7f7f7'),(QPalette.WindowText,'#242424'),
                       (QPalette.Base,'#ffffff'),(QPalette.AlternateBase,'#fafafa'),
                       (QPalette.Text,'#242424'),(QPalette.Button,'#ffffff'),
                       (QPalette.ButtonText,'#242424'),(QPalette.Highlight,'#dedede'),
                       (QPalette.HighlightedText,'#171717'),(QPalette.Link,'#444444')]:
        palette.setColor(role,QColor(color))
    app.setPalette(palette)
    app.setStyleSheet('''
    QWidget{color:#242424;font-size:13px;} QMainWindow{background:#f7f7f7;}
    #sidebar{background:white;border-right:1px solid #e4e4e4;}
    #brand{font-size:26px;font-weight:700;color:#202020;}
    QListWidget{background:transparent;border:0;outline:0;color:#616161;}
    QListWidget::item{padding:12px 9px;margin:2px 0;border-radius:4px;}
    QListWidget::item:hover{background:#f5f5f5;}
    QListWidget::item:selected{background:#ededed;color:#171717;border-left:3px solid #444444;}
    #heading{font-size:21px;font-weight:bold;} #hero{font-size:22px;font-weight:bold;margin:12px 0;}
    #muted{color:#777777;} #context{padding:8px 0;color:#666666;border-bottom:1px solid #e5e5e5;}
    #card{background:white;border:1px solid #e1e1e1;border-radius:6px;padding:10px;}
    #cardTitle{font-weight:bold;font-size:16px;}
    #summary{background:white;color:#333333;border:1px solid #e2e2e2;border-radius:4px;padding:10px;}
    QPushButton{background:white;border:1px solid #d5d5d5;border-radius:4px;padding:7px 12px;min-height:20px;}
    QPushButton:hover{background:#f1f1f1;border-color:#aaaaaa;}
    QPushButton:pressed{background:#e8e8e8;}
    QPushButton#primary{background:#333333;color:white;border:1px solid #333333;}
    QPushButton#primary:hover{background:#4b4b4b;border-color:#4b4b4b;}
    QPushButton:disabled,QPushButton#primary:disabled{color:#999999;background:#efefef;border-color:#e1e1e1;}
    QLineEdit,QComboBox,QSpinBox{background:white;border:1px solid #d8d8d8;border-radius:4px;padding:6px;}
    QLineEdit:focus,QComboBox:focus,QSpinBox:focus{border-color:#888888;}
    QTableWidget,QPlainTextEdit{background:white;alternate-background-color:#fafafa;border:1px solid #e0e0e0;
        gridline-color:#eeeeee;selection-background-color:#e7e7e7;selection-color:#171717;}
    QHeaderView::section{background:#f4f4f4;padding:7px;border:0;border-bottom:1px solid #dddddd;
        border-right:1px solid #e7e7e7;font-weight:bold;}
    QTabWidget::pane{background:white;border:1px solid #e0e0e0;}
    QTabBar::tab{padding:8px 16px;background:#f3f3f3;color:#777777;border-bottom:2px solid transparent;}
    QTabBar::tab:selected{background:white;color:#242424;border-bottom:2px solid #555555;}
    #log{background:#f3f3f3;color:#666666;border:1px solid #e3e3e3;}
    #status{color:#666666;} QProgressBar{background:#eeeeee;border:0;}
    QProgressBar::chunk{background:#777777;} QToolTip{background:white;color:#333333;border:1px solid #cccccc;}
    ''')
def main():
    app=QApplication(sys.argv); apply_style(app); window=MainWindow(); window.show(); return app.exec()
if __name__=='__main__':raise SystemExit(main())
