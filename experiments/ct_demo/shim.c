/* 统一入口：让教学对照库与平台的 libmlkem{N}.so 具有相同的符号名，
 * 这样已有的计时采集程序（experiments/formal_timing.c）和统计模块
 * 都能不加修改地直接使用，只要换一个 .so 路径。
 *
 * 注意：Kyber-512 的 pk/sk/ct 长度（800/1632/768）与 ML-KEM-512 相同，
 * 但这是 Kyber 第三轮版本，不是 FIPS 203 的 ML-KEM，仅作教学对照使用。
 */

#include <stdint.h>

#include "api.h"

int mlkem_keypair(uint8_t *pk, uint8_t *sk);
int mlkem_enc(uint8_t *ct, uint8_t *ss, const uint8_t *pk);
int mlkem_dec(uint8_t *ss, const uint8_t *ct, const uint8_t *sk);

int mlkem_keypair(uint8_t *pk, uint8_t *sk)
{
    return pqcrystals_kyber512_ref_keypair(pk, sk);
}

int mlkem_enc(uint8_t *ct, uint8_t *ss, const uint8_t *pk)
{
    return pqcrystals_kyber512_ref_enc(ct, ss, pk);
}

int mlkem_dec(uint8_t *ss, const uint8_t *ct, const uint8_t *sk)
{
    return pqcrystals_kyber512_ref_dec(ss, ct, sk);
}
