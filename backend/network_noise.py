"""Controlled TCP latency/jitter experiment for ML-KEM timing evidence.

The native runner performs a real ``mlkem_dec`` call for every request and
records two observation channels for the same paired input sequence:

* server-internal time around ``mlkem_dec`` only;
* client-observed TCP round-trip time (RTT).

Latency and jitter are inserted *after* decapsulation, independently of the
input class.  This makes the experiment a reproducible robustness test, not a
claim that loopback TCP is identical to an arbitrary Internet path.
"""

from __future__ import annotations

import csv
import statistics
import subprocess
from pathlib import Path

from stats import analyze_file, percentile


PROFILES = {
    "none": {"label": "无附加噪声", "base_us": 0, "jitter_us": 0},
    "low": {"label": "低噪声", "base_us": 50, "jitter_us": 25},
    "medium": {"label": "中噪声", "base_us": 250, "jitter_us": 125},
    "high": {"label": "高噪声", "base_us": 1000, "jitter_us": 500},
}


def selected_profiles(names: list[str] | None = None) -> list[dict]:
    requested = names or list(PROFILES)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("网络噪声档位不能为空或重复")
    unknown = [name for name in requested if name not in PROFILES]
    if unknown:
        raise ValueError("未知网络噪声档位：" + ", ".join(unknown))
    return [dict(PROFILES[name], id=name) for name in requested]


def analyze_network_csv(path: Path) -> dict:
    internal = analyze_file(
        path,
        a_column="valid_internal_ns",
        b_column="changed_internal_ns",
        order_column="order",
    )
    rtt = analyze_file(
        path,
        a_column="valid_rtt_ns",
        b_column="changed_rtt_ns",
        order_column="order",
    )
    delays: list[int] = []
    server_cpus: set[int] = set()
    client_cpus: set[int] = set()
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            delays.extend((int(row["valid_delay_us"]), int(row["changed_delay_us"])))
            server_cpus.add(int(row["server_cpu"]))
            client_cpus.add(int(row["client_cpu"]))
    return {
        "raw_csv": str(path),
        "pairs": internal["class_a"]["count"],
        "internal": internal,
        "rtt": rtt,
        "applied_delay_us": {
            "mean": statistics.fmean(delays),
            "p50": percentile(delays, 0.50),
            "p95": percentile(delays, 0.95),
            "minimum": min(delays),
            "maximum": max(delays),
        },
        "observed_server_cpus": sorted(server_cpus),
        "observed_client_cpus": sorted(client_cpus),
    }


def run_native(
    runner: Path,
    library: Path,
    level: str,
    private_samples: Path,
    pairs: int,
    seed: int,
    output: Path,
    category: int,
    control: bool,
    server_cpu: int,
    client_cpu: int,
    profile: dict,
    timeout: int = 900,
) -> dict:
    command = [
        str(runner), str(library), str(level), str(private_samples), str(pairs),
        str(seed), str(output), str(category), "1" if control else "0",
        str(server_cpu), str(client_cpu), str(profile["base_us"]),
        str(profile["jitter_us"]),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=timeout)
    result = analyze_network_csv(output)
    result.update({
        "profile": profile,
        "seed": int(seed),
        "control": bool(control),
        "server_cpu": int(server_cpu),
        "client_cpu": int(client_cpu),
    })
    return result


def _channel_row(analysis: dict) -> dict:
    paired = analysis["paired"]
    verdict = analysis["verdict"]
    return {
        "mean_difference_ns": paired["paired_mean_difference_ns"],
        "ci95_ns": paired["paired_difference_ci_ns"],
        "statistically_significant": verdict["statistically_significant"],
        "tests_agree": verdict["tests_agree"],
        "relative_difference_percent": analysis["relative_mean_difference_percent"],
    }


def summarize_profiles(profile_runs: list[dict]) -> list[dict]:
    rows = []
    for item in profile_runs:
        runs = item["runs"]
        controls = item["controls"]
        internal = [_channel_row(run["internal"]) for run in runs]
        rtt = [_channel_row(run["rtt"]) for run in runs]
        control_rtt = [_channel_row(run["rtt"]) for run in controls]
        internal_detected = sum(row["statistically_significant"] and row["tests_agree"] for row in internal)
        rtt_detected = sum(row["statistically_significant"] and row["tests_agree"] for row in rtt)
        systematic_control = (
            len(control_rtt) >= 3
            and all(row["statistically_significant"] and row["tests_agree"] for row in control_rtt)
            and len({1 if row["mean_difference_ns"] > 0 else -1 for row in control_rtt}) == 1
        )
        rows.append({
            "profile": item["profile"],
            "rounds": len(runs),
            "internal_detected_rounds": internal_detected,
            "rtt_detected_rounds": rtt_detected,
            "rtt_detection_rate_percent": 100.0 * rtt_detected / len(runs),
            "internal_mean_difference_ns": statistics.fmean(row["mean_difference_ns"] for row in internal),
            "rtt_mean_difference_ns": statistics.fmean(row["mean_difference_ns"] for row in rtt),
            "rtt_control_systematic": systematic_control,
            "formal_rtt_evidence": rtt_detected == len(runs) and not systematic_control,
        })
    return rows


def plot_report(result: dict, output: Path) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summaries = result["profile_summary"]
    plot_labels = {"none": "No added noise", "low": "Low", "medium": "Medium", "high": "High"}
    labels = [plot_labels[row["profile"]["id"]] for row in summaries]
    internal = [row["internal_mean_difference_ns"] for row in summaries]
    rtt = [row["rtt_mean_difference_ns"] for row in summaries]
    rates = [row["rtt_detection_rate_percent"] for row in summaries]
    x = range(len(labels))
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    width = 0.36
    axes[0].bar([v - width / 2 for v in x], internal, width, label="Server internal", color="#555555")
    axes[0].bar([v + width / 2 for v in x], rtt, width, label="Client RTT", color="#a0a0a0")
    axes[0].axhline(0, color="#222222", linewidth=0.8)
    axes[0].set_xticks(list(x), labels)
    axes[0].set_ylabel("Paired mean difference (ns)")
    axes[0].set_title("Signal observed through two timing channels")
    axes[0].legend()
    axes[1].plot(list(x), rates, "o-", linewidth=2, color="#555555")
    axes[1].set_xticks(list(x), labels)
    axes[1].set_ylim(-5, 105)
    axes[1].set_ylabel("RTT detected rounds (%)")
    axes[1].set_title("Detection stability under controlled jitter")
    axes[1].grid(axis="y", color="#dddddd")
    figure.suptitle(
        f"{result['target_id']} / ML-KEM-{result['level']} / "
        f"{result['pairs']:,} pairs × {result['repeats']} rounds"
    )
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return str(output)
