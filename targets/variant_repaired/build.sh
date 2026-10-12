#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_DIR="$PROJECT_DIR/targets/variant_repaired"
mkdir -p "$TARGET_DIR/lib"
CC="${CC:-gcc}"
MLKEM_DIR="$TARGET_DIR/src/mlkem"
COMMON_FLAGS="-O3 -fPIC -std=c99 -Wall -Wextra -Wpedantic -I$MLKEM_DIR -DMLK_CONFIG_NAMESPACE_PREFIX=mlkem"
for level in 512 768 1024; do
  "$CC" $COMMON_FLAGS -DMLK_CONFIG_PARAMETER_SET=$level -shared \
    "$MLKEM_DIR/mlkem_native.c" "$TARGET_DIR/src/randombytes.c" \
    -o "$TARGET_DIR/lib/libmlkem${level}.so"
done
