#define _POSIX_C_SOURCE 200809L
#include <dlfcn.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef int (*keypair_fn)(uint8_t *, uint8_t *);
typedef int (*enc_fn)(uint8_t *, uint8_t *, const uint8_t *);
typedef int (*dec_fn)(uint8_t *, const uint8_t *, const uint8_t *);
#define SAMPLE_COUNT 32

static uint64_t ticks(void) {
  struct timespec t;
#ifdef CLOCK_MONOTONIC_RAW
  if (clock_gettime(CLOCK_MONOTONIC_RAW, &t) != 0) { perror("clock_gettime"); exit(2); }
#else
  if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) { perror("clock_gettime"); exit(2); }
#endif
  return (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
}

static uint32_t next_random(uint32_t *state) {
  uint32_t x = *state;
  x ^= x << 13; x ^= x >> 17; x ^= x << 5;
  return *state = x;
}

static void *load_symbol(void *handle, const char *name) {
  void *symbol = dlsym(handle, name);
  if (!symbol) { fprintf(stderr, "missing symbol %s: %s\n", name, dlerror()); exit(2); }
  return symbol;
}

static uint64_t measure(dec_fn dec, uint8_t *out, const uint8_t *ct,
                        const uint8_t *sk) {
  const uint64_t before = ticks();
  int rc = dec(out, ct, sk);
  const uint64_t after = ticks();
  if (rc != 0) { fprintf(stderr, "decapsulation failed: %d\n", rc); exit(2); }
  return after - before;
}

int main(int argc, char **argv) {
  if (argc != 5) {
    fprintf(stderr, "usage: %s LIBRARY LEVEL PAIRS OUTPUT.csv\n", argv[0]);
    return 2;
  }
  const int level = atoi(argv[2]);
  size_t pk_len, sk_len, ct_len;
  switch (level) {
    case 512: pk_len=800; sk_len=1632; ct_len=768; break;
    case 768: pk_len=1184; sk_len=2400; ct_len=1088; break;
    case 1024: pk_len=1568; sk_len=3168; ct_len=1568; break;
    default: fprintf(stderr, "unsupported level\n"); return 2;
  }
  char *end = NULL;
  unsigned long pairs = strtoul(argv[3], &end, 10);
  if (!end || *end || pairs < 100 || pairs > 1000000) {
    fprintf(stderr, "PAIRS must be between 100 and 1000000\n"); return 2;
  }
  void *handle = dlopen(argv[1], RTLD_NOW);
  if (!handle) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 2; }
  keypair_fn keypair = (keypair_fn)load_symbol(handle, "mlkem_keypair");
  enc_fn enc = (enc_fn)load_symbol(handle, "mlkem_enc");
  dec_fn dec = (dec_fn)load_symbol(handle, "mlkem_dec");
  uint8_t *pk=malloc(pk_len), *sk=malloc(sk_len);
  uint8_t *valid=malloc(SAMPLE_COUNT * ct_len);
  uint8_t *changed=malloc(SAMPLE_COUNT * ct_len);
  uint8_t expected[32], actual[32];
  if (!pk || !sk || !valid || !changed) { perror("malloc"); return 2; }
  if (keypair(pk, sk)) { fprintf(stderr, "setup failed\n"); return 2; }
  for (size_t j=0; j<SAMPLE_COUNT; j++) {
    uint8_t *a = valid + j * ct_len;
    uint8_t *b = changed + j * ct_len;
    if (enc(a, expected, pk)) { fprintf(stderr, "encapsulation failed\n"); return 2; }
    memcpy(b, a, ct_len);
    b[ct_len / 2] ^= 1;
    if (dec(actual, a, sk) || memcmp(expected, actual, 32) != 0) {
      fprintf(stderr, "valid input self-check failed\n"); return 2;
    }
    if (dec(actual, b, sk) || memcmp(expected, actual, 32) == 0) {
      fprintf(stderr, "changed input self-check failed\n"); return 2;
    }
  }
  for (int i=0; i<2000; i++) {
    size_t j = (size_t)i % SAMPLE_COUNT;
    dec(actual, valid + j * ct_len, sk);
    dec(actual, changed + j * ct_len, sk);
  }
  FILE *out = fopen(argv[4], "w");
  if (!out) { perror("fopen"); return 2; }
  fputs("pair,sample,order,valid_ns,changed_ns\n", out);
  uint32_t random_state = 0x6d2b79f5U;
  for (unsigned long i=0; i<pairs; i++) {
    uint64_t a, b;
    size_t sample = (size_t)i % SAMPLE_COUNT;
    const uint8_t *valid_sample = valid + sample * ct_len;
    const uint8_t *changed_sample = changed + sample * ct_len;
    unsigned order = next_random(&random_state) & 1U;
    if (order == 0) {
      a = measure(dec, actual, valid_sample, sk);
      b = measure(dec, actual, changed_sample, sk);
    } else {
      b = measure(dec, actual, changed_sample, sk);
      a = measure(dec, actual, valid_sample, sk);
    }
    fprintf(out, "%lu,%zu,%u,%" PRIu64 ",%" PRIu64 "\n", i, sample, order, a, b);
  }
  if (fclose(out) != 0) { perror("fclose"); return 2; }
  memset(sk, 0, sk_len);
  free(pk); free(sk); free(valid); free(changed);
  dlclose(handle);
  return 0;
}

