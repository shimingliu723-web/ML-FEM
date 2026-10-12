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

enum { CLASS_COUNT = 4 };

static const char *CLASS_NAMES[CLASS_COUNT] = {
    "normal",
    "changed_first",
    "changed_mid",
    "changed_last",
};

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
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  return *state = x;
}

static void *load_symbol(void *handle, const char *name) {
  void *symbol = dlsym(handle, name);
  if (!symbol) {
    fprintf(stderr, "missing symbol %s: %s\n", name, dlerror());
    exit(2);
  }
  return symbol;
}

static uint64_t measure(dec_fn dec, uint8_t *out, const uint8_t *ct,
                        const uint8_t *sk) {
  const uint64_t before = ticks();
  int rc = dec(out, ct, sk);
  const uint64_t after = ticks();
  if (rc != 0) {
    fprintf(stderr, "decapsulation failed: %d\n", rc);
    exit(2);
  }
  return after - before;
}

int main(int argc, char **argv) {
  if (argc != 6) {
    fprintf(stderr, "usage: %s LIBRARY LEVEL SAMPLES REPEATS OUTPUT.csv\n", argv[0]);
    return 2;
  }
  const int level = atoi(argv[2]);
  size_t pk_len, sk_len, ct_len;
  switch (level) {
    case 512: pk_len = 800; sk_len = 1632; ct_len = 768; break;
    case 768: pk_len = 1184; sk_len = 2400; ct_len = 1088; break;
    case 1024: pk_len = 1568; sk_len = 3168; ct_len = 1568; break;
    default: fprintf(stderr, "unsupported level\n"); return 2;
  }
  char *end = NULL;
  unsigned long samples = strtoul(argv[3], &end, 10);
  if (!end || *end || samples < 1 || samples > 4096) {
    fprintf(stderr, "SAMPLES must be between 1 and 4096\n");
    return 2;
  }
  unsigned long repeats = strtoul(argv[4], &end, 10);
  if (!end || *end || repeats < 100 || repeats > 1000000) {
    fprintf(stderr, "REPEATS must be between 100 and 1000000\n");
    return 2;
  }

  void *handle = dlopen(argv[1], RTLD_NOW);
  if (!handle) {
    fprintf(stderr, "dlopen: %s\n", dlerror());
    return 2;
  }
  keypair_fn keypair = (keypair_fn)load_symbol(handle, "mlkem_keypair");
  enc_fn enc = (enc_fn)load_symbol(handle, "mlkem_enc");
  dec_fn dec = (dec_fn)load_symbol(handle, "mlkem_dec");

  uint8_t *pk = malloc(pk_len);
  uint8_t *sk = malloc(sk_len);
  uint8_t *inputs = malloc(CLASS_COUNT * samples * ct_len);
  uint8_t expected[32], actual[32];
  if (!pk || !sk || !inputs) {
    perror("malloc");
    return 2;
  }
  if (keypair(pk, sk)) {
    fprintf(stderr, "setup failed\n");
    return 2;
  }

  for (unsigned long j = 0; j < samples; j++) {
    uint8_t *normal = inputs + (0 * samples + j) * ct_len;
    uint8_t *first = inputs + (1 * samples + j) * ct_len;
    uint8_t *mid = inputs + (2 * samples + j) * ct_len;
    uint8_t *last = inputs + (3 * samples + j) * ct_len;
    if (enc(normal, expected, pk)) {
      fprintf(stderr, "encapsulation failed\n");
      return 2;
    }
    memcpy(first, normal, ct_len);
    memcpy(mid, normal, ct_len);
    memcpy(last, normal, ct_len);
    first[0] ^= 1;
    mid[ct_len / 2] ^= 1;
    last[ct_len - 1] ^= 1;
    if (dec(actual, normal, sk) || memcmp(expected, actual, 32) != 0) {
      fprintf(stderr, "normal input self-check failed\n");
      return 2;
    }
    if (dec(actual, first, sk) || memcmp(expected, actual, 32) == 0) {
      fprintf(stderr, "changed_first self-check failed\n");
      return 2;
    }
    if (dec(actual, mid, sk) || memcmp(expected, actual, 32) == 0) {
      fprintf(stderr, "changed_mid self-check failed\n");
      return 2;
    }
    if (dec(actual, last, sk) || memcmp(expected, actual, 32) == 0) {
      fprintf(stderr, "changed_last self-check failed\n");
      return 2;
    }
  }

  for (unsigned long i = 0; i < 2000; i++) {
    unsigned long j = i % samples;
    for (unsigned cls = 0; cls < CLASS_COUNT; cls++) {
      dec(actual, inputs + (cls * samples + j) * ct_len, sk);
    }
  }

  FILE *out = fopen(argv[5], "w");
  if (!out) {
    perror("fopen");
    return 2;
  }
  fputs("repeat,class_index,class_name,sample,elapsed_ns\n", out);
  uint32_t random_state = 0x9e3779b9U;
  for (unsigned long i = 0; i < repeats; i++) {
    for (unsigned k = 0; k < CLASS_COUNT; k++) {
      uint32_t rnd = next_random(&random_state);
      unsigned cls = (rnd + k) % CLASS_COUNT;
      unsigned long sample = (i + (rnd % samples)) % samples;
      uint64_t elapsed = measure(dec, actual, inputs + (cls * samples + sample) * ct_len, sk);
      fprintf(out, "%lu,%u,%s,%lu,%" PRIu64 "\n", i, cls, CLASS_NAMES[cls], sample, elapsed);
    }
  }
  if (fclose(out) != 0) {
    perror("fclose");
    return 2;
  }
  memset(sk, 0, sk_len);
  free(pk);
  free(sk);
  free(inputs);
  dlclose(handle);
  return 0;
}

