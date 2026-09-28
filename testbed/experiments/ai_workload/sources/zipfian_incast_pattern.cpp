#include "zipfian_incast_pattern.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <sstream>
#include <stdexcept>

static std::vector<double> generate_zipfian_distribution(int group_size, double alpha) {
  if (group_size <= 0) {
    throw std::invalid_argument("group_size must be positive");
  }
  if (alpha < 0.0) {
    throw std::invalid_argument("alpha must be non-negative");
  }

  std::vector<double> weights(group_size, 0.0);
  if (alpha == 0.0) {
    std::fill(weights.begin(), weights.end(), 1.0);
    return weights;
  }
  for (int i = 0; i < group_size; ++i) {
    weights[i] = 1.0 / std::pow((double)(i + 1), alpha);
  }
  return weights;
}

traffic_pattern_t build_zipfian_incast_pattern(int group_size, int rank,
                                               std::int64_t base_size_bytes,
                                               double alpha) {
  if (group_size <= 1) {
    throw std::invalid_argument("group_size must be at least 2");
  }
  if (rank < 0 || rank >= group_size) {
    throw std::invalid_argument("rank out of range");
  }
  if (base_size_bytes <= 0) {
    throw std::invalid_argument("base_size_bytes must be positive");
  }
  if (base_size_bytes > std::numeric_limits<int>::max()) {
    throw std::invalid_argument("base_size_bytes exceeds int range");
  }

  traffic_pattern_t pattern;
  pattern.send_counts.assign(group_size, 0);
  pattern.receiver_weights = generate_zipfian_distribution(group_size, alpha);
  pattern.recv_totals.assign(group_size, 0);

  const double max_weight = *std::max_element(pattern.receiver_weights.begin(),
                                              pattern.receiver_weights.end());
  for (int dst = 0; dst < group_size; ++dst) {
    const double scaled = (double)base_size_bytes * (pattern.receiver_weights[dst] / max_weight);
    pattern.recv_totals[dst] = (int)scaled;
  }

  for (int dst = 0; dst < group_size; ++dst) {
    const int senders = group_size - 1;
    const int base_bytes = pattern.recv_totals[dst] / senders;
    const int remainder = pattern.recv_totals[dst] % senders;
    int sender_index = 0;
    for (int src = 0; src < group_size; ++src) {
      if (src == dst) continue;
      const int bytes = base_bytes + (sender_index < remainder ? 1 : 0);
      if (src == rank) {
        pattern.send_counts[dst] = bytes;
      }
      ++sender_index;
    }
  }

  pattern.send_counts[rank] = 0;
  return pattern;
}

std::vector<int> build_remote_write_offsets_from_flat_recv_displs(
    int group_size, int group_rank, const std::vector<int>& flat_recv_displs) {
  if (group_size <= 0) {
    throw std::invalid_argument("group_size must be positive");
  }
  if (group_rank < 0 || group_rank >= group_size) {
    throw std::invalid_argument("group_rank out of range");
  }
  if ((int)flat_recv_displs.size() != group_size * group_size) {
    throw std::invalid_argument("flat_recv_displs size mismatch");
  }

  std::vector<int> offsets(group_size, 0);
  for (int peer_rank = 0; peer_rank < group_size; ++peer_rank) {
    offsets[peer_rank] = flat_recv_displs[peer_rank * group_size + group_rank];
  }
  return offsets;
}

void fill_alltoallv_write_headers(std::uint8_t* send_buf, int self_rank,
                                  const std::vector<int>& group_world_ranks,
                                  const std::vector<int>& send_counts,
                                  const std::vector<int>& send_displs) {
  if (!send_buf) {
    throw std::invalid_argument("send_buf must not be null");
  }
  if (group_world_ranks.size() != send_counts.size() ||
      send_counts.size() != send_displs.size()) {
    throw std::invalid_argument("header fill vector sizes must match");
  }

  for (size_t gi = 0; gi < group_world_ranks.size(); ++gi) {
    const int peer = group_world_ranks[gi];
    const int len = send_counts[gi];
    if (peer == self_rank || len < 12) continue;
    std::uint32_t* w =
        reinterpret_cast<std::uint32_t*>(send_buf + (size_t)send_displs[gi]);
    w[0] = (std::uint32_t)self_rank;
    w[1] = (std::uint32_t)peer;
    w[2] = 0xDEADBEEF;
  }
}

int count_alltoallv_write_header_errors(const std::uint8_t* recv_buf, int self_rank,
                                        const std::vector<int>& group_world_ranks,
                                        const std::vector<int>& recv_counts,
                                        const std::vector<int>& recv_displs,
                                        std::string* first_error) {
  if (!recv_buf) {
    throw std::invalid_argument("recv_buf must not be null");
  }
  if (group_world_ranks.size() != recv_counts.size() ||
      recv_counts.size() != recv_displs.size()) {
    throw std::invalid_argument("header verify vector sizes must match");
  }

  int errors = 0;
  if (first_error) first_error->clear();
  for (size_t gi = 0; gi < group_world_ranks.size(); ++gi) {
    const int peer = group_world_ranks[gi];
    const int len = recv_counts[gi];
    if (peer == self_rank || len <= 0 || len < 12) continue;
    const std::uint32_t* w =
        reinterpret_cast<const std::uint32_t*>(recv_buf + (size_t)recv_displs[gi]);
    if (w[0] != (std::uint32_t)peer || w[1] != (std::uint32_t)self_rank ||
        w[2] != 0xDEADBEEF) {
      if (errors == 0 && first_error) {
        std::ostringstream oss;
        oss << "src=" << w[0] << " dst=" << w[1] << " magic=0x"
            << std::hex << w[2];
        *first_error = oss.str();
      }
      errors++;
    }
  }
  return errors;
}
