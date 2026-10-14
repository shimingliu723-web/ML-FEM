#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_DIR="$PROJECT_DIR/targets/case_variable_division"
mkdir -p "$TARGET_DIR/lib"
CC="${CC:-gcc}"
COMMON_FLAGS="-Os -fPIC -std=c99 -Wall -Wextra -Wpedantic -I$TARGET_DIR/src/mlkem -DMLK_CONFIG_NAMESPACE_PREFIX=mlkem"
for level in 512 768 1024; do
 "$CC" $COMMON_FLAGS -DMLK_CONFIG_PARAMETER_SET=$level -shared "$TARGET_DIR/src/mlkem/mlkem_native.c" "$TARGET_DIR/src/randombytes.c" -o "$TARGET_DIR/lib/libmlkem${level}.so"
done
