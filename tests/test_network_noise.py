from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from network_noise import analyze_network_csv, selected_profiles, summarize_profiles


class NetworkNoiseTest(unittest.TestCase):
    def test_profile_validation(self):
        profiles = selected_profiles(["none", "high"])
        self.assertEqual([item["id"] for item in profiles], ["none", "high"])
        with self.assertRaises(ValueError):
            selected_profiles(["none", "none"])
        with self.assertRaises(ValueError):
            selected_profiles(["unknown"])

    def test_dual_channel_csv_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow([
                    "pair", "sample", "order", "valid_internal_ns", "changed_internal_ns",
                    "valid_rtt_ns", "changed_rtt_ns", "valid_delay_us", "changed_delay_us",
                    "server_cpu", "client_cpu",
                ])
                for index in range(400):
                    writer.writerow([
                        index, index % 32, index % 2, 1000 + index % 7,
                        1300 + index % 7, 100000 + index % 11,
                        100300 + index % 11, 50, 50, 2, 3,
                    ])
            report = analyze_network_csv(path)
            self.assertEqual(report["pairs"], 400)
            self.assertTrue(report["internal"]["verdict"]["statistically_significant"])
            self.assertTrue(report["rtt"]["verdict"]["statistically_significant"])
            self.assertEqual(report["observed_server_cpus"], [2])
            self.assertEqual(report["observed_client_cpus"], [3])

    def test_summary_keeps_aa_control_separate(self):
        def channel(diff, significant):
            return {
                "paired": {"paired_mean_difference_ns": diff, "paired_difference_ci_ns": [diff - 1, diff + 1]},
                "verdict": {"statistically_significant": significant, "tests_agree": True},
                "relative_mean_difference_percent": diff / 10,
            }
        runs = [{"internal": channel(300, True), "rtt": channel(250, True)} for _ in range(3)]
        controls = [{"internal": channel(0, False), "rtt": channel(0, False)} for _ in range(3)]
        summary = summarize_profiles([{"profile": selected_profiles(["low"])[0], "runs": runs, "controls": controls}])
        self.assertEqual(summary[0]["rtt_detected_rounds"], 3)
        self.assertFalse(summary[0]["rtt_control_systematic"])
        self.assertTrue(summary[0]["formal_rtt_evidence"])


if __name__ == "__main__":
    unittest.main()
