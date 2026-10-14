#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

typedef int (*dec_fn)(uint8_t *, const uint8_t *, const uint8_t *);

typedef struct {
  uint32_t sample;
  uint8_t class_id;
  uint8_t reserved[3];
} request_header;

typedef struct {
  uint64_t internal_ns;
  uint32_t delay_us;
  int32_t return_code;
  int32_t server_cpu;
  uint32_t reserved;
} response_record;

static uint64_t now_ns(void) {
  struct timespec value;
  if (clock_gettime(CLOCK_MONOTONIC_RAW, &value) != 0) exit(3);
  return (uint64_t)value.tv_sec * 1000000000ULL + (uint64_t)value.tv_nsec;
}

static uint32_t random_u32(uint32_t *state) {
  *state ^= *state << 13;
  *state ^= *state >> 17;
  *state ^= *state << 5;
  return *state;
}

static int send_all(int fd, const void *buffer, size_t length) {
  const uint8_t *cursor = buffer;
  while (length != 0) {
    ssize_t sent = send(fd, cursor, length, MSG_NOSIGNAL);
    if (sent <= 0) return -1;
    cursor += (size_t)sent;
    length -= (size_t)sent;
  }
  return 0;
}

static int receive_all(int fd, void *buffer, size_t length) {
  uint8_t *cursor = buffer;
  while (length != 0) {
    ssize_t received = recv(fd, cursor, length, 0);
    if (received <= 0) return -1;
    cursor += (size_t)received;
    length -= (size_t)received;
  }
  return 0;
}

static void pin_to_cpu(int cpu) {
  cpu_set_t set;
  CPU_ZERO(&set);
  CPU_SET(cpu, &set);
  if (sched_setaffinity(0, sizeof(set), &set) != 0) exit(5);
}

static void apply_delay(uint32_t base_us, uint32_t jitter_us, uint32_t *state,
                        uint32_t *actual_us) {
  int64_t delay = (int64_t)base_us;
  if (jitter_us != 0) {
    uint32_t width = jitter_us * 2U + 1U;
    delay += (int64_t)(random_u32(state) % width) - (int64_t)jitter_us;
  }
  if (delay < 0) delay = 0;
  *actual_us = (uint32_t)delay;
  if (delay != 0) {
    struct timespec duration = {(time_t)(delay / 1000000), (long)(delay % 1000000) * 1000L};
    while (nanosleep(&duration, &duration) != 0 && errno == EINTR) {}
  }
}

static int serve(int listener, dec_fn dec, const uint8_t *data, uint32_t count,
                 size_t row_size, size_t ciphertext_size,
                 uint32_t base_us, uint32_t jitter_us, uint32_t seed, int cpu) {
  pin_to_cpu(cpu);
  int connection = accept(listener, NULL, NULL);
  if (connection < 0) return 10;
  int enabled = 1;
  setsockopt(connection, IPPROTO_TCP, TCP_NODELAY, &enabled, sizeof(enabled));
  uint8_t *ciphertext = malloc(ciphertext_size);
  uint8_t *shared_secret = malloc(32);
  if (!ciphertext || !shared_secret) return 11;
  for (;;) {
    request_header request;
    if (receive_all(connection, &request, sizeof(request)) != 0) break;
    if (request.class_id == 255) break;
    if (request.sample >= count || request.class_id > 3 ||
        receive_all(connection, ciphertext, ciphertext_size) != 0) return 12;
    const uint8_t *secret_key = data + (size_t)request.sample * row_size;
    uint64_t begin = now_ns();
    int rc = dec(shared_secret, ciphertext, secret_key);
    uint64_t end = now_ns();
    response_record response = {end - begin, 0, rc, sched_getcpu(), 0};
    apply_delay(base_us, jitter_us, &seed, &response.delay_us);
    if (send_all(connection, &response, sizeof(response)) != 0) return 13;
  }
  volatile uint8_t *wipe = shared_secret;
  for (size_t i = 0; i < 32; ++i) wipe[i] = 0;
  free(shared_secret);
  free(ciphertext);
  close(connection);
  return 0;
}

static int request_once(int connection, uint32_t sample, uint8_t class_id,
                        const uint8_t *ciphertext, size_t ciphertext_size,
                        response_record *response, uint64_t *rtt_ns) {
  request_header request = {sample, class_id, {0, 0, 0}};
  uint64_t begin = now_ns();
  if (send_all(connection, &request, sizeof(request)) != 0 ||
      send_all(connection, ciphertext, ciphertext_size) != 0 ||
      receive_all(connection, response, sizeof(*response)) != 0) return -1;
  *rtt_ns = now_ns() - begin;
  return response->return_code == 0 ? 0 : -1;
}

int main(int argc, char **argv) {
  if (argc != 13) {
    fprintf(stderr, "usage: network_noise_measure LIB LEVEL SAMPLE.bin PAIRS SEED OUTPUT.csv CLASS CONTROL SERVER_CPU CLIENT_CPU BASE_US JITTER_US\n");
    return 2;
  }
  int level = atoi(argv[2]);
  int pairs = atoi(argv[4]);
  uint32_t seed = (uint32_t)strtoul(argv[5], NULL, 10);
  int class_id = atoi(argv[7]);
  int control = atoi(argv[8]);
  int server_cpu = atoi(argv[9]);
  int client_cpu = atoi(argv[10]);
  uint32_t base_us = (uint32_t)strtoul(argv[11], NULL, 10);
  uint32_t jitter_us = (uint32_t)strtoul(argv[12], NULL, 10);
  size_t secret_key_size = 0, ciphertext_size = 0;
  if (level == 512) { secret_key_size = 1632; ciphertext_size = 768; }
  else if (level == 768) { secret_key_size = 2400; ciphertext_size = 1088; }
  else if (level == 1024) { secret_key_size = 3168; ciphertext_size = 1568; }
  else return 2;
  if (pairs < 100 || pairs > 100000 || class_id < 1 || class_id > 3 ||
      (control != 0 && control != 1) || server_cpu == client_cpu) return 2;
  if (seed == 0) seed = 1;

  FILE *input = fopen(argv[3], "rb");
  if (!input) return 2;
  uint32_t count = 0;
  if (fread(&count, 4, 1, input) != 1 || count < 1 || count > 4096) return 2;
  size_t row_size = secret_key_size + 4 * ciphertext_size;
  size_t data_size = (size_t)count * row_size;
  uint8_t *data = malloc(data_size);
  if (!data || fread(data, 1, data_size, input) != data_size || fgetc(input) != EOF) return 2;
  fclose(input);

  void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!library) return 3;
  dec_fn dec;
  *(void **)(&dec) = dlsym(library, "mlkem_dec");
  if (!dec) return 3;

  int listener = socket(AF_INET, SOCK_STREAM, 0);
  if (listener < 0) return 6;
  int enabled = 1;
  setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &enabled, sizeof(enabled));
  struct sockaddr_in address;
  memset(&address, 0, sizeof(address));
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  address.sin_port = 0;
  if (bind(listener, (struct sockaddr *)&address, sizeof(address)) != 0 || listen(listener, 1) != 0) return 6;
  socklen_t address_length = sizeof(address);
  if (getsockname(listener, (struct sockaddr *)&address, &address_length) != 0) return 6;

  pid_t child = fork();
  if (child < 0) return 7;
  if (child == 0) {
    int result = serve(listener, dec, data, count, row_size, ciphertext_size,
                       base_us, jitter_us, seed ^ 0xa5a5a5a5U,
                       server_cpu);
    _exit(result);
  }

  pin_to_cpu(client_cpu);
  int connection = socket(AF_INET, SOCK_STREAM, 0);
  if (connection < 0) return 8;
  setsockopt(connection, IPPROTO_TCP, TCP_NODELAY, &enabled, sizeof(enabled));
  if (connect(connection, (struct sockaddr *)&address, sizeof(address)) != 0) return 8;
  close(listener);

  /* Warm up both paths without writing measurements. */
  for (int i = 0; i < 200; ++i) {
    uint32_t sample = (uint32_t)i % count;
    uint8_t *row = data + (size_t)sample * row_size;
    response_record response;
    uint64_t rtt;
    if (request_once(connection, sample, 0, row + secret_key_size,
                     ciphertext_size, &response, &rtt) != 0) return 9;
  }

  FILE *output = fopen(argv[6], "w");
  if (!output) return 2;
  fputs("pair,sample,order,valid_internal_ns,changed_internal_ns,valid_rtt_ns,changed_rtt_ns,valid_delay_us,changed_delay_us,server_cpu,client_cpu\n", output);
  for (int pair = 0; pair < pairs; ++pair) {
    uint32_t sample = random_u32(&seed) % count;
    uint32_t order = random_u32(&seed) & 1U;
    uint8_t *row = data + (size_t)sample * row_size;
    uint8_t changed_class = control ? 0 : (uint8_t)class_id;
    response_record valid_response, changed_response;
    uint64_t valid_rtt, changed_rtt;
    int first = order == 0
      ? request_once(connection, sample, 0, row + secret_key_size, ciphertext_size, &valid_response, &valid_rtt)
      : request_once(connection, sample, changed_class, row + secret_key_size + (size_t)changed_class * ciphertext_size, ciphertext_size, &changed_response, &changed_rtt);
    int second = order == 0
      ? request_once(connection, sample, changed_class, row + secret_key_size + (size_t)changed_class * ciphertext_size, ciphertext_size, &changed_response, &changed_rtt)
      : request_once(connection, sample, 0, row + secret_key_size, ciphertext_size, &valid_response, &valid_rtt);
    if (first != 0 || second != 0) return 9;
    fprintf(output, "%d,%u,%u,%llu,%llu,%llu,%llu,%u,%u,%d,%d\n",
            pair, sample, order,
            (unsigned long long)valid_response.internal_ns,
            (unsigned long long)changed_response.internal_ns,
            (unsigned long long)valid_rtt,
            (unsigned long long)changed_rtt,
            valid_response.delay_us, changed_response.delay_us,
            valid_response.server_cpu, sched_getcpu());
  }
  fclose(output);
  request_header stop = {0, 255, {0, 0, 0}};
  send_all(connection, &stop, sizeof(stop));
  close(connection);
  int status = 0;
  waitpid(child, &status, 0);
  volatile uint8_t *wipe = data;
  for (size_t i = 0; i < data_size; ++i) wipe[i] = 0;
  free(data);
  dlclose(library);
  return WIFEXITED(status) ? WEXITSTATUS(status) : 15;
}
