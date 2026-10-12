#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/random.h>
#include <unistd.h>

int randombytes(uint8_t *out, size_t outlen)
{
  size_t offset = 0;
  while (offset < outlen)
  {
    ssize_t n = getrandom(out + offset, outlen - offset, 0);
    if (n > 0)
    {
      offset += (size_t)n;
      continue;
    }
    if (n < 0 && errno == EINTR)
    {
      continue;
    }
    break;
  }
  if (offset == outlen)
  {
    return 0;
  }

  int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
  if (fd < 0)
  {
    return -1;
  }
  while (offset < outlen)
  {
    ssize_t n = read(fd, out + offset, outlen - offset);
    if (n > 0)
    {
      offset += (size_t)n;
    }
    else if (n < 0 && errno == EINTR)
    {
      continue;
    }
    else
    {
      close(fd);
      return -1;
    }
  }
  close(fd);
  return 0;
}
