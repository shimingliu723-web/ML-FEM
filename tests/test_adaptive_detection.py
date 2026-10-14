from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from adaptive_detection import decide, resource_summary


def row(significant=False, direction=0, practical=False, migrations=0):
    return {
        "statistically_significant": significant,
        "tests_agree": True,
        "practically_relevant": practical,
        "direction": direction,
        "cpu_migrations": migrations,
    }


def stage(run, control=None, pairs=1000):
    return {"run": run, "control": control or row(), "pairs": pairs}


class AdaptiveDecisionTest(unittest.TestCase):
    def test_two_consistent_stages_stop_with_difference(self):
        stages = [stage(row(True, -1, True)), stage(row(True, -1, True), pairs=3000)]
        result = decide(stages, True)
        self.assertEqual(result["action"], "stop")
        self.assertTrue(result["stable_difference"])
        self.assertTrue(result["formal"])

    def test_three_non_significant_stages_stop_without_stable_difference(self):
        stages = [stage(row()), stage(row(), pairs=3000), stage(row(), pairs=10000)]
        result = decide(stages, True)
        self.assertEqual(result["action"], "stop")
        self.assertTrue(result["stable_null"])

    def test_repeated_control_offset_downgrades_evidence(self):
        bad_control = row(True, 1, True)
        stages = [stage(row(True, -1, True), bad_control), stage(row(True, -1, True), bad_control, 3000)]
        result = decide(stages, True, final=True)
        self.assertTrue(result["systematic_control"])
        self.assertFalse(result["formal"])
        self.assertFalse(result["stable_difference"])

    def test_environment_and_migration_gate_formal_evidence(self):
        stages = [stage(row(True, -1, True)), stage(row(True, -1, True, migrations=1), pairs=3000)]
        self.assertFalse(decide(stages, True)["formal"])
        self.assertFalse(decide(stages, False)["formal"])

    def test_resource_accounting_matches_fixed_reference(self):
        summary = resource_summary([{"pairs":1000},{"pairs":3000},{"pairs":10000}])
        self.assertEqual(summary["adaptive_pairs"], 14000)
        self.assertEqual(summary["fixed_reference_pairs"], 30000)
        self.assertAlmostEqual(summary["pair_saving_percent"], 53.3333333333)


if __name__ == "__main__":
    unittest.main()
