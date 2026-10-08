# 教学对照版本：同一份 Kyber-512 参考实现的两个构建。
#
#   vuln = 原样编译（-Os）。Clang 会把 poly_frommsg 里源码级的掩码运算
#          降低成 bt + jae 的秘密相关分支。
#   ct   = 只把该函数内的字节读取提到内层循环之外，语义不变，
#          但 Clang 会改为把内层 8 次迭代整体向量化成无分支代码。
#
# 两个库导出相同的 mlkem_keypair / mlkem_enc / mlkem_dec 符号，
# 因此可以直接配合 experiments/formal_timing.c 和 backend/stats.py 使用，
# 只需换一个 .so 路径。
#
# 警告：这是 Kyber 第三轮参考实现，不是 FIPS 203 的 ML-KEM。
# 它明确标注为教学对照，与平台正式使用的 core/mlkem-native 完全分离，
# 其测量结果不得当作 mlkem-native 的结论。
#
# 本 Makefile 刻意只使用相对路径作为目标名（make 无法处理含空格的目标名），
# 因此即使仓库放在含空格的路径下也能构建。

SHELL := /bin/bash

CC := clang
REF := ../clangover-poc/kyber/ref
BUILD := build

# 必须用 clang。这里不能写 CC ?= clang：make 内建了 CC = cc 的默认值，
# ?= 永远不会生效，结果会用 gcc 构建。而本漏洞是 Clang 特有的——
# 同一份源码用 GCC 编译时 poly_frommsg 保持无分支，只有 Clang 会在
# -Os/-O1 下引入秘密相关跳转。用 gcc 构建会得到一个"看起来无泄露"的
# 对照版，导致复测结论完全反过来。
# 仍可用 make CC=gcc 临时覆盖，以便做编译器对比。

REF_SOURCES := kex.c kem.c indcpa.c polyvec.c poly.c ntt.c cbd.c reduce.c \
               verify.c fips202.c symmetric-shake.c randombytes.c

REF_CFLAGS := -Wall -Wextra -Wpedantic -Wmissing-prototypes -Wredundant-decls \
              -Wshadow -Wpointer-arith -Os -fomit-frame-pointer -fPIC -DKYBER_K=2
SHIM_CFLAGS := -Wall -Wextra -Os -fPIC -DKYBER_K=2
TEST_CFLAGS := -Wall -Wextra -Os

VULN_OBJS := $(patsubst %.c,$(BUILD)/vuln/%.o,$(REF_SOURCES))
CT_OBJS := $(patsubst %.c,$(BUILD)/ct/%.o,$(REF_SOURCES))
VULN_SOURCES := $(patsubst %.c,$(BUILD)/vuln/%.c,$(REF_SOURCES))
CT_SOURCES := $(patsubst %.c,$(BUILD)/ct/%.c,$(REF_SOURCES))
VULN_LIB := $(BUILD)/libkyber512_teach_vuln.so
CT_LIB := $(BUILD)/libkyber512_teach_ct.so
FROMMSG := pqcrystals_kyber512_ref_poly_frommsg

# make 默认会把“中间产物”删掉，其中就包括改造后的 poly.c。
# 那份源码本身是改造的审计证据，必须留在磁盘上供人工核对。
.SECONDARY: $(VULN_SOURCES) $(CT_SOURCES)

.PHONY: all test disasm clean help

all: $(VULN_LIB) $(CT_LIB)

help:
	@echo "make all     构建 vuln 与 ct 两个教学对照库"
	@echo "make test    验证两个库功能正确且互相等价"
	@echo "make disasm  反汇编 poly_frommsg，给出秘密相关分支的证据"
	@echo "make clean   清理构建产物"

# ---------------------------------------------------------------- 源码副本
# make 的目标名不能含空格，所以统一复制到相对路径 build/<variant>/ 下再编译。
$(BUILD)/vuln/%.c:
	@mkdir -p $(@D)
	cp $(REF)/$*.c $@

$(BUILD)/ct/%.c:
	@mkdir -p $(@D)
	cp $(REF)/$*.c $@

# 改造版只覆盖 poly.c，其余源码与 vuln 完全相同。
$(BUILD)/ct/poly.c: $(BUILD)/vuln/poly.c apply_ct_patch.py
	@mkdir -p $(@D)
	python3 apply_ct_patch.py $< $@

# ---------------------------------------------------------------- 目标文件
$(BUILD)/vuln/%.o: $(BUILD)/vuln/%.c
	$(CC) $(REF_CFLAGS) -I$(REF) -I$(BUILD)/vuln -c $< -o $@

$(BUILD)/ct/%.o: $(BUILD)/ct/%.c
	$(CC) $(REF_CFLAGS) -I$(REF) -I$(BUILD)/ct -c $< -o $@

$(BUILD)/vuln/shim.o: shim.c
	@mkdir -p $(@D)
	$(CC) $(SHIM_CFLAGS) -I$(REF) -c $< -o $@

$(BUILD)/ct/shim.o: shim.c
	@mkdir -p $(@D)
	$(CC) $(SHIM_CFLAGS) -I$(REF) -c $< -o $@

# ---------------------------------------------------------------- 链接
$(VULN_LIB): $(VULN_OBJS) $(BUILD)/vuln/shim.o
	$(CC) -shared -o $@ $^

$(CT_LIB): $(CT_OBJS) $(BUILD)/ct/shim.o
	$(CC) -shared -o $@ $^

$(BUILD)/selftest: selftest.c
	@mkdir -p $(@D)
	$(CC) $(TEST_CFLAGS) $< -o $@ -ldl

# ---------------------------------------------------------------- 验证
test: all $(BUILD)/selftest
	./$(BUILD)/selftest ./$(VULN_LIB) ./$(CT_LIB)

# 直接给出题目要求 5（泄露定位）需要的证据：
# poly_frommsg 在 vuln 版里含秘密相关分支，在 ct 版里没有。
disasm: all
	@echo "编译器: $$($(CC) --version | head -1)"
	@echo "（用 gcc 构建时 poly_frommsg 不会出现秘密相关分支，"
	@echo "  这正是该漏洞被称为 ClangOver 的原因）"
	@echo
	@for variant in vuln ct; do \
	    echo "===== $$variant ====="; \
	    objdump -d $(BUILD)/$$variant/poly.o \
	        | awk '/<$(FROMMSG)>:/,/^$$/' | sed 's/^/  /'; \
	    total=$$(objdump -d $(BUILD)/$$variant/poly.o \
	        | awk '/<$(FROMMSG)>:/,/^$$/' | grep -cE '\bj[a-z]+\b'); \
	    secret=$$(objdump -d $(BUILD)/$$variant/poly.o \
	        | awk '/<$(FROMMSG)>:/,/^$$/' | grep -A1 -E '\b(bt|test)\b' \
	        | grep -cE '\bj[a-z]+\b'); \
	    echo "  --> 总分支 $$total 个，秘密相关分支 $$secret 个"; \
	    echo; \
	done

clean:
	rm -rf $(BUILD)
