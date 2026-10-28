/* Independent oracle byte primitives. No production project code is included.
 * Parsing, topic matching, sequence selection, and retention are Python-owned.
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
uint64_t tiplog_oracle_fnv(const unsigned char *data, const uint64_t *offset,
                          const uint16_t *length, const uint64_t *seq,
                          size_t count, uint64_t state) {
  for (size_t j=0; j<count; ++j) {
    for (unsigned shift=0; shift<64; shift+=8) {
      state ^= (seq[j] >> shift) & UINT64_C(255);
      state *= UINT64_C(1099511628211);
    }
    for (uint16_t k=0; k<length[j]; ++k) {
      state ^= data[offset[j]+k];
      state *= UINT64_C(1099511628211);
    }
  }
  return state;
}
size_t tiplog_oracle_copy(const unsigned char *data, const uint64_t *offset,
                         const uint16_t *length, size_t count,
                         unsigned char *output) {
  size_t written=0;
  for (size_t j=0; j<count; ++j) {
    memcpy(output+written, data+offset[j], length[j]);
    written += length[j];
  }
  return written;
}
