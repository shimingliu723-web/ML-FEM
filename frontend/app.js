const state = { level: "768" };
const sizes = {
  "512": { pk: 800, sk: 1632, ct: 768 },
  "768": { pk: 1184, sk: 2400, ct: 1088 },
  "1024": { pk: 1568, sk: 3168, ct: 1568 }
};
const $ = id => document.getElementById(id);

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 2800);
}

function ns(value) {
  if (value === undefined) return "尚未运行";
  return `${value.toLocaleString()} ns · ${(value / 1000).toFixed(2)} μs`;
}

function log(operation, detail, elapsed) {
  const area = $("activityLog");
  if (area.querySelector(".empty")) area.innerHTML = "";
  const row = document.createElement("div");
  row.className = "log-row";
  row.innerHTML = `<span>${new Date().toLocaleTimeString()}</span><b>${operation}</b><span>${detail}${elapsed ? ` · ${ns(elapsed)}` : ""}</span>`;
  area.prepend(row);
}

async function api(path, payload) {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ level: state.level, ...payload }) });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || "请求失败");
  return data.result;
}

async function busy(button, task) {
  const old = button.textContent;
  button.disabled = true;
  button.textContent = "正在执行…";
  try { await task(); } catch (error) { toast(error.message); log("操作失败", error.message); }
  finally { button.disabled = false; button.textContent = old; }
}

function updateLevel(level) {
  state.level = level;
  document.querySelectorAll("[data-level]").forEach(button => button.classList.toggle("active", button.dataset.level === level));
  $("pkSize").textContent = `${sizes[level].pk} B`;
  $("skSize").textContent = `${sizes[level].sk} B`;
  $("ctSize").textContent = `${sizes[level].ct} B`;
  ["publicKey","secretKey","ciphertext","encapsSecret","decapsSecret"].forEach(id => $(id).value = "");
  $("matchResult").className = "result neutral";
  $("matchResult").textContent = "等待结果";
  log("切换参数集", `ML-KEM-${level}`);
}

document.querySelectorAll("[data-level]").forEach(button => button.addEventListener("click", () => updateLevel(button.dataset.level)));

$("keygenButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/keygen", {});
  $("publicKey").value = result.public_key;
  $("secretKey").value = result.secret_key;
  $("keygenTime").textContent = ns(result.elapsed_ns);
  log("密钥生成", result.level, result.elapsed_ns);
}));

$("encapsButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/encaps", { public_key: $("publicKey").value.trim() });
  $("ciphertext").value = result.ciphertext;
  $("encapsSecret").value = result.shared_secret;
  $("encapsTime").textContent = ns(result.elapsed_ns);
  log("密钥封装", result.level, result.elapsed_ns);
}));

$("decapsButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/decaps", { ciphertext: $("ciphertext").value.trim(), secret_key: $("secretKey").value.trim() });
  $("decapsSecret").value = result.shared_secret;
  $("decapsTime").textContent = ns(result.elapsed_ns);
  const matched = result.shared_secret === $("encapsSecret").value.trim();
  $("matchResult").className = `result ${matched ? "success" : "failure"}`;
  $("matchResult").textContent = matched ? "共享密钥一致 ✓" : "共享密钥不一致 ✕";
  log("密钥解封装", matched ? "结果一致" : "结果不一致", result.elapsed_ns);
}));

$("demoButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/demo", {});
  $("publicKey").value = result.public_key;
  $("secretKey").value = result.secret_key;
  $("ciphertext").value = result.ciphertext;
  $("encapsSecret").value = result.encapsulated_secret;
  $("decapsSecret").value = result.decapsulated_secret;
  $("keygenTime").textContent = ns(result.timings_ns.keygen);
  $("encapsTime").textContent = ns(result.timings_ns.encaps);
  $("decapsTime").textContent = ns(result.timings_ns.decaps);
  $("matchResult").className = `result ${result.matched ? "success" : "failure"}`;
  $("matchResult").textContent = result.matched ? "共享密钥一致 ✓" : "共享密钥不一致 ✕";
  log("完整流程", result.matched ? `${result.level} · 验证通过` : "验证失败");
}));

$("selftestButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const iterations = Number($("iterations").value);
  const result = await api("/api/selftest", { iterations });
  $("selftestResult").innerHTML = `<b>${result.success ? "全部通过" : "存在失败"}</b><br>${result.passed}/${result.iterations} 次成功<br>平均：生成 ${ns(result.average_ns.keygen)}，封装 ${ns(result.average_ns.encaps)}，解封装 ${ns(result.average_ns.decaps)}`;
  log("连续正确性测试", `${result.passed}/${result.iterations} 次通过`);
}));


function secondsFromNs(value) {
  return `${(value / 1e9).toFixed(2)} s`;
}

function renderMeansChart(values) {
  const chart = $("meansChart");
  if (!values || !values.length) {
    chart.innerHTML = "";
    return;
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  chart.innerHTML = values.map((value, index) => {
    const height = max === min ? 36 : 22 + ((value - min) / (max - min)) * 88;
    const label = index === 7 ? "ref0" : index === 8 ? "ref1" : `c${index}`;
    return `<div class="bar"><i style="height:${height}px"></i><span>${label}</span><em>${value.toFixed(1)}</em></div>`;
  }).join("");
}

$("vectorButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/vector-test", {});
  $("vectorResult").innerHTML = `<b>${result.success ? "测试通过" : "测试失败"}</b><br>${result.checks_passed}/${result.checks_total} 项通过<br>向量来源：${result.vectors.source.split("/").slice(-4).join("/")}<br>耗时：${secondsFromNs(result.elapsed_ns)}`;
  log("公开向量验证", `${result.checks_passed}/${result.checks_total} 项通过`);
}));

$("timingButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const cpu = Number($("timingCpu").value);
  const timeout_seconds = Number($("timingTimeout").value);
  const result = await api("/api/timing-detect", { cpu, timeout_seconds });
  $("timingDone").textContent = `${result.coefficients_done}`;
  $("timingAccuracy").textContent = `${result.accuracy.toFixed(1)}%`;
  $("timingElapsed").textContent = secondsFromNs(result.elapsed_ns);
  $("timingGap").textContent = result.reference_gap ? result.reference_gap.toFixed(2) : "-";
  $("timingDetail").innerHTML = `<b>${result.distinguishable ? "观察到明显时间差异" : "差异不明显"}</b><br>固定 CPU：${result.cpu}，退出码：${result.exit_status}<br>完成：${result.correct}/${result.coefficients_done}，准确率：${result.accuracy.toFixed(1)}%，平均迭代：${Math.round(result.iteration_summary.mean).toLocaleString()}<br>${result.detection_note}<br>日志：${result.log_file}`;
  renderMeansChart(result.last_means);
  log("高精度计时检测", `${result.correct}/${result.coefficients_done} · ${result.accuracy.toFixed(1)}%`);
}));

$("formalButton").addEventListener("click", event => busy(event.currentTarget, async () => {
  const result = await api("/api/formal-timing", {
    cpu: Number($("formalCpu").value),
    pairs: Number($("formalPairs").value)
  });
  const data = result.analysis;
  $("formalValid").textContent = ns(data.valid.mean_ns);
  $("formalChanged").textContent = ns(data.changed.mean_ns);
  $("formalDifference").textContent = ns(data.paired_mean_difference_ns);
  $("formalInterval").textContent = data.paired_difference_ci95_ns.map(v => v.toFixed(1)).join(" ~ ") + " ns";
  $("formalDetail").textContent =
    `${data.statistically_distinguishable ? "本次配对均值差的区间未跨越零" : "本次配对均值差的区间跨越零"}。
    每类 ${data.valid.count} 次；正常输入中位数 ${data.valid.p50_ns.toFixed(1)} ns、P95 ${data.valid.p95_ns.toFixed(1)} ns；
    单比特变化中位数 ${data.changed.p50_ns.toFixed(1)} ns、P95 ${data.changed.p95_ns.toFixed(1)} ns。
    原始数据：${result.raw_csv}；分析报告：${result.report_json}。结论限于本次环境和输入类别。`;
  log("正式计时实验", `${result.level} · ${result.pairs} 组`);
}));

$("clearLog").addEventListener("click", () => { $("activityLog").innerHTML = '<div class="empty">等待执行操作</div>'; });

