from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from formal_timing import analyze_csv


class FormalTimingAnalysisTest(unittest.TestCase):
    def test_paired_difference_and_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            with path.open("w", encoding="utf-8") as handle:
                handle.write("pair,sample,order,valid_ns,changed_ns\n")
                for index in range(100):
                    valid = 1000 + index % 5
                    changed = valid + 25 + index % 3
                    handle.write(f"{index},{index % 32},{index % 2},{valid},{changed}\n")
            result = analyze_csv(path)
        self.assertEqual(result["valid"]["count"], 100)
        self.assertEqual(result["first_valid_count"], 50)
        self.assertEqual(result["first_changed_count"], 50)
        self.assertTrue(result["statistically_distinguishable"])
        self.assertGreater(result["paired_difference_ci95_ns"][0], 0)


if __name__ == "__main__":
    unittest.main()

