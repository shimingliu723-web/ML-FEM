const state = { level: "768", targetId: "mlkem_native_baseline", targets: [], environment: null };
const sizes = { "512": { pk: 800, sk: 1632, ct: 768 }, "768": { pk: 1184, sk: 2400, ct: 1088 }, "1024": { pk: 1568, sk: 3168, ct: 1568 } };
const $ = id => document.getElementById(id);

function toast(message) { const el = $("toast"); el.textContent = message; el.classList.add("show"); clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("show"), 2800); }
function ns(value) { if (value === undefined || value === null) return "尚未运行"; return `${Number(value).toLocaleString()} ns · ${(Number(value) / 1000).toFixed(2)} μs`; }
function seconds(value) { return `${Number(value).toFixed(2)} s`; }
function secondsFromNs(value) { return `${(Number(value) / 1e9).toFixed(2)} s`; }
function fmt(value, digits = 2) { if (value === undefined || value === null || Number.isNaN(Number(value))) return "-"; return Number(value).toFixed(digits); }
function htmlLines(lines) { return (lines || []).map(line => `<code>${String(line).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}</code>`).join(""); }
function log(operation, detail, elapsed) { const area = $("activityLog"); if (!area) return; if (area.querySelector(".empty")) area.innerHTML = ""; const row = document.createElement("div"); row.className = "log-row"; row.innerHTML = `<span>${new Date().toLocaleTimeString()}</span><b>${operation}</b><span>${detail}${elapsed ? ` · ${ns(elapsed)}` : ""}</span>`; area.prepend(row); }
async function api(path, payload = {}) { const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ level: state.level, target_id: state.targetId, ...payload }) }); const data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || "请求失败"); return data.result; }
async function getJson(path) { const response = await fetch(path, { headers: { "Cache-Control": "no-store" }}); const data = await response.json(); if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败"); return data; }
async function busy(button, task) { const old = button.textContent; button.disabled = true; button.textContent = "正在执行…"; try { await task(); } catch (error) { toast(error.message); log("操作失败", error.message); } finally { button.disabled = false; button.textContent = old; } }

function showPage(name) { document.querySelectorAll(".page").forEach(p => p.classList.toggle("active", p.id === `page-${name}`)); document.querySelectorAll(".nav").forEach(b => b.classList.toggle("active", b.dataset.page === name)); }
document.querySelectorAll(".nav").forEach(button => button.addEventListener("click", () => showPage(button.dataset.page)));
document.querySelectorAll(".entry-card").forEach(button => button.addEventListener("click", () => showPage(button.dataset.jump)));
$("openCryptoFlow").addEventListener("click", () => { showPage("crypto"); $("demoButton").click(); });

function updateLevel(level) { state.level = level; $("sideLevel").textContent = `ML-KEM-${level}`; document.querySelectorAll("[data-level]").forEach(button => button.classList.toggle("active", button.dataset.level === level)); $("pkSize").textContent = `${sizes[level].pk} B`; $("skSize").textContent = `${sizes[level].sk} B`; $("ctSize").textContent = `${sizes[level].ct} B`; ["publicKey","secretKey","ciphertext","encapsSecret","decapsSecret"].forEach(id => $(id).value = ""); $("matchResult").className = "result neutral"; $("matchResult").textContent = "等待结果"; updateTargetDetail(); log("切换参数集", `ML-KEM-${level}`); }
document.querySelectorAll("[data-level]").forEach(button => button.addEventListener("click", () => updateLevel(button.dataset.level)));

async function loadTargets() { const data = await getJson("/api/targets"); state.targets = data.targets || []; const select = $("targetSelect"); select.innerHTML = state.targets.map(t => `<option value="${t.id}">${t.name}</option>`).join(""); if (state.targets.some(t => t.id === state.targetId)) select.value = state.targetId; else if (state.targets.length) state.targetId = state.targets[0].id; select.value = state.targetId; renderTargetList(); updateTargetDetail(); }
function renderTargetList() { $("targetList").innerHTML = state.targets.map(t => { const readyCount = Object.values(t.libraries || {}).filter(Boolean).length; return `<article class="target-item"><b>${t.name}</b><span>${t.role}</span><p>${t.description}</p><em>${readyCount}/${t.levels.length} 参数库就绪</em></article>`; }).join(""); }
function updateTargetDetail() { const target = state.targets.find(t => t.id === state.targetId); if (!target) return; const ready = target.libraries && target.libraries[state.level]; $("sideTarget").textContent = target.name; $("targetDetail").innerHTML = `<b>${target.name}</b><br>目标ID：${target.id}<br>类型：${target.role}<br>配置：${target.config}<br>当前参数库：${ready ? "已就绪" : "未就绪"}<br><br>${target.description}`; $("targetReady").className = `result ${ready ? "success" : "failure"}`; $("targetReady").textContent = ready ? "当前目标可测试" : "当前目标缺少库文件"; }
$("targetSelect").addEventListener("change", event => { state.targetId = event.target.value; updateTargetDetail(); log("切换目标实现", state.targetId); });
$("targetBuildButton").addEventListener("click", event => busy(event.currentTarget, async () => { const result = await api("/api/target-build"); await loadTargets(); $("targetCommandResult").innerHTML = `<b>${result.success ? "构建完成" : "构建失败"}</b><br>命令：${(result.command || []).join(" ")}<br>返回码：${result.returncode ?? "-"}<div class="code-lines">${htmlLines((result.output_tail || []).slice(-12))}</div>`; log("目标构建", `${state.targetId} · ${result.success ? "成功" : "失败"}`); }));
$("targetSelftestButton").addEventListener("click", event => busy(event.currentTarget, async () => { const result = await api("/api/target-selftest"); $("targetCommandResult").innerHTML = `<b>${result.success ? "自测完成" : "自测失败"}</b><br>命令：${(result.command || []).join(" ")}<br>返回码：${result.returncode ?? "-"}<div class="code-lines">${htmlLines((result.output_tail || []).slice(-12))}</div>`; log("目标自测", `${state.targetId} · ${result.success ? "成功" : "失败"}`); }));


$("registerTargetButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/register-target", {
    id: $("customTargetId").value.trim(),
    name: $("customTargetName").value.trim(),
    role: "custom",
    description: "用户在服务器本地注册的 ML-KEM 实现，用于工程接入检测。",
    levels: ["512", "768", "1024"],
    library_template: $("customLibTemplate").value.trim(),
    build_command: $("customBuildCommand").value.trim(),
    selftest_command: $("customSelftestCommand").value.trim()
  });
  await loadTargets();
  state.targetId = result.target;
  $("targetSelect").value = result.target;
  updateTargetDetail();
  $("registerTargetResult").innerHTML = `<b>注册完成</b><br>目标：${result.target}<br>配置：${result.config}<br>库文件状态：${Object.entries(result.libraries).map(([k,v]) => `ML-KEM-${k} ${v ? "已找到" : "未找到"}`).join("，")}`;
  log("注册本地实现", result.target);
}));

$("fillVectorExample").addEventListener("click", () => {
  const ct = $("ciphertext").value.trim();
  const sk = $("secretKey").value.trim();
  const ss = $("encapsSecret").value.trim();
  if (!ct || !sk || !ss) {
    toast("请先在基本功能页运行完整流程，生成 ct/sk/ss 样例");
    return;
  }
  $("customVectorInput").value = JSON.stringify([{ level: state.level, ct, sk, ss }], null, 2);
  log("填入向量样例", `ML-KEM-${state.level}`);
});

$("validateVectorButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/vector-validate", { vectors: $("customVectorInput").value });
  const rows = result.results.map(row => `<tr><td>${row.index}</td><td>${row.level}</td><td>${row.length_ok ? "是" : "否"}</td><td>${row.passed ? "通过" : "失败"}</td><td>${row.reason}</td><td>${row.actual_shared_secret_sha256_16 || "-"}</td></tr>`).join("");
  $("customVectorResult").innerHTML = `<b>${result.success ? "批量验证通过" : "存在失败项"}</b><br>目标：${result.target_name}<br>总数：${result.total}，通过：${result.passed}，失败：${result.failed}<br>格式：${result.accepted_format}<table class="matrix"><thead><tr><th>#</th><th>参数</th><th>长度正确</th><th>结果</th><th>说明</th><th>实际共享结果摘要</th></tr></thead><tbody>${rows}</tbody></table>`;
  log("自定义向量验证", `${result.passed}/${result.total}`);
}));

$("keygenButton").addEventListener("click", event => busy(event.currentTarget, async () => { const result = await api("/api/keygen"); $("publicKey").value = result.public_key; $("secretKey").value = result.secret_key; $("keygenTime").textContent = ns(result.elapsed_ns); log("密钥生成", result.level, result.elapsed_ns); }));
$("encapsButton").addEventListener("click", event => busy(event.currentTarget, async () => { const result = await api("/api/encaps", { public_key: $("publicKey").value.trim() }); $("ciphertext").value = result.ciphertext; $("encapsSecret").value = result.shared_secret; $("encapsTime").textContent = ns(result.elapsed_ns); log("封装", result.level, result.elapsed_ns); }));
$("decapsButton").addEventListener("click", event => busy(event.currentTarget, async () => { const result = await api("/api/decaps", { ciphertext: $("ciphertext").value.trim(), secret_key: $("secretKey").value.trim() }); $("decapsSecret").value = result.shared_secret; $("decapsTime").textContent = ns(result.elapsed_ns); const matched = result.shared_secret === $("encapsSecret").value.trim(); $("matchResult").className = `result ${matched ? "success" : "failure"}`; $("matchResult").textContent = matched ? "共享结果一致，流程正确" : "共享结果不一致"; log("解封装", matched ? "结果一致" : "结果不一致", result.elapsed_ns); }));
$("demoButton").addEventListener("click", event => busy(event.currentTarget, async () => { const result = await api("/api/demo"); $("publicKey").value = result.public_key; $("secretKey").value = result.secret_key; $("ciphertext").value = result.ciphertext; $("encapsSecret").value = result.encapsulated_secret; $("decapsSecret").value = result.decapsulated_secret; $("keygenTime").textContent = ns(result.timings_ns.keygen); $("encapsTime").textContent = ns(result.timings_ns.encaps); $("decapsTime").textContent = ns(result.timings_ns.decaps); $("matchResult").className = `result ${result.matched ? "success" : "failure"}`; $("matchResult").textContent = result.matched ? "共享结果一致，完整流程通过" : "完整流程失败"; log("完整流程", result.matched ? `${result.level} · 通过` : "失败"); }));
$("selftestButton").addEventListener("click", event => busy(event.currentTarget, async () => { const iterations = Number($("iterations").value); const result = await api("/api/selftest", { iterations }); $("selftestResult").innerHTML = `<b>${result.success ? "连续测试全部通过" : "存在失败"}</b><br>成功次数：${result.passed}/${result.iterations}<br>总耗时：${ns(result.total_elapsed_ns)}<br>平均耗时：KeyGen ${ns(result.average_ns.keygen)}，Encaps ${ns(result.average_ns.encaps)}，Decaps ${ns(result.average_ns.decaps)}`; log("连续正确性测试", `${result.passed}/${result.iterations} 次通过`); }));
$("vectorButton").addEventListener("click", event => busy(event.currentTarget, async () => { const result = await api("/api/vector-test"); const items = Object.entries(result.vectors.available_items || {}).map(([k,v]) => `${k}: ${v}B`).join("，"); $("vectorResult").innerHTML = `<b>${result.success ? "公开向量验证通过" : "公开向量验证失败"}</b><br>检查项：${result.checks_passed}/${result.checks_total}<br>覆盖参数：${result.levels.join(" / ")}<br>向量来源：${result.vectors.source}<br>向量字段：${items}<br>耗时：${secondsFromNs(result.elapsed_ns)}<div class="code-lines">${htmlLines(result.output_tail)}</div>`; log("公开向量验证", `${result.checks_passed}/${result.checks_total} 项通过`); }));

$("sampleButton").addEventListener("click", event => busy(event.currentTarget, async () => { const count = Number($("sampleCount").value); const result = await api("/api/generate-samples", { count }); $("sampleResult").innerHTML = `<b>样本生成完成</b><br>目标：${result.target_name}<br>参数：${result.level}<br>样本类别：${result.sample_classes.join(" / ")}<br>每类长度：${result.ciphertext_bytes} B<br>生成规则：${result.rule}<br>CSV：${result.csv}<br>JSON：${result.report_json}`; $("evSamples").textContent = `最近一次生成 ${result.count} 组样本，JSON：${result.report_json}`; log("生成测试样本", `${result.target_id} · ${result.count} 组`); }));

$("formalTimingButton").addEventListener("click", event => busy(event.currentTarget, async () => { const cpu = Number($("formalCpu").value); const pairs = Number($("formalPairs").value); const result = await api("/api/formal-timing", { cpu, pairs }); const a = result.analysis; $("formalStatus").className = `result ${a.statistically_distinguishable ? "failure" : "success"}`; $("formalStatus").textContent = a.statistically_distinguishable ? "观察到稳定可区分差异" : "未观察到稳定可区分差异"; $("formalValidMean").textContent = fmt(a.valid.mean_ns); $("formalChangedMean").textContent = fmt(a.changed.mean_ns); $("formalDiff").textContent = fmt(a.paired_mean_difference_ns); $("formalElapsed").textContent = seconds(result.elapsed_seconds); $("formalDetail").innerHTML = `目标：${result.target_name}<br>参数：${result.level}<br>配对次数：${result.pairs.toLocaleString()}，固定 CPU：${result.cpu}<br>测量方式：${result.measurement}<br>异常样本处理：${result.outlier_policy}<br>正常样本：mean ${fmt(a.valid.mean_ns)} ns，std ${fmt(a.valid.stddev_ns)} ns，P50 ${fmt(a.valid.p50_ns)} ns，P95 ${fmt(a.valid.p95_ns)} ns<br>改动样本：mean ${fmt(a.changed.mean_ns)} ns，std ${fmt(a.changed.stddev_ns)} ns，P50 ${fmt(a.changed.p50_ns)} ns，P95 ${fmt(a.changed.p95_ns)} ns<br>配对均值差：${fmt(a.paired_mean_difference_ns)} ns，95% CI：[${fmt(a.paired_difference_ci95_ns[0])}, ${fmt(a.paired_difference_ci95_ns[1])}] ns<br>统计结论：${a.statistically_distinguishable ? "存在可区分差异" : "未观察到稳定可区分差异"}<br>原始 CSV：${result.raw_csv}<br>报告 JSON：${result.report_json}<br>${a.method}`; $("evStats").textContent = `最近一次 ${result.target_name} ${result.level}，配对 ${result.pairs} 次，报告：${result.report_json}`; log("正式计时检测", `${result.target_id} · ${result.level}`); }));


function renderSnippet(text) {
  return `<pre class="snippet"><code>${String(text || "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}</code></pre>`;
}

$("locateButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/code-locate");
  $("locateSummary").innerHTML = `<b>${result.target_name}</b><br>目标角色：${result.role}<br>源码根目录：${result.source_root}<br>比较风格：${result.compare_style}<br>${result.summary}`;
  $("locateFindings").innerHTML = result.findings.map(item => `<article class="finding"><h3>${item.title}</h3><p>${item.requirement}</p><b>${item.found ? "已定位" : "未找到"}：${item.path}</b><br>匹配行：${(item.matches || []).join(", ") || "-"}${renderSnippet(item.snippet)}</article>`).join("");
  $("evLocate").textContent = `最近定位目标：${result.target_name}，比较风格：${result.compare_style}`;
  log("代码定位", result.target_id);
}));

$("diffButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/fix-diff", { before_id: "variant_early_return", after_id: "variant_fixed" });
  $("diffResult").innerHTML = `<b>对照/改进源码差异</b><br>${result.explanation}<br>对照文件：${result.before_file}<br>改进文件：${result.after_file}${renderSnippet((result.diff_lines || []).join("\n"))}`;
  $("evLocate").textContent = `已生成源码差异：${result.before_id} -> ${result.after_id}`;
  log("源码差异", `${result.before_id} -> ${result.after_id}`);
}));

$("fixCompareButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const cpu = Number($("fixCpu").value);
  const pairs = Number($("fixPairs").value);
  const result = await api("/api/fix-compare", { cpu, pairs });
  const summary = result.summary;
  $("beforeDiff").textContent = fmt(summary.before_diff_ns);
  $("beforeDist").textContent = summary.before_distinguishable ? "是" : "否";
  $("afterDiff").textContent = fmt(summary.after_diff_ns);
  $("afterDist").textContent = summary.after_distinguishable ? "是" : "否";
  $("fixSummary").innerHTML = `<b>前后复测完成</b><br>参数：${result.level}，配对次数：${result.pairs}，CPU：${result.cpu}<br>对照版本：${result.before.target_name}<br>差值：${fmt(summary.before_diff_ns)} ns，95% CI：[${fmt(result.before.analysis.paired_difference_ci95_ns[0])}, ${fmt(result.before.analysis.paired_difference_ci95_ns[1])}] ns，可区分：${summary.before_distinguishable ? "是" : "否"}<br>改进版本：${result.after.target_name}<br>差值：${fmt(summary.after_diff_ns)} ns，95% CI：[${fmt(result.after.analysis.paired_difference_ci95_ns[0])}, ${fmt(result.after.analysis.paired_difference_ci95_ns[1])}] ns，可区分：${summary.after_distinguishable ? "是" : "否"}<br>绝对差值降低：${fmt(summary.absolute_diff_reduction_ns)} ns<br>对照报告：${result.before.report_json}<br>改进报告：${result.after.report_json}`;
  $("evFix").textContent = `最近一次前后复测：${result.level}，对照差值 ${fmt(summary.before_diff_ns)} ns，改进差值 ${fmt(summary.after_diff_ns)} ns`;
  log("修复前后复测", `${result.level} · ${pairs} pairs`);
}));


$("perfButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const cpu = Number($("perfCpu").value);
  const pairs = Number($("perfPairs").value);
  const result = await api("/api/performance-compare", { cpu, pairs });
  const p = result.performance;
  $("perfBeforeMean").textContent = fmt(p.before_mean_ns);
  $("perfAfterMean").textContent = fmt(p.after_mean_ns);
  $("perfOverhead").textContent = fmt(p.overhead_ns);
  $("perfPercent").textContent = `${fmt(p.overhead_percent)}%`;
  $("perfResult").innerHTML = `<b>性能对比完成</b><br>参数：${result.level}，配对次数：${result.pairs}，CPU：${result.cpu}<br>对照版本：mean ${fmt(p.before_mean_ns)} ns，P50 ${fmt(p.before_p50_ns)} ns，P95 ${fmt(p.before_p95_ns)} ns<br>改进版本：mean ${fmt(p.after_mean_ns)} ns，P50 ${fmt(p.after_p50_ns)} ns，P95 ${fmt(p.after_p95_ns)} ns<br>开销：${fmt(p.overhead_ns)} ns，${fmt(p.overhead_percent)}%<br>${p.interpretation}<br>对照报告：${result.before.report_json}<br>改进报告：${result.after.report_json}`;
  $("evPerf").textContent = `最近一次性能评估：开销 ${fmt(p.overhead_ns)} ns，${fmt(p.overhead_percent)}%`;
  log("性能评估", `${result.level} · ${pairs} pairs`);
}));

function renderReportPreview(report) {
  const threat = report.threat_model || {};
  $("threatBox").innerHTML = Object.entries(threat).map(([k,v]) => `<b>${k}</b><br>${v}`).join("<br><br>");
  $("reproBox").innerHTML = (report.repro_steps || []).map((x,i) => `${i + 1}. <code>${x}</code>`).join("<br>");
  $("matrixBox").innerHTML = `<table class="matrix"><thead><tr><th>要求</th><th>状态</th><th>平台证据</th></tr></thead><tbody>${(report.requirements || []).map(r => `<tr><td>${r.requirement}</td><td>${r.status}</td><td>${r.evidence}</td></tr>`).join("")}</tbody></table>`;
}

async function loadReportPreview() {
  const data = await getJson("/api/report-preview");
  renderReportPreview(data.report);
}

$("reportButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/report-generate", {});
  renderReportPreview(result.payload);
  $("reportResult").innerHTML = `<b>报告已生成</b><br>Markdown：${result.markdown}<br>JSON：${result.json}<br>最近样本：${result.payload.latest_files.latest_sample_json}<br>最近计时：${result.payload.latest_files.latest_timing_json}`;
  $("evReport").textContent = `已生成报告：${result.markdown}`;
  log("生成报告", result.markdown);
}));

async function loadEnvironment() { const data = await getJson("/api/environment"); state.environment = data.environment; const e = state.environment; $("evEnv").textContent = `${e.platform}；${e.compiler}；优化参数 ${e.optimization}`; $("environmentBox").innerHTML = `<b>测量环境</b><br>系统：${e.platform}<br>处理器：${e.processor}<br>编译器：${e.compiler}<br>优化级别：${e.optimization}<br>CPU 频率策略：${e.cpu_governor_cpu0}<br>可用 CPU 核：${e.cpu_affinity.join(", ")}<br>计时方式：${e.clock}<br>预热策略：${e.warmup}<br>异常样本处理：${e.outlier_policy}<br>结果目录：${e.results_dir}<div class="code-lines">${htmlLines(e.lscpu_head)}</div>`; }
$("refreshEvidence").addEventListener("click", () => loadEnvironment().catch(error => toast(error.message)));
$("clearLog").addEventListener("click", () => { $("activityLog").innerHTML = '<div class="empty">等待执行操作</div>'; });

Promise.all([loadTargets(), loadEnvironment(), loadReportPreview()]).catch(error => toast(error.message));
