CC ?= gcc
PROJECT_ROOT := $(abspath .)
MLKEM_DIR := $(PROJECT_ROOT)/core/mlkem-native/mlkem
LIB_DIR := $(PROJECT_ROOT)/backend/lib
COMMON_FLAGS := -O3 -fPIC -std=c99 -Wall -Wextra -Wpedantic \
	-I$(MLKEM_DIR) -DMLK_CONFIG_NAMESPACE_PREFIX=mlkem
SOURCE := $(MLKEM_DIR)/mlkem_native.c $(PROJECT_ROOT)/core/randombytes.c

.PHONY: all clean formal-timing

all: $(LIB_DIR)/libmlkem512.so $(LIB_DIR)/libmlkem768.so $(LIB_DIR)/libmlkem1024.so

formal-timing: $(PROJECT_ROOT)/experiments/formal_timing

$(PROJECT_ROOT)/experiments/formal_timing: $(PROJECT_ROOT)/experiments/formal_timing.c
	$(CC) -O3 -std=c11 -Wall -Wextra -Wpedantic $< -o $@ -ldl

$(LIB_DIR):
	mkdir -p $@

$(LIB_DIR)/libmlkem512.so: $(SOURCE) | $(LIB_DIR)
	$(CC) $(COMMON_FLAGS) -DMLK_CONFIG_PARAMETER_SET=512 -shared $(SOURCE) -o $@

$(LIB_DIR)/libmlkem768.so: $(SOURCE) | $(LIB_DIR)
	$(CC) $(COMMON_FLAGS) -DMLK_CONFIG_PARAMETER_SET=768 -shared $(SOURCE) -o $@

$(LIB_DIR)/libmlkem1024.so: $(SOURCE) | $(LIB_DIR)
	$(CC) $(COMMON_FLAGS) -DMLK_CONFIG_PARAMETER_SET=1024 -shared $(SOURCE) -o $@

clean:
	rm -f $(LIB_DIR)/libmlkem512.so $(LIB_DIR)/libmlkem768.so $(LIB_DIR)/libmlkem1024.so
	rm -f $(PROJECT_ROOT)/experiments/formal_timing

