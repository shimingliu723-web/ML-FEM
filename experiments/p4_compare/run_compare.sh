#!/usr/bin/env bash
# P4 三组对照复测：三个目标轮转交叉采样。
#
# 为什么轮转：如果把一个目标一次性跑完再跑下一个，两次采样之间发生的频率、
# 温度或负载漂移会全部算到目标之间的差异上。轮转交叉可以让漂移均摊。
#
# 用法：
#   bash experiments/p4_compare/run_compare.sh [项目根目录]
# 不传参数时，取本脚本所在位置的上两级目录作为项目根。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
cd "$BASE" || { echo "找不到项目根目录：$BASE"; exit 1; }

BIN=./experiments/formal_timing
OUT=results/p4_compare
ROUNDS="${P4_ROUNDS:-5}"
PAIRS="${P4_PAIRS:-20000}"
CPU="${P4_CPU:-0}"
TARGETS="mlkem_native_baseline variant_early_return variant_fixed"

# 注意：基线目标没有自己的 targets/<id>/lib/ 目录，它的库就是平台构建的那份。
library_for() {
    case "$1" in
        mlkem_native_baseline) echo "backend/lib/libmlkem512.so" ;;
        *) echo "targets/$1/lib/libmlkem512.so" ;;
    esac
}

if [ ! -x "$BIN" ]; then
    echo "找不到可执行的计时程序：$BIN（先 make all formal-timing）"
    exit 1
fi

mkdir -p "$OUT"
rm -f "$OUT"/*.csv "$OUT"/env.txt

{
    echo "时间: $(date -Is)"
    echo "主机: $(hostname)"
    echo "内核: $(uname -r)"
    echo "CPU: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
    echo "固定 CPU 核: $CPU"
    echo "频率策略: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo 未知)"
    echo "轮数: $ROUNDS"
    echo "每轮配对数: $PAIRS"
    echo "采样顺序: 三个目标轮转交叉"
    echo "负载: $(uptime)"
} > "$OUT/env.txt"

failed=0
for round in $(seq 1 "$ROUNDS"); do
    for target in $TARGETS; do
        lib="$(library_for "$target")"
        csv="$OUT/${target}-r${round}.csv"
        if [ ! -f "$lib" ]; then
            printf 'r%s %-24s 缺少库 %s\n' "$round" "$target" "$lib"
            failed=$((failed + 1))
            continue
        fi
        if taskset -c "$CPU" "$BIN" "$lib" 512 "$PAIRS" "$csv" >/dev/null 2>&1; then
            printf 'r%s %-24s 完成 %s 行\n' "$round" "$target" "$(wc -l < "$csv")"
        else
            printf 'r%s %-24s 失败\n' "$round" "$target"
            failed=$((failed + 1))
        fi
    done
done

echo
if [ "$failed" -eq 0 ]; then
    echo "全部完成，共 $((ROUNDS * 3)) 轮，数据在 $OUT/"
else
    echo "有 $failed 轮失败"
    exit 1
fi
