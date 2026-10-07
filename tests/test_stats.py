"""``backend/stats.py`` 的单元测试。

验证策略（不依赖 scipy/numpy）：

1. t 分布用数学闭式解交叉验证——df=1 是柯西分布、df=2 有精确反演公式，
   再用标准 t 表临界值（df=8/10/30）核对双尾 p 值；
2. Mann-Whitney U 用组合枚举的精确 p 值作为独立对照实现；
3. 配对块平衡分析复刻 ``tests/test_formal_timing.py`` 的期望值，
   证明本模块与 ``backend/formal_timing.py`` 对同一批数据给出相同口径的结果；
4. 如果环境里装了 scipy，额外做一次交叉校验。
"""

import json
import math
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import stats  # noqa: E402

try:
    import formal_timing  # PR #1 合并前该模块不存在
except ImportError:
    formal_timing = None

# scipy 是可选的第三方依赖，只用于交叉校验，必须捕获所有异常。
# 在 Ubuntu 上遇到过系统自带 scipy 与 numpy 二进制不兼容的情况，
# 导入时抛的是 ValueError（numpy.dtype size changed）而不是 ImportError；
# 只捕获 ImportError 会让整个测试套件直接崩掉。
try:
    from scipy import stats as scipy_stats
except Exception:  # noqa: BLE001 - 可选依赖的任何导入失败都不应影响测试套件
    scipy_stats = None


def write_csv(path: Path, rows, header="pair,sample,order,valid_ns,changed_ns"):
    with path.open("w", encoding="utf-8") as handle:
        handle.write(header + "\n")
        for row in rows:
            handle.write(",".join(str(value) for value in row) + "\n")


def run_cli(arguments):
    """用固定 UTF-8 编码运行 CLI。

    不能依赖本机 locale：中文 Windows 的默认编码是 GBK，而 CLI 输出含中文，
    两边不一致会让 subprocess 的读取线程抛 UnicodeDecodeError。
    """
    return subprocess.run(
        [sys.executable, str(ROOT / "backend" / "stats.py"), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        check=False,
    )


class PercentileTest(unittest.TestCase):
    def test_linear_interpolation(self):
        values = [1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(stats.percentile(values, 0.0), 1.0)
        self.assertAlmostEqual(stats.percentile(values, 0.25), 1.75)
        self.assertAlmostEqual(stats.percentile(values, 0.50), 2.5)
        self.assertAlmostEqual(stats.percentile(values, 1.0), 4.0)

    @unittest.skipUnless(formal_timing is not None, "需要 PR #1 的 backend/formal_timing.py")
    def test_matches_formal_timing_definition(self):
        """与 formal_timing.py 的实现逐点比对，保证口径不分叉。"""
        import formal_timing as reference

        values = [17.0, 3.5, 99.0, 42.0, 8.25, 61.0, 0.5]
        for fraction in (0.0, 0.05, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0):
            self.assertAlmostEqual(
                stats.percentile(values, fraction),
                reference.percentile(values, fraction),
                places=12,
            )

    def test_rejects_empty_and_out_of_range(self):
        with self.assertRaises(ValueError):
            stats.percentile([], 0.5)
        with self.assertRaises(ValueError):
            stats.percentile([1.0], 1.5)


class SummarizeTest(unittest.TestCase):
    def test_values(self):
        result = stats.summarize([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(result["count"], 5)
        self.assertAlmostEqual(result["mean_ns"], 3.0)
        self.assertAlmostEqual(result["stddev_ns"], 1.5811388300841898)
        self.assertAlmostEqual(result["p05_ns"], 1.2)
        self.assertAlmostEqual(result["p25_ns"], 2.0)
        self.assertAlmostEqual(result["p50_ns"], 3.0)
        self.assertAlmostEqual(result["p75_ns"], 4.0)
        self.assertAlmostEqual(result["p90_ns"], 4.6)
        self.assertAlmostEqual(result["p95_ns"], 4.8)
        self.assertAlmostEqual(result["p99_ns"], 4.96)
        self.assertAlmostEqual(result["minimum_ns"], 1.0)
        self.assertAlmostEqual(result["maximum_ns"], 5.0)
        self.assertAlmostEqual(result["range_ns"], 4.0)
        self.assertAlmostEqual(result["iqr_ns"], 2.0)

    def test_covers_required_percentiles(self):
        """题目要求 4 明确列出 P90/P95/P99 与方差类指标。"""
        result = stats.summarize([float(value) for value in range(1, 101)])
        for key in ("mean_ns", "stddev_ns", "p50_ns", "p90_ns", "p95_ns", "p99_ns"):
            self.assertIn(key, result)

    def test_single_sample_has_zero_deviation(self):
        self.assertEqual(stats.summarize([7.0])["stddev_ns"], 0.0)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            stats.summarize([])


class StudentTTest(unittest.TestCase):
    """用闭式解验证不完全贝塔函数，而不是自己验证自己。"""

    def test_df_one_is_cauchy(self):
        for t in (0.0, 0.5, 1.0, 2.0, 12.706204736):
            expected = 1.0 - 2.0 * math.atan(t) / math.pi
            self.assertAlmostEqual(stats.student_t_two_sided_p(t, 1), expected, places=12)

    def test_df_two_closed_form(self):
        for t in (0.0, 1.0, 3.0, 4.302652730):
            expected = 1.0 - t / math.sqrt(2.0 + t * t)
            self.assertAlmostEqual(stats.student_t_two_sided_p(t, 2), expected, places=12)

    def test_df_four_closed_form(self):
        # df=4 时双尾 p = 1 - 1.5*s + 0.5*s^3，其中 s = t / sqrt(t^2 + 4)
        # （已用 scipy 1.18.1 逐点核对；t=2.776445105 是 df=4 的双侧 0.05 临界值）
        for t in (0.0, 0.5, 1.0, 2.0, 2.776445105):
            s = t / math.sqrt(t * t + 4.0)
            expected = 1.0 - 1.5 * s + 0.5 * s**3
            self.assertAlmostEqual(stats.student_t_two_sided_p(t, 4), expected, places=12)
        self.assertAlmostEqual(stats.student_t_two_sided_p(2.776445105, 4), 0.05, places=10)

    def test_matches_standard_t_table_at_five_percent(self):
        """标准双侧 0.05 临界值，df=1/8/10/30。"""
        table = {1: 12.706204736, 8: 2.306004135, 10: 2.228138852, 30: 2.042272456}
        for degrees, critical in table.items():
            self.assertAlmostEqual(stats.student_t_two_sided_p(critical, degrees), 0.05, places=9)
            self.assertAlmostEqual(stats.student_t_critical(degrees), critical, places=6)

    def test_converges_to_normal_for_large_df(self):
        self.assertAlmostEqual(stats.student_t_two_sided_p(1.959963985, 10**7), 0.05, places=5)

    def test_monotonically_decreasing(self):
        previous = 2.0  # 起点大于 1，才能断言 t=0 时 p=1 之后的严格下降
        for t in (0.0, 0.5, 1.0, 2.0, 5.0, 10.0):
            current = stats.student_t_two_sided_p(t, 12)
            self.assertLess(current, previous)
            previous = current

    def test_rejects_non_positive_df(self):
        with self.assertRaises(ValueError):
            stats.student_t_two_sided_p(1.0, 0)


class WelchTTestTest(unittest.TestCase):
    def test_hand_computed_example(self):
        # a=[1..5] 与 b=[4..8]：均值差 3，方差各 2.5，标准误 1，t=3，df=8
        result = stats.welch_t_test([1, 2, 3, 4, 5], [4, 5, 6, 7, 8])
        self.assertAlmostEqual(result["t_statistic"], 3.0, places=12)
        self.assertAlmostEqual(result["degrees_of_freedom"], 8.0, places=12)
        self.assertAlmostEqual(result["mean_difference_ns"], 3.0)
        # t=3 落在 df=8 的双侧 0.02(t=2.896) 与 0.01(t=3.355) 之间
        self.assertGreater(result["p_value"], 0.01)
        self.assertLess(result["p_value"], 0.02)
        lower, upper = result["difference_ci_ns"]
        self.assertAlmostEqual(lower, 3.0 - 2.306004135, places=6)
        self.assertAlmostEqual(upper, 3.0 - 2.306004135 + 2 * 2.306004135, places=6)

    def test_identical_groups_are_not_significant(self):
        values = [float(value) for value in range(1, 51)]
        result = stats.welch_t_test(values, values)
        self.assertAlmostEqual(result["t_statistic"], 0.0)
        self.assertAlmostEqual(result["p_value"], 1.0)

    def test_unequal_variance_reduces_degrees_of_freedom(self):
        wide = [0.0, 100.0, 200.0, 300.0]
        narrow = [100.0, 101.0, 102.0, 103.0]
        result = stats.welch_t_test(wide, narrow)
        # Welch 自由度严格小于 n1+n2-2=6
        self.assertLess(result["degrees_of_freedom"], 6)

    def test_requires_two_samples_per_group(self):
        with self.assertRaises(ValueError):
            stats.welch_t_test([1.0], [2.0, 3.0])


class RanksTest(unittest.TestCase):
    def test_midranks_with_ties(self):
        self.assertEqual(stats.ranks_of([3.0, 1.0, 3.0, 2.0]), [3.5, 1.0, 3.5, 2.0])

    def test_no_ties_is_plain_order(self):
        self.assertEqual(stats.ranks_of([30.0, 10.0, 20.0]), [3.0, 1.0, 2.0])

    def test_tie_group_sizes(self):
        self.assertEqual(sorted(stats.tie_group_sizes([1.0, 1.0, 2.0, 3.0, 3.0, 3.0])), [2, 3])
        self.assertEqual(stats.tie_group_sizes([1.0, 2.0, 3.0]), [])


class MannWhitneyTest(unittest.TestCase):
    def test_fully_separated_matches_exact_distribution(self):
        sample_a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        sample_b = [7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
        result = stats.mann_whitney_u(sample_a, sample_b)
        self.assertAlmostEqual(result["u_statistic"], 0.0)
        self.assertAlmostEqual(result["u_min"], 0.0)
        self.assertAlmostEqual(result["expected_u"], 18.0)
        # 完全分离时精确双尾 p = 2 / C(12,6)
        self.assertAlmostEqual(result["exact_p_value"], 2.0 / math.comb(12, 6), places=12)
        # 正态近似含连续性修正：z = (18 - 0.5) / sqrt(6*6*13/12)
        self.assertAlmostEqual(result["z_statistic"], 17.5 / math.sqrt(39.0), places=10)
        self.assertAlmostEqual(result["p_value"], math.erfc(17.5 / math.sqrt(39.0) / math.sqrt(2.0)), places=12)

    def test_identical_groups_are_not_significant(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        result = stats.mann_whitney_u(values, values)
        self.assertAlmostEqual(result["u_statistic"], result["expected_u"])
        self.assertAlmostEqual(result["p_value"], 1.0)

    def test_all_values_tied_does_not_divide_by_zero(self):
        result = stats.mann_whitney_u([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
        self.assertEqual(result["z_statistic"], 0.0)
        self.assertEqual(result["p_value"], 1.0)
        self.assertIsNone(result["exact_p_value"])

    def test_exact_is_skipped_when_ties_present(self):
        result = stats.mann_whitney_u([1.0, 1.0, 2.0], [3.0, 4.0, 5.0])
        self.assertIsNone(result["exact_p_value"])

    def test_normal_approximation_tracks_exact_for_moderate_samples(self):
        sample_a = [float(value) for value in range(10)]
        sample_b = [float(value) + 3.5 for value in range(10)]
        result = stats.mann_whitney_u(sample_a, sample_b)
        self.assertIsNotNone(result["exact_p_value"])
        # 中等样本量下近似值应与精确值同量级
        self.assertLess(abs(result["p_value"] - result["exact_p_value"]), 0.05 * max(result["exact_p_value"], 1e-3) + 0.02)

    def test_continuity_correction_can_be_disabled(self):
        sample_a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        sample_b = [7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
        uncorrected = stats.mann_whitney_u(sample_a, sample_b, continuity_correction=False)
        self.assertAlmostEqual(uncorrected["z_statistic"], 18.0 / math.sqrt(39.0), places=10)


class PairedBlockAnalysisTest(unittest.TestCase):
    """复刻 tests/test_formal_timing.py 的期望值，证明口径与 PR #1 一致。"""

    def test_paired_difference_and_counts(self):
        sample_a = [float(1000 + index % 5) for index in range(100)]
        sample_b = [value + 25 + index % 3 for index, value in enumerate(sample_a)]
        orders = [index % 2 for index in range(100)]
        result = stats.paired_block_analysis(sample_a, sample_b, orders)
        self.assertEqual(result["first_a_count"], 50)
        self.assertEqual(result["first_b_count"], 50)
        self.assertTrue(result["statistically_distinguishable"])
        self.assertGreater(result["paired_difference_ci_ns"][0], 0)
        # 块数不足时退回逐配对区间
        self.assertEqual(result["block_count"], 0)
        self.assertAlmostEqual(result["paired_mean_difference_ns"], 25.99, places=6)

    def test_order_balanced_block_estimate(self):
        sample_a = [1000.0] * 2000
        sample_b = []
        orders = []
        for index in range(2000):
            order = index % 2
            difference = 40 + (100 if order == 0 else -100)
            sample_b.append(1000.0 + difference)
            orders.append(order)
        result = stats.paired_block_analysis(sample_a, sample_b, orders)
        self.assertEqual(result["block_count"], 10)
        self.assertAlmostEqual(result["paired_mean_difference_ns"], 40.0)
        self.assertTrue(result["statistically_distinguishable"])

    def test_order_bias_is_cancelled_by_blocking(self):
        """块内两种顺序的样本量不等时，只有块平衡才能抵消顺序偏移。

        需要至少 min_blocks * block_size = 1000 个配对才会走块平衡分支，
        否则会退回逐配对均值，块平衡逻辑根本不会被触发。
        """
        sample_a, sample_b, orders = [], [], []
        for index in range(1200):
            order = 0 if index % 4 < 3 else 1
            bias = 500.0 if order == 0 else -500.0
            sample_a.append(1000.0)
            sample_b.append(1000.0 + 7.0 + bias)
            orders.append(order)
        result = stats.paired_block_analysis(sample_a, sample_b, orders)
        self.assertEqual(result["block_count"], 6)
        # 未做块平衡的原始均值被顺序偏移严重污染，块平衡后回到真实差值附近
        self.assertGreater(abs(result["unadjusted_paired_mean_difference_ns"] - 7.0), 100.0)
        self.assertAlmostEqual(result["paired_mean_difference_ns"], 7.0, places=9)

    def test_rejects_mismatched_lengths(self):
        with self.assertRaises(ValueError):
            stats.paired_block_analysis([1.0, 2.0], [1.0, 2.0, 3.0], [0, 1])


class CompareTwoClassesTest(unittest.TestCase):
    def test_detects_clear_difference(self):
        sample_a = [float(1000 + index % 5) for index in range(200)]
        sample_b = [value + 300 for value in sample_a]
        orders = [index % 2 for index in range(200)]
        result = stats.compare_two_classes(sample_a, sample_b, orders=orders)
        self.assertTrue(result["verdict"]["welch_significant"])
        self.assertTrue(result["verdict"]["mann_whitney_significant"])
        self.assertTrue(result["verdict"]["statistically_significant"])
        self.assertTrue(result["verdict"]["practically_relevant"])
        # class_a 均值 = 1000 + mean(0..4 均匀重复) = 1002，差 300
        self.assertAlmostEqual(result["relative_mean_difference_percent"], 100.0 * 300.0 / 1002.0, places=9)
        self.assertIn("主检验", result["verdict"]["text"])
        self.assertEqual(result["verdict"]["primary_test"], "paired_difference_tests")
        self.assertFalse(result["verdict"]["independent_sample_conflicts_with_paired"])

    def test_no_difference_reports_bounded_conclusion(self):
        base = [float(1000 + index % 17) for index in range(200)]
        result = stats.compare_two_classes(base, base[::-1])
        self.assertFalse(result["verdict"]["statistically_significant"])
        self.assertIn("不能证明实现绝对恒定时间", result["verdict"]["text"])
        self.assertIsNone(result["paired"])
        self.assertTrue(any("未观察到差异不能证明" in note for note in result["caveats"]))

    def test_small_but_significant_difference_is_not_overclaimed(self):
        """统计显著但相对差异极小，不应直接当成有实际意义。"""
        sample_a = [float(10000 + index % 3) for index in range(300)]
        sample_b = [value + 2.0 for value in sample_a]
        result = stats.compare_two_classes(sample_a, sample_b)
        self.assertTrue(result["verdict"]["statistically_significant"])
        self.assertFalse(result["verdict"]["practically_relevant"])
        self.assertLess(result["relative_mean_difference_percent"], 1.0)

    def test_requires_two_samples_per_group(self):
        with self.assertRaises(ValueError):
            stats.compare_two_classes([1.0], [2.0, 3.0])


class PairedDesignTest(unittest.TestCase):
    """配对数据的陷阱：把配对样本当独立样本会因测量顺序偏移产生假阳性。

    这个缺陷是在端到端演示中发现的：真实差值为 0 的合成数据被 Welch 与
    Mann-Whitney 判成极显著（p≈1e-107），而块平衡后的配对差值精确为 0.00 ns。
    原因是每对样本的两次测量背靠背进行、顺序随机，位置效应使两类原始样本的
    分布整体错开，独立样本检验会把这个位移误当成类别差异。
    """

    @staticmethod
    def _order_biased(shift, count=3000, bias=1500.0, seed=20260928):
        rng = random.Random(seed)
        sample_a, sample_b, orders = [], [], []
        for _ in range(count):
            order = 0 if rng.random() < 0.7 else 1
            first = 32000.0 + rng.gauss(0, 200)
            sample_a.append(first)
            sample_b.append(first + shift + (bias if order == 0 else -bias))
            orders.append(order)
        return sample_a, sample_b, orders

    def test_null_case_is_not_reported_as_significant(self):
        sample_a, sample_b, orders = self._order_biased(0.0)
        result = stats.compare_two_classes(sample_a, sample_b, orders=orders)
        self.assertAlmostEqual(result["paired"]["paired_mean_difference_ns"], 0.0, places=6)
        self.assertFalse(result["verdict"]["statistically_significant"])
        self.assertFalse(result["verdict"]["practically_relevant"])
        self.assertIn("没有判出差异", result["verdict"]["text"])

    def test_independent_sample_tests_are_flagged_as_conflicting(self):
        """独立样本检验确实会被顺序偏移误导，且必须被显式标注出来。"""
        sample_a, sample_b, orders = self._order_biased(0.0)
        result = stats.compare_two_classes(sample_a, sample_b, orders=orders)
        self.assertTrue(result["verdict"]["welch_significant"])
        self.assertTrue(result["verdict"]["mann_whitney_significant"])
        self.assertTrue(result["verdict"]["independent_sample_significant"])
        self.assertTrue(result["verdict"]["independent_sample_conflicts_with_paired"])
        self.assertIn("不应采用独立样本检验的结论", result["verdict"]["text"])
        self.assertEqual(result["verdict"]["primary_test"], "paired_difference_tests")

    def test_real_difference_is_detected_and_recovered(self):
        sample_a, sample_b, orders = self._order_biased(150.0)
        result = stats.compare_two_classes(sample_a, sample_b, orders=orders)
        self.assertAlmostEqual(result["paired"]["paired_mean_difference_ns"], 150.0, places=6)
        self.assertTrue(result["verdict"]["statistically_significant"])
        # 150 ns 在 32 µs 的解封装上只占 0.47%，低于默认 1% 的实际意义阈值：
        # 统计上能测出来，不等于有实际意义——这正是要区分的两件事。
        self.assertAlmostEqual(
            result["relative_mean_difference_percent"],
            100.0 * 150.0 / result["class_a"]["mean_ns"],
            places=9,
        )
        self.assertFalse(result["verdict"]["practically_relevant"])
        # 放低阈值后应能判为有实际意义
        relaxed = stats.compare_two_classes(
            sample_a, sample_b, orders=orders, relevance_percent=0.1
        )
        self.assertTrue(relaxed["verdict"]["practically_relevant"])
        # 未平衡估计被顺序偏移严重污染
        self.assertGreater(
            abs(result["paired"]["unadjusted_paired_mean_difference_ns"] - 150.0), 100.0
        )
        self.assertFalse(result["verdict"]["independent_sample_conflicts_with_paired"])

    def test_paired_test_has_much_smaller_standard_error(self):
        """配对检验的方差远小于独立样本检验，这是配对设计的核心收益。"""
        sample_a, sample_b, orders = self._order_biased(150.0)
        result = stats.compare_two_classes(sample_a, sample_b, orders=orders)
        paired_error = result["paired"]["difference_t_test"]["standard_error_ns"]
        unpaired_error = result["welch"]["difference_ci_ns"][1] - result["welch"]["mean_difference_ns"]
        self.assertLess(paired_error, 10.0)
        self.assertLess(paired_error, unpaired_error)

    def test_primary_estimate_drives_relative_percent(self):
        """相对差值必须用块平衡后的估计，与 formal_timing.py 口径一致。"""
        sample_a, sample_b, orders = self._order_biased(150.0)
        result = stats.compare_two_classes(sample_a, sample_b, orders=orders)
        expected = 100.0 * result["paired"]["paired_mean_difference_ns"] / result["class_a"]["mean_ns"]
        self.assertAlmostEqual(result["relative_mean_difference_percent"], expected, places=9)
        self.assertNotAlmostEqual(
            result["relative_mean_difference_percent"],
            100.0 * result["raw_mean_difference_ns"] / result["class_a"]["mean_ns"],
            places=3,
        )

    def test_unpaired_path_still_uses_independent_tests(self):
        """没有配对标签时（例如对比两个不同实现）仍用独立样本检验。"""
        sample_a = [100.0 + index * 0.1 for index in range(200)]
        sample_b = [value + 50.0 for value in sample_a]
        result = stats.compare_two_classes(sample_a, sample_b)
        self.assertIsNone(result["paired"])
        self.assertEqual(result["verdict"]["primary_test"], "welch_and_mann_whitney")
        self.assertTrue(result["verdict"]["statistically_significant"])
        self.assertFalse(result["verdict"]["independent_sample_conflicts_with_paired"])


class WilcoxonTest(unittest.TestCase):
    def test_all_zero_differences(self):
        result = stats.wilcoxon_signed_rank([0.0, 0.0, 0.0])
        self.assertEqual(result["p_value"], 1.0)
        self.assertEqual(result["nonzero_count"], 0)
        self.assertEqual(result["zero_count"], 3)

    def test_symmetric_differences_are_not_significant(self):
        result = stats.wilcoxon_signed_rank([1.0, -1.0, 2.0, -2.0, 3.0, -3.0, 4.0, -4.0])
        self.assertAlmostEqual(result["positive_rank_sum"], result["negative_rank_sum"])
        self.assertAlmostEqual(result["p_value"], 1.0)

    def test_consistent_sign_is_significant(self):
        result = stats.wilcoxon_signed_rank([5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0])
        self.assertEqual(result["negative_rank_sum"], 0.0)
        self.assertLess(result["p_value"], 0.02)

    def test_zero_differences_are_excluded(self):
        with_zeros = stats.wilcoxon_signed_rank([5.0, 6.0, 7.0, 8.0, 0.0, 0.0])
        without_zeros = stats.wilcoxon_signed_rank([5.0, 6.0, 7.0, 8.0])
        self.assertEqual(with_zeros["w_statistic"], without_zeros["w_statistic"])
        self.assertEqual(with_zeros["zero_count"], 2)
        self.assertEqual(with_zeros["p_value"], without_zeros["p_value"])


class OneSampleTTestTest(unittest.TestCase):
    def test_zero_mean_differences_are_not_significant(self):
        result = stats.one_sample_t_test([1.0, -1.0, 2.0, -2.0, 3.0, -3.0])
        self.assertAlmostEqual(result["mean_ns"], 0.0)
        self.assertAlmostEqual(result["t_statistic"], 0.0)
        self.assertAlmostEqual(result["p_value"], 1.0)
        self.assertLess(result["ci_ns"][0], 0.0)
        self.assertGreater(result["ci_ns"][1], 0.0)

    def test_detects_consistent_shift(self):
        result = stats.one_sample_t_test([10.0, 11.0, 9.0, 10.5, 10.2, 9.8])
        self.assertGreater(result["ci_ns"][0], 0.0)
        self.assertLess(result["p_value"], 0.001)
        self.assertEqual(result["degrees_of_freedom"], 5)

    def test_requires_two_observations(self):
        with self.assertRaises(ValueError):
            stats.one_sample_t_test([1.0])


class LoadCsvTest(unittest.TestCase):
    def test_reads_formal_timing_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            write_csv(path, [(0, 0, 0, 100, 130), (1, 0, 1, 140, 105)])
            data = stats.load_paired_csv(path)
            self.assertEqual(data["samples_a"], [100.0, 140.0])
            self.assertEqual(data["samples_b"], [130.0, 105.0])
            self.assertEqual(data["orders"], [0, 1])

    def test_reports_available_columns_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            write_csv(path, [(0, 0, 0, 100, 130)])
            with self.assertRaises(ValueError) as context:
                stats.load_paired_csv(path, a_column="valid_ns", b_column="missing_ns")
            self.assertIn("missing_ns", str(context.exception))
            self.assertIn("changed_ns", str(context.exception))

    def test_rejects_empty_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            write_csv(path, [])
            with self.assertRaises(ValueError):
                stats.load_paired_csv(path)
            with self.assertRaises(FileNotFoundError):
                stats.load_paired_csv(Path(directory) / "nope.csv")


class AnalyzeFileAndCliTest(unittest.TestCase):
    def test_analyze_file_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.csv"
            rows = []
            for index in range(400):
                order = index % 2
                sample_a = 1000 + index % 7
                sample_b = sample_a + 120
                rows.append((index, index % 32, order, sample_a, sample_b))
            write_csv(path, rows)
            result = stats.analyze_file(path)
            self.assertEqual(result["class_a"]["count"], 400)
            self.assertEqual(result["class_b"]["count"], 400)
            self.assertTrue(result["verdict"]["statistically_significant"])
            self.assertEqual(result["columns"]["a"], "valid_ns")

    def test_cli_writes_output_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.csv"
            rows = [(index, index % 32, index % 2, 1000 + index % 7, 1120 + index % 7) for index in range(400)]
            write_csv(path, rows)
            output = Path(directory) / "analysis.json"
            completed = run_cli([str(path), "--output", str(output)])
            self.assertEqual(completed.returncode, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("verdict", payload)
            self.assertEqual(payload["class_a"]["count"], 400)

    def test_cli_rejects_bad_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.csv"
            write_csv(path, [(0, 0, 0, 100, 130)])
            completed = run_cli([str(path), "--b-column", "nope"])
            self.assertEqual(completed.returncode, 2)
            self.assertIsNotNone(completed.stderr)
            self.assertIn("nope", completed.stderr)

    def test_cli_output_is_locale_independent(self):
        """CLI 自己固定 UTF-8 输出，不应依赖 PYTHONIOENCODING 是否设置。

        这条测试是在中文 Windows（locale=GBK）上暴露真实缺陷后补的：
        当时 subprocess 读取线程抛 UnicodeDecodeError，stderr 直接变成 None。
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.csv"
            write_csv(path, [(0, 0, 0, 100, 130)])
            arguments = [str(path), "--b-column", "nope"]

            with_variable = run_cli(arguments)
            environment = dict(os.environ)
            environment.pop("PYTHONIOENCODING", None)
            without_variable = subprocess.run(
                [sys.executable, str(ROOT / "backend" / "stats.py"), *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )

            self.assertEqual(with_variable.stderr, without_variable.stderr)
            self.assertIn("错误", without_variable.stderr)
            self.assertIn("nope", without_variable.stderr)


@unittest.skipUnless(formal_timing is not None, "需要 PR #1 的 backend/formal_timing.py")
class FormalTimingCompatibilityTest(unittest.TestCase):
    """确认本模块与 ``backend/formal_timing.py`` 对同一批数据口径完全一致。

    PR #1 合并后该测试自动生效，防止两套统计实现随时间分叉。
    """

    SUMMARY_KEYS = (
        "count",
        "mean_ns",
        "stddev_ns",
        "p05_ns",
        "p50_ns",
        "p95_ns",
        "minimum_ns",
        "maximum_ns",
    )

    @staticmethod
    def _write_pairs(path: Path, count: int) -> None:
        """写入带测量顺序效应的配对数据。

        差值与先后顺序相关，且顺序在块内是 3:1 不均衡的，因此「未做块平衡的
        原始均值」与「块平衡后的估计」会明显不同。若只用与顺序无关的数据，
        两种口径恰好相等，测试就无法发现口径分叉。
        """
        rows = []
        for index in range(count):
            order = 0 if index % 4 < 3 else 1
            sample_a = 1000 + (index * 13) % 37
            position_bias = 300 if order == 0 else -300
            sample_b = sample_a + 20 + index % 5 + position_bias
            rows.append((index, index % 32, order, sample_a, sample_b))
        write_csv(path, rows)

    def _assert_same_result(self, path: Path) -> None:
        reference = formal_timing.analyze_csv(path)
        mine = stats.analyze_file(path)
        for key in self.SUMMARY_KEYS:
            self.assertAlmostEqual(reference["valid"][key], mine["class_a"][key], places=9, msg=f"valid.{key}")
            self.assertAlmostEqual(
                reference["changed"][key], mine["class_b"][key], places=9, msg=f"changed.{key}"
            )
        paired = mine["paired"]
        self.assertAlmostEqual(
            reference["paired_mean_difference_ns"], paired["paired_mean_difference_ns"], places=9
        )
        self.assertAlmostEqual(
            reference["unadjusted_paired_mean_difference_ns"],
            paired["unadjusted_paired_mean_difference_ns"],
            places=9,
        )
        self.assertAlmostEqual(
            reference["paired_difference_ci95_ns"][0], paired["paired_difference_ci_ns"][0], places=9
        )
        self.assertAlmostEqual(
            reference["paired_difference_ci95_ns"][1], paired["paired_difference_ci_ns"][1], places=9
        )
        self.assertAlmostEqual(
            reference["relative_mean_difference_percent"],
            mine["relative_mean_difference_percent"],
            places=9,
        )
        self.assertEqual(reference["block_count"], paired["block_count"])
        self.assertEqual(reference["first_valid_count"], paired["first_a_count"])
        self.assertEqual(reference["first_changed_count"], paired["first_b_count"])
        self.assertEqual(
            reference["statistically_distinguishable"], paired["statistically_distinguishable"]
        )

    def test_matches_with_block_balancing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.csv"
            self._write_pairs(path, 2000)
            # 先确认测试数据本身有判别力：块平衡与未平衡的结果必须不同，
            # 否则两种口径恰好相等，测试就发现不了口径分叉。
            reference = formal_timing.analyze_csv(path)
            self.assertGreater(
                abs(
                    reference["unadjusted_paired_mean_difference_ns"]
                    - reference["paired_mean_difference_ns"]
                ),
                1.0,
            )
            self._assert_same_result(path)

    def test_matches_with_pairwise_fallback(self):
        """配对不足 1000 组时两边都应退回逐配对区间。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.csv"
            self._write_pairs(path, 400)
            reference = formal_timing.analyze_csv(path)
            self.assertEqual(reference["block_count"], 2)
            self._assert_same_result(path)

    def test_both_reject_too_few_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.csv"
            self._write_pairs(path, 50)
            with self.assertRaises(ValueError):
                formal_timing.analyze_csv(path)
            with self.assertRaises(ValueError):
                stats.analyze_file(path)


@unittest.skipUnless(scipy_stats is not None, "需要 scipy 才做交叉校验")
class ScipyCrossCheckTest(unittest.TestCase):  # pragma: no cover - 依赖可选包
    def test_t_distribution_matches_scipy(self):
        for t in (0.1, 1.0, 2.5, 7.0):
            for degrees in (1, 2, 5, 17.3, 60):
                self.assertAlmostEqual(
                    stats.student_t_two_sided_p(t, degrees),
                    float(2.0 * scipy_stats.t.sf(abs(t), degrees)),
                    places=10,
                )

    def test_mann_whitney_matches_scipy(self):
        """含并列值：两组数据的 U 值、连续性修正与非修正 p 值都应与 scipy 一致。"""
        sample_a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        sample_b = [4.0, 5.0, 6.0, 9.0, 10.0, 11.0, 12.0, 13.0]
        reference_u = scipy_stats.mannwhitneyu(sample_a, sample_b, alternative="two-sided").statistic
        self.assertAlmostEqual(stats.mann_whitney_u(sample_a, sample_b)["u_statistic"], float(reference_u), places=9)
        for continuity in (False, True):
            mine = stats.mann_whitney_u(sample_a, sample_b, continuity_correction=continuity)
            reference = scipy_stats.mannwhitneyu(
                sample_a,
                sample_b,
                alternative="two-sided",
                method="asymptotic",
                use_continuity=continuity,
            )
            self.assertAlmostEqual(
                mine["p_value"],
                float(reference.pvalue),
                places=9,
                msg=f"continuity_correction={continuity}",
            )

    def test_mann_whitney_matches_scipy_without_ties(self):
        sample_a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        sample_b = [9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
        for continuity in (False, True):
            mine = stats.mann_whitney_u(sample_a, sample_b, continuity_correction=continuity)
            reference = scipy_stats.mannwhitneyu(
                sample_a,
                sample_b,
                alternative="two-sided",
                method="asymptotic",
                use_continuity=continuity,
            )
            self.assertAlmostEqual(
                mine["p_value"],
                float(reference.pvalue),
                places=9,
                msg=f"continuity_correction={continuity}",
            )

    def test_exact_p_value_matches_scipy_exact(self):
        sample_a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        sample_b = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]
        reference = scipy_stats.mannwhitneyu(sample_a, sample_b, alternative="two-sided", method="exact")
        self.assertAlmostEqual(
            stats.mann_whitney_u_exact(sample_a, sample_b), float(reference.pvalue), places=12
        )

    def test_welch_matches_scipy(self):
        """我方言号约定为 mean(b)-mean(a)（与 PR #1 的"变化减正常"一致）。

        scipy 的 ttest_ind 是 mean(a)-mean(b)，因此统计量符号相反、p 值相同。
        """
        sample_a = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 7.5]
        sample_b = [3.0, 3.5, 9.0, 10.0, 11.5, 40.0, 2.5, 6.0]
        mine = stats.welch_t_test(sample_a, sample_b)
        reference = scipy_stats.ttest_ind(sample_a, sample_b, equal_var=False)
        self.assertAlmostEqual(mine["t_statistic"], -float(reference.statistic), places=12)
        self.assertAlmostEqual(mine["p_value"], float(reference.pvalue), places=12)
        self.assertAlmostEqual(mine["degrees_of_freedom"], float(reference.df), places=12)
        self.assertGreater(mine["mean_difference_ns"], 0.0)
        self.assertAlmostEqual(
            mine["mean_difference_ns"], sum(sample_b) / len(sample_b) - sum(sample_a) / len(sample_a), places=12
        )

    def test_t_critical_matches_scipy(self):
        for degrees in (1, 4, 8, 17.3, 30, 1000):
            self.assertAlmostEqual(
                stats.student_t_critical(degrees, 0.95),
                float(scipy_stats.t.ppf(0.975, degrees)),
                places=9,
            )

    def test_one_sample_t_matches_scipy(self):
        differences = [3.0, 1.5, -2.0, 4.5, 0.5, 6.0, -1.0, 2.5]
        mine = stats.one_sample_t_test(differences)
        reference = scipy_stats.ttest_1samp(differences, 0.0)
        self.assertAlmostEqual(mine["t_statistic"], float(reference.statistic), places=12)
        self.assertAlmostEqual(mine["p_value"], float(reference.pvalue), places=12)

    def test_wilcoxon_matches_scipy(self):
        """使用 method="approx" 与我的正态近似对齐（scipy 小样本默认走精确检验）。"""
        differences = [3.0, 1.5, -2.0, 4.5, 0.5, 6.0, -1.0, 2.5, 0.0]
        for correction in (False, True):
            mine = stats.wilcoxon_signed_rank(differences, continuity_correction=correction)
            reference = scipy_stats.wilcoxon(
                differences,
                zero_method="wilcox",
                correction=correction,
                alternative="two-sided",
                method="approx",
            )
            self.assertAlmostEqual(
                mine["w_statistic"], float(reference.statistic), places=9, msg=f"correction={correction}"
            )
            self.assertAlmostEqual(
                mine["p_value"], float(reference.pvalue), places=9, msg=f"correction={correction}"
            )

    def test_wilcoxon_matches_scipy_with_ties(self):
        differences = [1.0, 1.0, -2.0, -2.0, 3.0, -3.0, 4.5, -4.5, 5.0]
        mine = stats.wilcoxon_signed_rank(differences)
        reference = scipy_stats.wilcoxon(
            differences,
            zero_method="wilcox",
            correction=True,
            alternative="two-sided",
            method="approx",
        )
        self.assertAlmostEqual(mine["w_statistic"], float(reference.statistic), places=9)
        self.assertAlmostEqual(mine["p_value"], float(reference.pvalue), places=9)


if __name__ == "__main__":
    unittest.main()
