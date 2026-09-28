"""ML-KEM 解封装时间实验的统计分析（纯标准库实现）。

用法::

    python3 backend/stats.py results/timing/<run_id>.csv
    python3 backend/stats.py results/timing/<run_id>.csv --output analysis.json

设计约定（与 ``backend/formal_timing.py`` 保持一致，便于两套代码对同一批数据
给出相同口径的结果）：

* 不做事后异常值剔除，保存并使用全部原始计时；
* 配对数据按固定大小的「时间块」分段，块内平衡两种测量先后顺序；
* 单轮置信区间只作探索性结论，必须结合独立重复轮次解释；
* 区间跨越零不等于「证明实现恒定时间」。

检验选择（重要）：

* **配对数据必须用配对检验。** 同一个实现、两类等长输入、每对背靠背测量且顺序
  随机的数据是配对数据，主检验应为对块平衡估计做单样本 t 检验与 Wilcoxon
  符号秩检验。若误用 Welch / Mann-Whitney 等独立样本检验，测量先后顺序造成的
  位移会被当成类别差异，即使真实差异为 0 也会判出极显著。
  ``tests/test_stats.py`` 的 ``PairedDesignTest`` 固定住了这个回归。
* 独立样本检验仍然保留，用于两组数据确实不配对的场景（例如比较两个不同实现
  的库），此时才是 Welch t 检验与 Mann-Whitney U 检验的正确用法。

与 ``formal_timing.py`` 的区别：本模块补齐题目要求 4 里缺少的正式检验、
P90/P99 分位数和自动结论文本。``percentile`` 的分位数口径完全一致，
``relative_mean_difference_percent`` 同样以块平衡后的配对估计作分子。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from itertools import combinations
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_BLOCK_SIZE = 200
DEFAULT_MIN_BLOCKS = 5
DEFAULT_ALPHA = 0.05
DEFAULT_CONFIDENCE = 0.95
# 配对数据少于此数量时拒绝对外给结论，与 formal_timing.py 的守卫一致。
MIN_PAIRS = 100
# 配对块均值区间沿用 formal_timing.py 的正态近似系数，保持口径一致。
PAIRED_Z_95 = 1.96
# 相对均值差低于该百分比时，即使统计显著也不视为「有实际意义的差异」。
DEFAULT_RELEVANCE_PERCENT = 1.0


# --------------------------------------------------------------------------
# 描述性统计
# --------------------------------------------------------------------------


def percentile(values: Sequence[float], fraction: float) -> float:
    """线性插值分位数，口径与 ``formal_timing.py`` 的 ``percentile`` 相同。"""
    if not values:
        raise ValueError("无法对空序列计算分位数")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction 必须在 0 到 1 之间")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(values: Sequence[float]) -> dict:
    """描述性统计摘要。键名是 ``formal_timing.py`` 的超集，语义保持一致。"""
    if not values:
        raise ValueError("无法对空序列做统计摘要")
    ordered = sorted(values)
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    p25 = percentile(ordered, 0.25)
    p75 = percentile(ordered, 0.75)
    return {
        "count": len(values),
        "mean_ns": statistics.fmean(values),
        "stddev_ns": deviation,
        "minimum_ns": ordered[0],
        "p05_ns": percentile(ordered, 0.05),
        "p25_ns": p25,
        "p50_ns": percentile(ordered, 0.50),
        "p75_ns": p75,
        "p90_ns": percentile(ordered, 0.90),
        "p95_ns": percentile(ordered, 0.95),
        "p99_ns": percentile(ordered, 0.99),
        "maximum_ns": ordered[-1],
        "range_ns": ordered[-1] - ordered[0],
        "iqr_ns": p75 - p25,
    }


# --------------------------------------------------------------------------
# 概率分布（不完全贝塔函数，Numerical Recipes 的连分式实现）
# --------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    max_iterations = 300
    epsilon = 3e-16
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全贝塔函数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def normal_two_sided_p(z: float) -> float:
    """标准正态分布的双尾 p 值。"""
    return math.erfc(abs(z) / math.sqrt(2.0))


def student_t_two_sided_p(t: float, degrees_of_freedom: float) -> float:
    """t 分布双尾 p 值。``degrees_of_freedom`` 可以是小数（Welch 情形）。"""
    if degrees_of_freedom <= 0:
        raise ValueError("自由度必须为正")
    if math.isinf(t):
        return 0.0
    return _betai(degrees_of_freedom / 2.0, 0.5, degrees_of_freedom / (degrees_of_freedom + t * t))


def student_t_critical(degrees_of_freedom: float, confidence: float = DEFAULT_CONFIDENCE) -> float:
    """双侧临界值，用二分法在 t 分布尾部反解。"""
    if degrees_of_freedom <= 0:
        raise ValueError("自由度必须为正")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence 必须在 0 到 1 之间")
    target = 1.0 - confidence
    low, high = 0.0, 1.0
    while student_t_two_sided_p(high, degrees_of_freedom) > target:
        high *= 2.0
        if high > 1e8:
            return high
    for _ in range(200):
        middle = (low + high) / 2.0
        if student_t_two_sided_p(middle, degrees_of_freedom) > target:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


# --------------------------------------------------------------------------
# 显著性检验
# --------------------------------------------------------------------------


def welch_t_test(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
    confidence: float = DEFAULT_CONFIDENCE,
) -> dict:
    """Welch t 检验，不假设两组方差相等。

    均值差定义为 ``mean(b) - mean(a)``，即「第二组减第一组」，与配对分析里
    「变化后的输入耗时减正常输入耗时」的方向一致。
    """
    if len(sample_a) < 2 or len(sample_b) < 2:
        raise ValueError("Welch t 检验每组至少需要 2 个样本")
    n_a, n_b = len(sample_a), len(sample_b)
    mean_a, mean_b = statistics.fmean(sample_a), statistics.fmean(sample_b)
    var_a, var_b = statistics.variance(sample_a), statistics.variance(sample_b)
    term_a, term_b = var_a / n_a, var_b / n_b
    difference = mean_b - mean_a
    standard_error = math.sqrt(term_a + term_b)
    if standard_error == 0.0:
        statistic = 0.0 if difference == 0.0 else math.inf
        degrees_of_freedom = n_a + n_b - 2
    else:
        statistic = difference / standard_error
        denominator = term_a**2 / (n_a - 1) + term_b**2 / (n_b - 1)
        degrees_of_freedom = (term_a + term_b) ** 2 / denominator if denominator else n_a + n_b - 2
    critical = student_t_critical(degrees_of_freedom, confidence)
    half_width = critical * standard_error
    p_value = student_t_two_sided_p(statistic, degrees_of_freedom)
    return {
        "t_statistic": statistic,
        "degrees_of_freedom": degrees_of_freedom,
        "p_value": p_value,
        "mean_difference_ns": difference,
        "difference_ci_ns": [difference - half_width, difference + half_width],
        "label": f"{confidence * 100:.0f}% 置信区间",
        "critical_value": critical,
        "method": "Welch t 检验（不假设方差相等），均值差为第二组减第一组；区间用 t 分位数",
    }


def ranks_of(values: Sequence[float]) -> list[float]:
    """返回与输入同序的秩（并列取平均秩）。"""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average_rank = (position + end) / 2.0 + 1.0
        for slot in range(position, end + 1):
            ranks[order[slot]] = average_rank
        position = end + 1
    return ranks


def tie_group_sizes(values: Sequence[float]) -> list[int]:
    """返回并列组的大小（只保留大于 1 的组）。"""
    counts: dict[float, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [count for count in counts.values() if count > 1]


def mann_whitney_u(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
    continuity_correction: bool = True,
) -> dict:
    """Mann-Whitney U 检验（正态近似，含并列值修正）。

    ``u_statistic`` 是样本 A 的 U 值，方向与均值差相反（U 小表示 A 的取值偏小）。
    """
    if len(sample_a) < 1 or len(sample_b) < 1:
        raise ValueError("Mann-Whitney U 检验每组至少需要 1 个样本")
    n_a, n_b = len(sample_a), len(sample_b)
    combined = list(sample_a) + list(sample_b)
    ranks = ranks_of(combined)
    rank_sum_a = sum(ranks[:n_a])
    u_a = rank_sum_a - n_a * (n_a + 1) / 2.0
    u_b = n_a * n_b - u_a
    total = n_a + n_b
    expected = n_a * n_b / 2.0

    variance_term = total + 1.0
    ties = tie_group_sizes(combined)
    if ties:
        tie_sum = sum(size**3 - size for size in ties)
        denominator = total * (total - 1)
        variance_term -= tie_sum / denominator if denominator else 0.0
    sigma = math.sqrt(n_a * n_b * variance_term / 12.0)

    if sigma == 0.0:
        z_score = 0.0
        p_value = 1.0
    else:
        deviation = abs(u_a - expected)
        if continuity_correction:
            deviation = max(deviation - 0.5, 0.0)
        z_score = deviation / sigma
        p_value = normal_two_sided_p(z_score)

    smaller = min(u_a, u_b)
    exact = mann_whitney_u_exact(sample_a, sample_b) if not ties and n_a * n_b <= 200 else None
    return {
        "u_statistic": u_a,
        "u_min": smaller,
        "rank_sum_a": rank_sum_a,
        "expected_u": expected,
        "z_statistic": z_score,
        "p_value": p_value,
        "exact_p_value": exact,
        "tie_groups": len(ties),
        "group_sizes": [n_a, n_b],
        "method": (
            "Mann-Whitney U 检验，正态近似"
            + ("（含连续性修正）" if continuity_correction else "")
            + ("，含并列值方差修正" if ties else "，无并列值")
        ),
    }


def mann_whitney_u_exact(sample_a: Sequence[float], sample_b: Sequence[float]) -> float | None:
    """小样本精确双尾 p 值（仅适用于无并列值的情形）。

    用组合枚举计算 U 的精确分布，是最慢也最可靠的对照实现。
    """
    n_a, n_b = len(sample_a), len(sample_b)
    total = n_a + n_b
    if total > 24 or n_a == 0 or n_b == 0:
        return None
    combined = list(sample_a) + list(sample_b)
    if len(set(combined)) != total:
        return None
    ranks = ranks_of(combined)
    observed = sum(ranks[:n_a]) - n_a * (n_a + 1) / 2.0
    expected = n_a * n_b / 2.0
    tolerance = abs(observed - expected)

    extreme = 0
    for selection in combinations(range(total), n_a):
        rank_sum = sum(ranks[index] for index in selection)
        u_value = rank_sum - n_a * (n_a + 1) / 2.0
        if abs(u_value - expected) >= tolerance - 1e-9:
            extreme += 1
    return extreme / math.comb(total, n_a)


def one_sample_t_test(
    values: Sequence[float],
    confidence: float = DEFAULT_CONFIDENCE,
    label: str = "配对差值",
) -> dict:
    """单样本 t 检验：检验 ``values`` 的均值是否显著偏离 0。

    配对设计里正确的检验对象是差值本身，而不是把两类原始计时当独立样本。
    """
    if len(values) < 2:
        raise ValueError("单样本 t 检验至少需要 2 个观测")
    count = len(values)
    mean = statistics.fmean(values)
    standard_error = statistics.stdev(values) / math.sqrt(count)
    degrees_of_freedom = count - 1
    if standard_error == 0.0:
        statistic = 0.0 if mean == 0.0 else math.inf
    else:
        statistic = mean / standard_error
    critical = student_t_critical(degrees_of_freedom, confidence)
    half_width = critical * standard_error
    return {
        "n": count,
        "degrees_of_freedom": degrees_of_freedom,
        "t_statistic": statistic,
        "p_value": student_t_two_sided_p(statistic, degrees_of_freedom),
        "mean_ns": mean,
        "standard_error_ns": standard_error,
        "ci_ns": [mean - half_width, mean + half_width],
        "critical_value": critical,
        "label": label,
        "method": f"单样本 t 检验（{label}是否显著偏离 0），{confidence * 100:.0f}% 区间用 t 分位数",
    }


def wilcoxon_signed_rank(differences: Sequence[float], continuity_correction: bool = True) -> dict:
    """Wilcoxon 符号秩检验（正态近似，含并列值修正与连续性修正）。

    零差值按惯例剔除，并单独记录数量。配对数据的非参数首选。
    """
    nonzero = [value for value in differences if value != 0.0]
    zero_count = len(differences) - len(nonzero)
    count = len(nonzero)
    if count == 0:
        return {
            "w_statistic": 0.0,
            "positive_rank_sum": 0.0,
            "negative_rank_sum": 0.0,
            "expected_w": 0.0,
            "z_statistic": 0.0,
            "p_value": 1.0,
            "nonzero_count": 0,
            "zero_count": zero_count,
            "tie_groups": 0,
            "method": "Wilcoxon 符号秩检验：全部差值均为 0，无法拒绝原假设",
        }
    magnitudes = [abs(value) for value in nonzero]
    ranks = ranks_of(magnitudes)
    positive = sum(rank for rank, value in zip(ranks, nonzero) if value > 0)
    negative = sum(rank for rank, value in zip(ranks, nonzero) if value < 0)
    statistic = min(positive, negative)
    expected = count * (count + 1) / 4.0
    ties = tie_group_sizes(magnitudes)
    tie_sum = sum(size**3 - size for size in ties)
    variance = (count * (count + 1) * (2 * count + 1) - tie_sum / 2.0) / 24.0
    if variance <= 0.0:
        z_score, p_value = 0.0, 1.0
    else:
        deviation = abs(statistic - expected)
        if continuity_correction:
            deviation = max(deviation - 0.5, 0.0)
        z_score = deviation / math.sqrt(variance)
        p_value = normal_two_sided_p(z_score)
    return {
        "w_statistic": statistic,
        "positive_rank_sum": positive,
        "negative_rank_sum": negative,
        "expected_w": expected,
        "z_statistic": z_score,
        "p_value": p_value,
        "nonzero_count": count,
        "zero_count": zero_count,
        "tie_groups": len(ties),
        "method": (
            "Wilcoxon 符号秩检验，正态近似"
            + ("（含连续性修正）" if continuity_correction else "")
            + f"，含并列值方差修正；剔除 {zero_count} 个零差值"
        ),
    }


# --------------------------------------------------------------------------
# 配对分析（沿用 formal_timing.py 的块平衡口径）
# --------------------------------------------------------------------------


def block_estimates_of(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
    orders: Sequence[int],
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> tuple[list[float], list[float]]:
    """把配对序列切成时间块，返回 (逐配对差值, 各块的顺序平衡估计)。

    块估计是配对设计里真正可交换的分析单元：它已经抵消了测量先后顺序的影响。
    """
    if not (len(sample_a) == len(sample_b) == len(orders)):
        raise ValueError("配对分析要求两组样本与顺序标签长度一致")
    differences = [b - a for a, b in zip(sample_a, sample_b)]
    estimates: list[float] = []
    for start in range(0, len(differences) - block_size + 1, block_size):
        block = differences[start : start + block_size]
        block_orders = orders[start : start + block_size]
        first_a = [d for d, order in zip(block, block_orders) if order == 0]
        first_b = [d for d, order in zip(block, block_orders) if order == 1]
        if first_a and first_b:
            estimates.append((statistics.fmean(first_a) + statistics.fmean(first_b)) / 2.0)
    return differences, estimates


def paired_block_analysis(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
    orders: Sequence[int],
    block_size: int = DEFAULT_BLOCK_SIZE,
    min_blocks: int = DEFAULT_MIN_BLOCKS,
    confidence: float = DEFAULT_CONFIDENCE,
) -> dict:
    """配对差值分析：差值定义为 ``b - a``（第二组减第一组）。

    ``orders`` 中 0 表示 a 先测、1 表示 b 先测。每 ``block_size`` 个配对为一个
    时间块，块内分别求两种先后顺序的差值均值再平均，以抵消先后顺序带来的偏移。
    """
    if len(sample_a) < 2:
        raise ValueError("配对分析至少需要 2 个配对")
    differences, block_estimates = block_estimates_of(sample_a, sample_b, orders, block_size)

    unadjusted = statistics.fmean(differences)
    if len(block_estimates) >= min_blocks:
        estimate = statistics.fmean(block_estimates)
        standard_error = statistics.stdev(block_estimates) / math.sqrt(len(block_estimates))
        method = (
            f"每{block_size}组为一个时间块，块内平衡两种执行顺序，"
            f"再对{len(block_estimates)}个块均值计算{confidence * 100:.0f}%正态近似区间"
        )
    else:
        estimate = unadjusted
        standard_error = statistics.stdev(differences) / math.sqrt(len(differences))
        method = (
            f"时间块不足{min_blocks}个，仅使用逐组配对均值的"
            f"{confidence * 100:.0f}%正态近似区间"
        )

    z_value = PAIRED_Z_95 if confidence == 0.95 else student_t_critical(10**6, confidence)
    half_width = z_value * standard_error
    lower, upper = estimate - half_width, estimate + half_width

    # 配对设计的正确检验对象是块估计（块数足够时），而不是两类原始计时。
    units = block_estimates if len(block_estimates) >= min_blocks else differences
    unit_label = "时间块均值" if units is block_estimates else "逐配对差值"
    difference_t = one_sample_t_test(units, confidence, unit_label) if len(units) >= 2 else None
    difference_w = wilcoxon_signed_rank(units)

    return {
        "paired_count": len(differences),
        "paired_mean_difference_ns": estimate,
        "unadjusted_paired_mean_difference_ns": unadjusted,
        "paired_difference_ci_ns": [lower, upper],
        "paired_standard_error_ns": standard_error,
        "paired_z_statistic": estimate / standard_error if standard_error else None,
        "statistically_distinguishable": lower > 0 or upper < 0,
        "block_count": len(block_estimates),
        "first_a_count": sum(1 for order in orders if order == 0),
        "first_b_count": sum(1 for order in orders if order == 1),
        "analysis_unit": unit_label,
        "analysis_unit_count": len(units),
        "difference_t_test": difference_t,
        "difference_wilcoxon": difference_w,
        "method": method + "；不删除异常值；单轮结果仅具探索性，应检查重复实验的一致性",
    }


# --------------------------------------------------------------------------
# 组合分析与自动结论
# --------------------------------------------------------------------------


def compare_two_classes(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
    orders: Sequence[int] | None = None,
    block_size: int = DEFAULT_BLOCK_SIZE,
    min_blocks: int = DEFAULT_MIN_BLOCKS,
    alpha: float = DEFAULT_ALPHA,
    confidence: float = DEFAULT_CONFIDENCE,
    relevance_percent: float = DEFAULT_RELEVANCE_PERCENT,
    label_a: str = "正常输入",
    label_b: str = "变化后的输入",
) -> dict:
    """对两类输入做完整对比：描述统计 + 两个检验 + 配对分析 + 自动结论。"""
    if len(sample_a) < 2 or len(sample_b) < 2:
        raise ValueError("两类对比每组至少需要 2 个样本")
    summary_a, summary_b = summarize(sample_a), summarize(sample_b)
    welch = welch_t_test(sample_a, sample_b, confidence)
    mann = mann_whitney_u(sample_a, sample_b)
    paired = (
        paired_block_analysis(sample_a, sample_b, orders, block_size, min_blocks, confidence)
        if orders is not None
        else None
    )

    welch_significant = welch["p_value"] < alpha
    mann_significant = mann["p_value"] < alpha
    independent_significant = welch_significant and mann_significant
    raw_difference = summary_b["mean_ns"] - summary_a["mean_ns"]

    if paired is not None:
        # 配对设计：以块平衡后的配对检验为准。独立样本检验忽略配对，
        # 会把"测量先后顺序造成的位移"误当成类别差异，只能作为参考。
        difference_t = paired["difference_t_test"]
        difference_w = paired["difference_wilcoxon"]
        t_significant = difference_t is not None and difference_t["p_value"] < alpha
        w_significant = difference_w["p_value"] < alpha
        primary_significant = t_significant and w_significant
        agreement = t_significant == w_significant
        mean_difference = paired["paired_mean_difference_ns"]
        primary_label = f"配对单样本 t 检验（{paired['analysis_unit']}）与 Wilcoxon 符号秩检验"
    else:
        primary_significant = independent_significant
        agreement = welch_significant == mann_significant
        mean_difference = raw_difference
        primary_label = "Welch t 检验与 Mann-Whitney U 检验"

    relative = 100.0 * mean_difference / summary_a["mean_ns"] if summary_a["mean_ns"] else None
    practically_relevant = relative is not None and abs(relative) >= relevance_percent

    conflict = paired is not None and primary_significant != independent_significant

    if not agreement:
        verdict_text = (
            f"两个主检验结论不一致：{primary_label}。"
            f"这通常说明分布形状或离群值对结论影响较大，应增大样本量或重复多轮实验后再判断。"
        )
    elif primary_significant:
        verdict_text = (
            f"主检验（{primary_label}）在 α={alpha} 下判为存在差异，"
            f"均值差 {mean_difference:.2f} ns（相对 {relative:.2f}%）。"
            + (
                "已达到设定的实际意义阈值。"
                if practically_relevant
                else f"但相对差异小于 {relevance_percent}%，"
                "是否具有实际意义需要结合攻击可行性和重复轮次判断。"
            )
        )
    else:
        verdict_text = (
            f"主检验（{primary_label}）在 α={alpha} 下没有判出差异，"
            f"均值差 {mean_difference:.2f} ns。"
            f"未观察到差异不能证明实现绝对恒定时间，只说明在本次环境、样本量和输入类别下没测出来。"
        )

    if conflict:
        verdict_text += (
            f" 注意：把同一批配对数据当作独立样本时结论相反"
            f"（Welch p={welch['p_value']:.4g}，Mann-Whitney p={mann['p_value']:.4g}），"
            f"这是测量先后顺序偏移被误当成类别差异所致，不应采用独立样本检验的结论。"
        )

    caveats = [
        "原始计时全部保留，未做事后异常值剔除。",
        "单轮结果仅具探索性，应检查独立重复轮次的方向与大小是否一致。",
        "未观察到差异不能证明实现绝对恒定时间。",
        "统计显著不等于实际可利用；判断泄露可行性还要看差异幅度、样本量和攻击者能力。",
    ]
    if paired is not None:
        caveats.append(
            "配对数据的正确检验对象是块平衡后的差值；"
            "Welch 与 Mann-Whitney 忽略配对，仅作独立样本参考，不参与判定。"
        )
        caveats.append(
            "未做顺序平衡的原始均值差受测量先后顺序影响，"
            f"本次未平衡估计为 {paired['unadjusted_paired_mean_difference_ns']:.2f} ns，"
            f"平衡后为 {mean_difference:.2f} ns。"
        )

    return {
        "label_a": label_a,
        "label_b": label_b,
        "class_a": summary_a,
        "class_b": summary_b,
        "mean_difference_ns": mean_difference,
        "raw_mean_difference_ns": raw_difference,
        "relative_mean_difference_percent": relative,
        "welch": welch,
        "mann_whitney": mann,
        "paired": paired,
        "verdict": {
            "primary_test": "paired_difference_tests" if paired is not None else "welch_and_mann_whitney",
            "primary_label": primary_label,
            "alpha": alpha,
            "welch_significant": welch_significant,
            "mann_whitney_significant": mann_significant,
            "independent_sample_significant": independent_significant,
            "tests_agree": agreement,
            "independent_sample_conflicts_with_paired": conflict,
            "statistically_significant": primary_significant,
            "practically_relevant": practically_relevant,
            "relevance_threshold_percent": relevance_percent,
            "text": verdict_text,
        },
        "caveats": caveats,
    }


# --------------------------------------------------------------------------
# 读取计时数据
# --------------------------------------------------------------------------


def load_paired_csv(
    path: str | Path,
    a_column: str = "valid_ns",
    b_column: str = "changed_ns",
    order_column: str = "order",
) -> dict:
    """读取 ``formal_timing.py`` / ``formal_timing.c`` 产出的配对 CSV。"""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"找不到计时数据文件：{source}")
    samples_a: list[float] = []
    samples_b: list[float] = []
    orders: list[int] = []
    with source.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"计时数据文件没有表头：{source}")
        missing = [name for name in (a_column, b_column) if name not in reader.fieldnames]
        if missing:
            raise ValueError(
                f"缺少列 {', '.join(missing)}；文件可用列为 {', '.join(reader.fieldnames)}"
            )
        has_order = order_column in reader.fieldnames
        for row in reader:
            samples_a.append(float(row[a_column]))
            samples_b.append(float(row[b_column]))
            orders.append(int(row[order_column]) if has_order else len(orders) % 2)
    if not samples_a:
        raise ValueError(f"计时数据文件没有数据行：{source}")
    return {
        "source": str(source),
        "column_a": a_column,
        "column_b": b_column,
        "order_column": order_column if has_order else None,
        "samples_a": samples_a,
        "samples_b": samples_b,
        "orders": orders,
    }


def analyze_file(
    path: str | Path,
    a_column: str = "valid_ns",
    b_column: str = "changed_ns",
    order_column: str = "order",
    block_size: int = DEFAULT_BLOCK_SIZE,
    alpha: float = DEFAULT_ALPHA,
) -> dict:
    """读取 CSV 并返回完整分析结果（可直接序列化为 JSON）。"""
    data = load_paired_csv(path, a_column, b_column, order_column)
    if len(data["samples_a"]) < MIN_PAIRS:
        raise ValueError(
            f"有效配对数据不足{MIN_PAIRS}组（实际{len(data['samples_a'])}组），不输出统计结论"
        )
    analysis = compare_two_classes(
        data["samples_a"],
        data["samples_b"],
        orders=data["orders"],
        block_size=block_size,
        alpha=alpha,
    )
    analysis["source"] = data["source"]
    analysis["columns"] = {
        "a": data["column_a"],
        "b": data["column_b"],
        "order": data["order_column"],
    }
    return analysis


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ML-KEM 解封装时间配对数据的统计分析（纯标准库）",
    )
    parser.add_argument("csv", help="配对计时 CSV，例如 results/timing/<run_id>.csv")
    parser.add_argument("--a-column", default="valid_ns", help="第一组耗时列名，默认 valid_ns")
    parser.add_argument("--b-column", default="changed_ns", help="第二组耗时列名，默认 changed_ns")
    parser.add_argument("--order-column", default="order", help="先后顺序列名，默认 order")
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE, help="配对时间块大小")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA, help="显著性水平，默认 0.05")
    parser.add_argument("--output", help="同时把结果写入该 JSON 文件")
    return parser


def _force_utf8_output() -> None:
    """把标准输出与标准错误固定为 UTF-8。

    本模块的输出含中文。若不固定编码，在 locale 为 GBK 的 Windows 上，
    调用方用管道读取时解码会失败（subprocess 的读取线程会抛
    UnicodeDecodeError，使 stderr 变成 None），因此不能依赖本机 locale。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: Iterable[str] | None = None) -> int:
    _force_utf8_output()
    arguments = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        analysis = analyze_file(
            arguments.csv,
            arguments.a_column,
            arguments.b_column,
            arguments.order_column,
            arguments.block_size,
            arguments.alpha,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    text = json.dumps(analysis, ensure_ascii=False, indent=2)
    if arguments.output:
        Path(arguments.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
