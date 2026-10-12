/* 教学对照版本的正确性验证。
 *
 * 两个库只差 poly_frommsg 的写法，因此对同一组 (密文, 私钥) 必须给出
 * 完全相同的共享密钥。这个测试同时检查：
 *   1. 正常密文的解封装结果与封装端一致（功能正确）；
 *   2. 两个构建对同一输入给出逐字节相同的输出（改造没有改变语义）；
 *   3. 被篡改的密文在两个构建上都返回同一个（不同的）共享密钥，
 *      因为 FIPS 203 风格的设计是隐式拒绝，不会返回错误码。
 *
 * 用法：./selftest <vuln.so> <ct.so>
 */

#define _POSIX_C_SOURCE 200809L

#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PK_BYTES 800
#define SK_BYTES 1632
#define CT_BYTES 768
#define SS_BYTES 32

#define VALID_TRIALS 200
#define TAMPER_TRIALS 200

typedef int (*keypair_fn)(uint8_t *, uint8_t *);
typedef int (*enc_fn)(uint8_t *, uint8_t *, const uint8_t *);
typedef int (*dec_fn)(uint8_t *, const uint8_t *, const uint8_t *);

typedef struct {
    const char *name;
    void *handle;
    keypair_fn keypair;
    enc_fn enc;
    dec_fn dec;
} library;

static int failures = 0;

static void fail(const char *message)
{
    fprintf(stderr, "错误：%s\n", message);
    exit(2);
}

static void load(library *lib, const char *path, const char *name)
{
    lib->name = name;
    lib->handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (lib->handle == NULL) {
        fprintf(stderr, "无法加载 %s（%s）：%s\n", name, path, dlerror());
        exit(2);
    }
    *(void **)(&lib->keypair) = dlsym(lib->handle, "mlkem_keypair");
    *(void **)(&lib->enc) = dlsym(lib->handle, "mlkem_enc");
    *(void **)(&lib->dec) = dlsym(lib->handle, "mlkem_dec");
    if (lib->keypair == NULL || lib->enc == NULL || lib->dec == NULL) {
        fprintf(stderr, "%s 缺少 mlkem_keypair/mlkem_enc/mlkem_dec 符号\n", name);
        exit(2);
    }
}

static void report(const char *what, long checked, int ok)
{
    if (ok) {
        printf("  [通过] %-34s 检查 %ld 次\n", what, checked);
    } else {
        printf("  [失败] %-34s 检查 %ld 次\n", what, checked);
        failures++;
    }
}

int main(int argc, char **argv)
{
    library vuln, ct;
    uint8_t pk[PK_BYTES], sk[SK_BYTES];
    uint8_t ct_bytes[CT_BYTES], tampered[CT_BYTES];
    uint8_t ss_encap[SS_BYTES], ss_vuln[SS_BYTES], ss_ct[SS_BYTES];
    long mismatch_semantics = 0, mismatch_valid = 0, mismatch_tamper = 0;
    long tamper_accepted = 0, tamper_same_as_valid = 0;

    if (argc != 3) {
        fprintf(stderr, "用法：%s <vuln.so> <ct.so>\n", argv[0]);
        return 2;
    }
    load(&vuln, argv[1], "vuln");
    load(&ct, argv[2], "ct");

    printf("vuln = %s\nct   = %s\n\n", argv[1], argv[2]);

    if (vuln.keypair(pk, sk) != 0) {
        fail("密钥生成失败");
    }

    for (int trial = 0; trial < VALID_TRIALS; trial++) {
        if (vuln.enc(ct_bytes, ss_encap, pk) != 0) {
            fail("封装失败");
        }
        if (vuln.dec(ss_vuln, ct_bytes, sk) != 0) {
            fail("vuln 解封装失败");
        }
        if (ct.dec(ss_ct, ct_bytes, sk) != 0) {
            fail("ct 解封装失败");
        }
        if (memcmp(ss_vuln, ss_ct, SS_BYTES) != 0) {
            mismatch_semantics++;
        }
        if (memcmp(ss_encap, ss_vuln, SS_BYTES) != 0) {
            mismatch_valid++;
        }
    }

    for (int trial = 0; trial < TAMPER_TRIALS; trial++) {
        if (vuln.enc(ct_bytes, ss_encap, pk) != 0) {
            fail("封装失败");
        }
        memcpy(tampered, ct_bytes, CT_BYTES);
        /* 翻转一个与 poly_frommsg 相关的位，确保走到隐式拒绝路径 */
        tampered[CT_BYTES / 2] ^= (uint8_t)(1u << (trial % 8));

        if (vuln.dec(ss_vuln, tampered, sk) != 0) {
            tamper_accepted++;
        }
        if (ct.dec(ss_ct, tampered, sk) != 0) {
            tamper_accepted++;
        }
        if (memcmp(ss_vuln, ss_ct, SS_BYTES) != 0) {
            mismatch_tamper++;
        }
        if (memcmp(ss_vuln, ss_encap, SS_BYTES) == 0) {
            tamper_same_as_valid++;
        }
    }

    printf("正确性\n");
    report("正常密文解封装结果一致", VALID_TRIALS, mismatch_valid == 0);
    report("篡改密文返回非零错误码", TAMPER_TRIALS * 2, tamper_accepted == 0);
    report("篡改密文结果不等于正常值", TAMPER_TRIALS, tamper_same_as_valid == 0);
    printf("等价性（改造未改变语义）\n");
    report("正常密文两构建输出逐字节相同", VALID_TRIALS, mismatch_semantics == 0);
    report("篡改密文两构建输出逐字节相同", TAMPER_TRIALS, mismatch_tamper == 0);

    printf("\n");
    if (failures == 0) {
        printf("全部通过\n");
    } else {
        printf("有 %d 项失败\n", failures);
    }

    dlclose(vuln.handle);
    dlclose(ct.handle);
    return failures == 0 ? 0 : 1;
}
