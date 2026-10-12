"""Desktop application services. No HTTP server; reports are scoped to each run."""
from __future__ import annotations
import base64
import csv
import hashlib
import json
import os
import platform
import shutil
import statistics
import struct
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

from target_manager import get_target, list_targets, register_target, run_target_command, _safe_id
from mlkem_service import MLKEM, PARAMETERS
from vector_validation import validate_vectors
from sample_generator import generate_samples
from stats import analyze_file, percentile
from formal_timing import analyze_csv
from env_check import assess_environment

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "software"
BUILTINS = ["mlkem_native_baseline", "variant_early_return", "variant_early_return_while",
            "variant_early_return_xor", "variant_repaired", "variant_repaired_while", "variant_repaired_xor"]
VECTORS = ROOT / "data/acvp/platform_vectors/mlkem_decap_official_direct.json"
RUNNER = ROOT / "experiments/software_measure"
CLASSES = ["normal_b64", "changed_first_b64", "changed_mid_b64", "changed_last_b64"]

def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""): h.update(block)
    return h.hexdigest()

def new_run(kind):
    p = RESULTS / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + "-" + kind)
    p.mkdir(parents=True)
    return p

def save(directory, result):
    result["report_json"] = str(directory / "report.json")
    result["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (directory / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result

def catalog():
    registry = {t["id"]: t for t in list_targets()}
    return [dict(registry[t], origin="内置对照系列（同一代码基础）") for t in BUILTINS if t in registry] + [dict(t, origin="外部接入") for t in registry.values() if t["role"] == "custom"] + [dict(t, origin="本机生成的修复产物") for t in registry.values() if t["id"].startswith("repair_") and t["role"]=="repaired"]

def validate_basic(target_id, levels=None, iterations=100, vector_text=None):
    target = get_target(target_id)
    levels = levels or target.levels
    if not 1 <= int(iterations) <= 10000: raise ValueError("自测次数范围 1–10000")
    rows, fingerprints = [], {}
    for level in levels:
        library = target.library_for(level)
        engine = MLKEM(level, library_path=library)
        fingerprints[level] = digest(library)
        totals = {k: 0 for k in ("keygen", "encaps", "decaps")}
        passed = 0
        for _ in range(int(iterations)):
            kp = engine.keygen(record=False)
            en = engine.encaps(kp["public_key"], record=False)
            de = engine.decaps(en["ciphertext"], kp["secret_key"], record=False)
            passed += en["shared_secret"] == de["shared_secret"]
            for k, v in zip(totals, (kp,en,de)): totals[k] += v["elapsed_ns"]
        rows.append({"level": level, "passed": passed, "total": iterations,
                     "mean_ns": {k: v/iterations for k,v in totals.items()}})
    official = vector_text is None
    if official:
        items = json.loads(VECTORS.read_text(encoding="utf-8"))
        items = [v for v in items if str(v.get("level", "")).replace("ML-KEM-", "") in levels]
        vector_text = json.dumps(items)
    from software_vectors import validate_official
    checked = validate_official(target_id,levels) if official else None
    full_official = checked is not None
    if checked is None: checked = validate_vectors(vector_text, levels[0], target_id)
    return save(new_run("basic"), {"kind":"basic", "target_id":target_id, "levels":levels,
        "success": all(r["passed"] == r["total"] for r in rows) and checked["success"],
        "selftests":rows, "vectors":checked, "library_sha256":fingerprints,
        "vector_source":str(ROOT/"data/acvp") if full_official else (str(VECTORS) if official else "用户导入的测试向量"),
        "vector_file_sha256":digest(VECTORS) if official else None,
        "scope":"随机流程一致性 + 所选目标435项官方向量库按参数集验证（KeyGen/Encaps/Decaps/输入检查）；不等同于认证。" if full_official else "随机流程一致性 + 所选目标解封装向量逐项比较；确定性扩展接口不可用或本次为用户向量。"})

def import_target(target_id, name, library_template, levels, source_root="", compiler="unknown", flags="unknown"):
    target_id = _safe_id(target_id)
    if not target_id.startswith("custom_"): raise ValueError("外部目标 ID 必须以 custom_ 开头")
    if (ROOT/"targets"/target_id).exists(): raise ValueError("目标ID已存在，请为新版本使用新ID")
    if not levels: raise ValueError("至少选择一个参数集")
    # Copy supplied trusted local libraries to a managed directory. No user build commands.
    directory = ROOT/"targets"/target_id
    paths = {}
    for level in levels:
        if level not in PARAMETERS: raise ValueError("不支持的参数集")
        path = Path(library_template.format(level=level)).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix != ".so": raise ValueError("请选择 Linux .so 动态库")
        symbols = subprocess.run(["nm","-D","--defined-only",str(path)],capture_output=True,text=True,check=True).stdout
        names = {line.split()[-1] for line in symbols.splitlines() if line.split()}
        if not {"mlkem_keypair","mlkem_enc","mlkem_dec"} <= names: raise ValueError("动态库缺少适配接口；请按文档提供三个 C 导出函数")
        paths[level] = path
    copied_source = None
    if source_root:
        source = Path(source_root).expanduser().resolve(strict=True)
        if not (source/"src/verify.h").is_file() or not (source/"src/kem.c").is_file():
            raise ValueError("源码目录需包含 src/verify.h 和 src/kem.c；其他结构目前仅支持二进制分析")
        # Source is optional location evidence. It is not assumed to reproduce the supplied binary.
        files=list(source.rglob("*"))
        if any(f.is_symlink() for f in files) or sum(f.stat().st_size for f in files if f.is_file()) > 32*1024*1024:
            raise ValueError("源码目录不能含符号链接，且总大小不得超过32MB")
        copied_source=directory/"src/mlkem"
    directory.mkdir(parents=True)
    (directory/"lib").mkdir()
    for level,path in paths.items(): shutil.copy2(path,directory/"lib"/f"libmlkem{level}.so")
    if copied_source:
        shutil.copytree(source,copied_source)
    result = register_target({"id":target_id,"name":name,"role":"custom","levels":levels,
        "library_template":f"targets/{target_id}/lib/libmlkem{{level}}.so","description":"用户接入的本地实现；不自动承诺源码修复能力"})
    profile = {"compiler":compiler,"optimization_flags":flags,"source_root":str(copied_source) if copied_source else "",
               "source_binary_correspondence":"用户提供，未证明源码与动态库对应" if copied_source else "源码未提供",
               "provenance":"用户提供；编译信息未经独立验证","library_sha256":{l:digest(p) for l,p in paths.items()}}
    (directory/"build_profile.json").write_text(json.dumps(profile,ensure_ascii=False,indent=2))
    result["correctness"] = validate_basic(target_id,levels,20)
    result["success"] = result["correctness"]["success"]
    return result

def environment(cpu):
    allowed = sorted(os.sched_getaffinity(0))
    if int(cpu) not in allowed: raise ValueError(f"CPU不可用，可用核心：{allowed}")
    directory = new_run("environment")
    # Pin only this worker, never the desktop process. Restore afterwards.
    previous = os.sched_getaffinity(0)
    try:
        os.sched_setaffinity(0,{int(cpu)})
        result = assess_environment(int(cpu))
        result["affinity"]["available_cpus"] = allowed
        result["affinity"]["pin_verified"] = os.sched_getaffinity(0) == {int(cpu)}
        native = directory/"native_probe.csv"
        subprocess.run([str(RUNNER),"--probe",str(native)],check=True,timeout=30)
    finally: os.sched_setaffinity(0,previous)
    with native.open() as f: rows = list(csv.DictReader(f))
    work = [int(r["work_ns"]) for r in rows]
    empty = [int(r["empty_ns"]) for r in rows]
    med = statistics.median(work)
    result["native_probe"] = {"count":len(rows),"median_ns":med,"p95_ns":percentile(work,.95),
        "p95_over_median":percentile(work,.95)/med,"max_over_median":max(work)/med,
        "clock_overhead_median_ns":statistics.median(empty),"cpu_migrations":sum(int(r["cpu"])!=int(cpu) for r in rows),
        "raw_csv":str(native),"method":"C固定工作量1000次，预热100次，CLOCK_MONOTONIC_RAW"}
    native_ok = result["native_probe"]["p95_over_median"] < 1.5 and result["native_probe"]["max_over_median"] < 3.5 and result["native_probe"]["cpu_migrations"] == 0
    check = {"name":"固定核心 C 探针", "ok":native_ok,"severity":"warning","detail":f"1000次；p95/median={result['native_probe']['p95_over_median']:.3f}；核心迁移={result['native_probe']['cpu_migrations']}"}
    result["checks"].append(check)
    if not native_ok:
        result["warnings"].append(check)
        if result["grade"] != "red": result["grade"] = "yellow"
        result["formal_timing_ready"] = False
    freq_dir = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
    result["selected_cpu_frequency"] = {n:(freq_dir/n).read_text().strip() if (freq_dir/n).is_file() else "unavailable" for n in ["scaling_governor","scaling_cur_freq","scaling_min_freq","scaling_max_freq"]}
    result["cpu"] = int(cpu)
    result["load_average"] = list(os.getloadavg())
    result["kind"] = "environment"
    result["conclusion"] = "当前预检通过；还需结合前后检查和重复实验" if result["formal_timing_ready"] else "当前环境只建议流程演示或探索测量"
    result["limits"] = "阈值是工程准入策略，不能证明环境没有噪声；虚拟化本身不代表功能不可用。"
    return save(directory,result)

def make_samples(target_id,level,count):
    result = generate_samples(target_id,level,count)
    result["csv_sha256"] = digest(result["csv"])
    result["kind"] = "samples"
    Path(result["report_json"]).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result

def load_samples(report_path,level):
    path = Path(report_path).resolve(strict=True)
    # A selected metadata file cannot redirect sample access outside the local sample store.
    store = (ROOT/"results/samples").resolve()
    if store not in path.parents: raise ValueError("请选择本软件生成的样本清单")
    report = json.loads(path.read_text())
    if report["level"] != "ML-KEM-"+level: raise ValueError("样本参数集与检测参数集不一致")
    csv_path = Path(report["csv"]).resolve(strict=True)
    if store not in csv_path.parents or digest(csv_path) != report["csv_sha256"]: raise ValueError("样本文件位置或摘要不匹配")
    with csv_path.open() as f: rows = list(csv.DictReader(f))
    if not 1<=len(rows)<=4096: raise ValueError("样本数量超出范围")
    return report,rows

def measure(target_id,level,sample_report,pairs,cpu,seed=42,category=2,control=False):
    if not 100<=int(pairs)<=100000 or int(category) not in (1,2,3): raise ValueError("计时参数不合法")
    if cpu not in os.sched_getaffinity(0): raise ValueError("所选CPU不可用")
    target = get_target(target_id)
    library = target.library_for(level)
    manifest,rows = load_samples(sample_report,level)
    directory = new_run("timing")
    private = directory/"inputs.bin"
    params = PARAMETERS[level]
    fd=os.open(private,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(struct.pack("<I",len(rows)))
            for row in rows:
                for key,length in [("secret_key_b64",params.secret_key)] + [(k,params.ciphertext) for k in CLASSES]:
                    selected = "normal_b64" if control and key in CLASSES else key
                    raw=base64.b64decode(row[selected],validate=True)
                    if len(raw)!=length: raise ValueError("样本字段长度错误")
                    out.write(raw)
        csv_path=directory/"timing.csv"
        command=["taskset","-c",str(cpu),str(RUNNER),str(library),level,str(private),str(pairs),str(seed),str(csv_path),str(category)]
        subprocess.run(command,check=True,capture_output=True,timeout=600)
    finally:
        private.unlink(missing_ok=True)
    stats=analyze_file(csv_path)
    analysis=analyze_csv(csv_path)
    with csv_path.open() as f: migrations=sum(int(r["cpu"])!=cpu for r in csv.DictReader(f))
    profile=ROOT/"targets"/target_id/"build_profile.json"
    result={"kind":"timing","target_id":target_id,"level":level,"pairs":pairs,"cpu":cpu,
        "seed":seed,"category":CLASSES[category],"control":control,"samples_per_class":len(rows),"sample_sha256":manifest["csv_sha256"],
        "sample_manifest":str(Path(sample_report).resolve()),"sample_rule":manifest["rule"],
        "library_sha256":digest(library),"runner_sha256":digest(RUNNER),"raw_csv":str(csv_path),
        "build_profile":json.loads(profile.read_text()) if profile.exists() else {"compiler":"unknown","optimization_flags":"unknown"},
        "analysis":analysis,"statistics":stats,"cpu_migrations":migrations,
        "measurement":"C CLOCK_MONOTONIC_RAW，仅包围mlkem_dec；输入先复制到同一64字节对齐缓冲区（复制不计时），预热2000对，随机先后顺序；原始异常值全保留",
        "threat_model":"本地测试进程可选择等长输入并观测函数耗时；实验材料专门生成。不代表远程网络条件。",
        "interpretation":("A/A同输入对照（在不同缓冲区复用同一输入）；" if control else "")+stats["verdict"]["text"]}
    save(directory,result)
    if not control: result["chart_png"]=plot_timing(result,directory)
    return save(directory,result)

def plot_timing(result,directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with Path(result["raw_csv"]).open() as f: rows=list(csv.DictReader(f))
    a=[int(r["valid_ns"]) for r in rows]; b=[int(r["changed_ns"]) for r in rows]
    fig,axes=plt.subplots(1,2,figsize=(10,3.5),layout="constrained")
    for values,label,color in [(a,"Normal","#2864ac"),(b,"Modified","#cf6b32")]:
        v=sorted(values); axes[0].plot(v,[(i+1)/len(v) for i in range(len(v))],label=label,color=color)
    axes[0].set(xlabel="Decapsulation time (ns)",ylabel="Empirical CDF",title="All observations (log time axis)")
    axes[0].set_xscale("log"); axes[0].legend()
    p=result["statistics"]["paired"]; mean=p["paired_mean_difference_ns"]; lo,hi=p["paired_difference_ci_ns"]
    axes[1].errorbar([0],[mean],yerr=[[mean-lo],[hi-mean]],fmt="o",capsize=8,color="#2864ac")
    axes[1].axhline(0,color="#888",linestyle="--"); axes[1].set(xticks=[0],xticklabels=["Modified - normal"],ylabel="Paired difference (ns)",title="95% Student-t confidence interval")
    fig.suptitle(f"{result['target_id']} / ML-KEM-{result['level']} / {result['pairs']} pairs",fontsize=11)
    output=directory/"timing.png"; fig.savefig(output,dpi=160); plt.close(fig); return str(output)

def detect(target_id,level,sample_report,pairs,cpu,repeats=3,category=2):
    if not 1<=int(repeats)<=10: raise ValueError("重复轮数范围1–10")
    pre=environment(cpu)
    if pre["grade"]=="red": raise ValueError("环境基础条件不满足，先查看环境自检报告")
    correctness=validate_basic(target_id,[level],20)
    if not correctness["success"]: return {"success":False,"correctness":correctness,"reason":"功能验证未通过，未启动计时"}
    controls=[]; runs=[]
    for i in range(repeats):
        controls.append(measure(target_id,level,sample_report,pairs,cpu,42+i,category,True))
        runs.append(measure(target_id,level,sample_report,pairs,cpu,42+i,category))
    post=environment(cpu)
    significant=[r["statistics"]["verdict"]["statistically_significant"] for r in runs]
    diffs=[r["analysis"]["paired_mean_difference_ns"] for r in runs]
    consistent=all(d>0 for d in diffs) or all(d<0 for d in diffs)
    control_ready=all(not r["statistics"]["verdict"]["statistically_significant"] and r["statistics"]["verdict"]["tests_agree"] for r in controls)
    formal=pre["formal_timing_ready"] and post["formal_timing_ready"] and control_ready and all(r["cpu_migrations"]==0 for r in runs+controls)
    agreed=all(r["statistics"]["verdict"]["tests_agree"] for r in runs)
    verdict="重复观察到同方向差异" if repeats>=3 and all(significant) and consistent else ("本次各轮未检出显著差异" if not any(significant) and agreed else "轮次结果不一致或轮数不足，需要进一步复测")
    return save(new_run("detection"),{"kind":"detection","success":True,"target_id":target_id,"level":level,
        "environment_before":pre,"environment_after":post,"formal_environment":formal,"correctness":correctness,
        "runs":runs,"controls":controls,"same_input_control_passed":control_ready,"conclusion":verdict,
        "scope":"环境或同输入对照未通过，结果仅作探索；不能直接归因于被测实现" if not formal else "仅对本环境、样本类别与次数成立；未检出不等于常数时间证明"})

def locate(target_id,level):
    from code_audit import locate_code
    from binary_audit import binary_locate
    return save(new_run("location"),{"kind":"location","target_id":target_id,"level":level,
        "source":locate_code(target_id),"binary":binary_locate(target_id,level),
        "scope":"二进制结果是候选指令；条件跳转数量不能直接证明敏感依赖。自动源码规则仅覆盖已适配的比较函数。"})

def repair(target_id,level,sample_report,pairs,cpu,repeats=3,category=2):
    from repair_manager import generate_repair
    location=locate(target_id,level)
    if get_target(target_id).role == "custom":
        return save(new_run("repair"),{"kind":"repair","success":False,"target_id":target_id,"location":location,
            "conclusion":"外部源码可辅助定位，但源码与动态库的构建对应尚未验证；需人工完成构建适配后才能自动应用补丁"})
    if location["source"]["compare_style"]!="early_return":
        return save(new_run("repair"),{"kind":"repair","success":False,"target_id":target_id,"location":location,
            "conclusion":"未识别受支持的修复模式，未改动源码；请人工适配"})
    before=detect(target_id,level,sample_report,pairs,cpu,repeats,category)
    if not before["success"]: return before
    repaired_id="repair_"+uuid.uuid4().hex[:12]
    patch=generate_repair(target_id,repaired_id,overwrite=False,build=True,validate_pairs=0,cpu=cpu)
    if not patch["success"]:
        return save(new_run("repair"),{"kind":"repair","success":False,"target_id":target_id,"patch":patch,"conclusion":"编译或功能验证失败，未接受补丁"})
    after=detect(repaired_id,level,sample_report,pairs,cpu,repeats,category)
    b=statistics.fmean(abs(r["analysis"]["paired_mean_difference_ns"]) for r in before["runs"])
    a=statistics.fmean(abs(r["analysis"]["paired_mean_difference_ns"]) for r in after["runs"])
    perf=[]
    for i,(br,ar) in enumerate(zip(before["runs"],after["runs"])):
        for cls in ("valid","changed"):
            bs,ass=br["analysis"][cls],ar["analysis"][cls]
            perf.append({"round":i+1,"class":cls,"before_mean_ns":bs["mean_ns"],"after_mean_ns":ass["mean_ns"],
                "before_p50_ns":bs["p50_ns"],"after_p50_ns":ass["p50_ns"],"before_p95_ns":bs["p95_ns"],"after_p95_ns":ass["p95_ns"],
                "overhead_percent":100*(ass["mean_ns"]/bs["mean_ns"]-1)})
    confirmed=before["conclusion"]=="重复观察到同方向差异" and after["conclusion"]=="本次各轮未检出显著差异" and a<b and before["formal_environment"] and after["formal_environment"]
    result={"kind":"repair","success":True,"target_id":target_id,"repaired_id":repaired_id,"level":level,"location":location,
        "patch":patch,"before":before,"after":after,"performance":perf,"effect_confirmed":confirmed,
        "mean_abs_diff_before_ns":b,"mean_abs_diff_after_ns":a,
        "conclusion":"本轮闭环实验支持防护改善" if confirmed else "补丁通过功能验证；计时改善尚未达到本轮验收条件，应检查重复结果与环境",
        "limits":"仅自动处理已适配的早退比较模式；不同源码结构须人工适配。"}
    return save(new_run("repair"),result)

def export_report(report_path):
    p=Path(report_path).resolve(strict=True)
    if RESULTS.resolve() not in p.parents: raise ValueError("请选择本软件生成的报告")
    data=json.loads(p.read_text())
    directory=new_run("export")
    artifacts=set()
    def visit(value):
        if isinstance(value,dict):
            for key,v in value.items():
                if key in {"report_json","raw_csv","chart_png","patch_file","sample_manifest"} and isinstance(v,str):
                    path=Path(v).resolve()
                    if path.is_file() and ROOT.resolve() in path.parents and (RESULTS.resolve() in path.parents or (key=="patch_file" and (ROOT/"targets").resolve() in path.parents) or (key=="sample_manifest" and path.suffix==".json" and (ROOT/"results/samples").resolve() in path.parents)):
                        artifacts.add(path)
                visit(v)
        elif isinstance(value,list):
            for v in value: visit(v)
    visit(data); artifacts.add(p)
    for relative in ["experiments/software_measure.c","backend/stats.py","backend/sample_generator.py","backend/software_service.py","docs/SOFTWARE.md"]:
        artifact=ROOT/relative
        if artifact.is_file(): artifacts.add(artifact)
    text="# ML-KEM 软件实验报告\n\n"+f"目标：{data.get('target_id','环境')}\n\n类型：{data.get('kind')}\n\n结论：{data.get('conclusion','见逐项验证明细')}\n\n"
    text+="报告仅包含实验结论、统计结果和源码补丁，不导出样本中的专用秘密材料。未检出差异不能证明绝对常数时间。\n\n"
    text+="```json\n"+json.dumps(data,ensure_ascii=False,indent=2)+"\n```\n"
    (directory/"report.md").write_text(text,encoding="utf-8")
    manifest=[]
    with zipfile.ZipFile(directory/"evidence.zip","w",zipfile.ZIP_DEFLATED) as z:
        z.write(directory/"report.md","report.md")
        for path in sorted(artifacts):
            arc=str(path.relative_to(ROOT)); z.write(path,arc); manifest.append({"file":arc,"sha256":digest(path)})
        z.writestr("manifest.json",json.dumps(manifest,indent=2))
    return {"kind":"export","success":True,"markdown":str(directory/"report.md"),"zip":str(directory/"evidence.zip"),"files":len(manifest)}

def dispatch(request):
    action=request["action"]; args=request.get("args",{})
    functions={"basic":validate_basic,"import":import_target,"environment":environment,"samples":make_samples,
               "detect":detect,"locate":locate,"repair":repair,"export":export_report}
    if action not in functions: raise ValueError("未知操作")
    if action in {"environment","detect","repair"}:
        import fcntl
        RESULTS.mkdir(parents=True,exist_ok=True)
        with (RESULTS/"measurement.lock").open("a") as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError("另一个软件任务正在测量，请等待它完成")
            return functions[action](**args)
    return functions[action](**args)

if __name__=="__main__":
    try:
        request=json.load(sys.stdin)
        result=dispatch(request)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        # No request, input values, internal outputs or traceback in ordinary logs.
        print(json.dumps({"error":type(exc).__name__,"message":str(exc) if isinstance(exc,(ValueError,FileNotFoundError)) else "操作失败，请检查库接口、文件和运行环境"},ensure_ascii=False))
        sys.exit(1)
