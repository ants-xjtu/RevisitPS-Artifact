#ifndef ZIPFIAN_INCAST_PATTERN_H
#define ZIPFIAN_INCAST_PATTERN_H

#include <cstdint>
#include <string>
#include <vector>

struct traffic_pattern_t {
  std::vector<int> send_counts;
  std::vector<int> recv_totals;
  std::vector<double> receiver_weights;
};

traffic_pattern_t build_zipfian_incast_pattern(int group_size, int rank,
                                               std::int64_t base_size_bytes,
                                               double alpha);

std::vector<int> build_remote_write_offsets_from_flat_recv_displs(
    int group_size, int group_rank, const std::vector<int>& flat_recv_displs);

void fill_alltoallv_write_headers(std::uint8_t* send_buf, int self_rank,
                                  const std::vector<int>& group_world_ranks,
                                  const std::vector<int>& send_counts,
                                  const std::vector<int>& send_displs);

int count_alltoallv_write_header_errors(const std::uint8_t* recv_buf, int self_rank,
                                        const std::vector<int>& group_world_ranks,
                                        const std::vector<int>& recv_counts,
                                        const std::vector<int>& recv_displs,
                                        std::string* first_error);

#endif
