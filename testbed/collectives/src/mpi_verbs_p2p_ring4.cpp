#include <mpi.h>
#include <infiniband/verbs.h>
#include <arpa/inet.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <unistd.h>

#define CHECK(x) do { if (!(x)) { \
  fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__, #x); \
  MPI_Abort(MPI_COMM_WORLD, 1); \
} } while (0)

struct Config {
  enum class Bench { BW, LATENCY };
  enum class Mode { WRITE };
  enum class WriteNotify { IMM, NONE };
  enum class LatencyMetric { RTT2, FCT };
  Bench bench = Bench::BW;
  Mode mode = Mode::WRITE;
  WriteNotify write_notify = WriteNotify::IMM;
  LatencyMetric latency_metric = LatencyMetric::FCT;
  std::vector<size_t> sizes;
  int warmup = 20;
  int iters = 2000;
  int inflight = 1;
  int sig_interval = 16;
  size_t write_chunk = 1u << 20;
  int ib_port = 1;
  int gid_index = 3;
  int single_flow_src = -1;  // -1 means all ring flows active; >=0 means only src->next active
  uint32_t active_src_mask = 0xF;  // bit i => flow i->(i+1) active
  bool active_src_mask_user_set = false;
  bool no_ack = false;             // skip backward ACK path
  bool independent_flows = false;  // only wait local tx completion, no ring feedback path
  bool independent_all_flows = false;  // with independent mode, use all ring flows instead of pair mode
  bool iter_barrier = true;        // synchronize all ranks between iterations
  std::string dump_iter_fct_path;
  std::vector<int> group_nps;
  std::vector<int> ring_order;
  std::vector<std::vector<int>> group_ring_orders;
  std::vector<std::string> group_dump_iter_fct_paths;
  std::vector<int> ring_pos_by_rank;
};

struct ConnInfo {
  uint16_t lid;
  uint32_t qpn;
  uint32_t psn;
  uint8_t gid[16];
};

struct ConnPair {
  ConnInfo next;
  ConnInfo prev;
};

struct RemoteMrInfo {
  uint64_t addr;
  uint32_t rkey;
};

struct GroupRuntime {
  int world_rank = 0;
  int world_size = 0;
  int group_id = 0;
  int group_base = 0;
  int group_rank = 0;
  int group_size = 0;
  MPI_Comm group_comm = MPI_COMM_NULL;
  std::vector<int> group_world_ranks;
  std::vector<int> ring_order;
  std::vector<int> ring_pos_by_rank;
  std::string dump_iter_fct_path;
};

struct VerbsRes {
  ibv_context* ctx = nullptr;
  ibv_pd* pd = nullptr;
  ibv_cq* cq_next = nullptr;
  ibv_cq* cq_prev = nullptr;
  ibv_qp* qp_next = nullptr;
  ibv_qp* qp_prev = nullptr;
  ibv_mr* mr_send = nullptr;
  ibv_mr* mr_recv = nullptr;
  uint8_t* send_buf = nullptr;
  uint8_t* recv_buf = nullptr;
  size_t buf_size = 0;
  int gid_index = 3;
};

static void die(const char* what, int rc) {
  fprintf(stderr, "%s failed rc=%d errno=%d (%s)\n", what, rc, errno, strerror(errno));
  MPI_Abort(MPI_COMM_WORLD, 1);
}

static double now_sec() {
  using namespace std::chrono;
  return duration<double>(steady_clock::now().time_since_epoch()).count();
}

static int env_local_rank() {
  const char* vars[] = {
    "OMPI_COMM_WORLD_LOCAL_RANK",
    "MV2_COMM_WORLD_LOCAL_RANK",
    "SLURM_LOCALID",
    nullptr
  };
  for (int i = 0; vars[i] != nullptr; ++i) {
    const char* v = getenv(vars[i]);
    if (v && *v) return atoi(v);
  }
  return 0;
}

static std::vector<std::string> matched_devices(const char* prefix) {
  int num = 0;
  ibv_device** list = ibv_get_device_list(&num);
  CHECK(list != nullptr && num > 0);
  std::vector<std::string> out;
  size_t pre_len = strlen(prefix);
  for (int i = 0; i < num; ++i) {
    const char* name = ibv_get_device_name(list[i]);
    if (strncmp(name, prefix, pre_len) == 0) out.emplace_back(name);
  }
  std::sort(out.begin(), out.end());
  ibv_free_device_list(list);
  return out;
}

static std::vector<std::string> parse_csv_strings(const char* text) {
  std::vector<std::string> out;
  if (!text || !*text) return out;
  std::string s(text);
  size_t pos = 0;
  while (pos < s.size()) {
    size_t comma = s.find(',', pos);
    std::string tok = (comma == std::string::npos) ? s.substr(pos) : s.substr(pos, comma - pos);
    size_t b = 0, e = tok.size();
    while (b < e && (tok[b] == ' ' || tok[b] == '\t')) b++;
    while (e > b && (tok[e - 1] == ' ' || tok[e - 1] == '\t')) e--;
    if (e > b) out.emplace_back(tok.substr(b, e - b));
    if (comma == std::string::npos) break;
    pos = comma + 1;
  }
  return out;
}

static bool lookup_dev_by_host(const char* map_env,
                               const std::string& host,
                               std::string* out_dev) {
  if (!map_env || !*map_env || !out_dev) return false;
  std::string s(map_env);
  size_t pos = 0;
  while (pos <= s.size()) {
    size_t sep = s.find_first_of("|;", pos);
    std::string host_entry = (sep == std::string::npos) ? s.substr(pos) : s.substr(pos, sep - pos);
    size_t colon = host_entry.find(':');
    if (colon != std::string::npos) {
      std::string h = host_entry.substr(0, colon);
      std::string dev = host_entry.substr(colon + 1);
      if (h == host && !dev.empty()) {
        *out_dev = dev;
        return true;
      }
    }
    if (sep == std::string::npos) break;
    pos = sep + 1;
  }
  return false;
}

static std::string short_hostname() {
  char buf[256];
  if (gethostname(buf, sizeof(buf)) != 0) return "";
  buf[sizeof(buf) - 1] = '\0';
  std::string h(buf);
  size_t dot = h.find('.');
  if (dot != std::string::npos) h = h.substr(0, dot);
  return h;
}

static const char* env_or_empty(const char* name) {
  const char* v = getenv(name);
  return (v && *v) ? v : "";
}

static std::string pick_device_name(int world_rank, int world_size) {
  const char* dev_map_by_host = getenv("IB_DEV_MAP_BY_HOST");
  if (dev_map_by_host && *dev_map_by_host) {
    std::string host = short_hostname();
    std::string mapped_dev;
    if (!host.empty() && lookup_dev_by_host(dev_map_by_host, host, &mapped_dev)) {
      return mapped_dev;
    }
  }

  const char* dev_map = getenv("IB_DEV_MAP");
  if (dev_map && *dev_map) {
    auto mapped = parse_csv_strings(dev_map);
    if ((int)mapped.size() == world_size) {
      CHECK(world_rank >= 0 && world_rank < world_size);
      return mapped[(size_t)world_rank];
    }
  }

  const char* prefix = getenv("IB_DEV_PREFIX");
  if (!prefix || !*prefix) prefix = "mlx5_";

  auto names = matched_devices(prefix);
  if (!names.empty()) {
    int lr = env_local_rank();
    return names[(size_t)lr % names.size()];
  }

  int num = 0;
  ibv_device** list = ibv_get_device_list(&num);
  CHECK(list != nullptr && num > 0);
  std::string fallback = ibv_get_device_name(list[0]);
  ibv_free_device_list(list);
  return fallback;
}

static bool lookup_gid_index_by_host_dev(const char* map_env,
                                         const std::string& host,
                                         const std::string& dev,
                                         int* out_idx) {
  if (!map_env || !*map_env || !out_idx) return false;
  std::string s(map_env);
  size_t pos = 0;
  while (pos <= s.size()) {
    size_t sep = s.find_first_of("|;", pos);
    std::string host_entry = (sep == std::string::npos) ? s.substr(pos) : s.substr(pos, sep - pos);
    size_t colon = host_entry.find(':');
    if (colon != std::string::npos) {
      std::string h = host_entry.substr(0, colon);
      if (h == host) {
        std::string pairs = host_entry.substr(colon + 1);
        size_t p = 0;
        while (p <= pairs.size()) {
          size_t comma = pairs.find(',', p);
          std::string kv = (comma == std::string::npos) ? pairs.substr(p) : pairs.substr(p, comma - p);
          size_t eq = kv.find('=');
          if (eq != std::string::npos) {
            std::string d = kv.substr(0, eq);
            std::string v = kv.substr(eq + 1);
            if (d == dev && !v.empty()) {
              *out_idx = atoi(v.c_str());
              return true;
            }
          }
          if (comma == std::string::npos) break;
          p = comma + 1;
        }
      }
    }
    if (sep == std::string::npos) break;
    pos = sep + 1;
  }
  return false;
}

static int resolve_gid_index_for_host_dev(const std::string& dev_name, int fallback_gid) {
  int idx = fallback_gid;
  const char* map_env = getenv("GID_INDEX_BY_HOST_DEV");
  if (!map_env || !*map_env) return idx;
  std::string host = short_hostname();
  if (host.empty()) return idx;
  int mapped = idx;
  if (lookup_gid_index_by_host_dev(map_env, host, dev_name, &mapped)) {
    idx = mapped;
  }
  return idx;
}

static size_t parse_size_token(const std::string& tok) {
  CHECK(!tok.empty());
  char unit = tok.back();
  long long mult = 1;
  std::string base = tok;
  if (unit == 'K' || unit == 'k') {
    mult = 1024LL;
    base.pop_back();
  } else if (unit == 'M' || unit == 'm') {
    mult = 1024LL * 1024LL;
    base.pop_back();
  } else if (unit == 'G' || unit == 'g') {
    mult = 1024LL * 1024LL * 1024LL;
    base.pop_back();
  }
  long long v = atoll(base.c_str());
  CHECK(v > 0);
  return (size_t)(v * mult);
}

static std::vector<size_t> parse_sizes_csv(const std::string& s) {
  std::vector<size_t> sizes;
  size_t pos = 0;
  while (pos < s.size()) {
    size_t comma = s.find(',', pos);
    std::string tok = (comma == std::string::npos) ? s.substr(pos) : s.substr(pos, comma - pos);
    if (!tok.empty()) sizes.push_back(parse_size_token(tok));
    if (comma == std::string::npos) break;
    pos = comma + 1;
  }
  CHECK(!sizes.empty());
  return sizes;
}

static uint32_t parse_src_mask_csv(const std::string& s) {
  uint32_t mask = 0;
  size_t pos = 0;
  while (pos < s.size()) {
    size_t comma = s.find(',', pos);
    std::string tok = (comma == std::string::npos) ? s.substr(pos) : s.substr(pos, comma - pos);
    if (!tok.empty()) {
      int src = atoi(tok.c_str());
      CHECK(src >= 0 && src < 32);
      mask |= (1u << (uint32_t)src);
    }
    if (comma == std::string::npos) break;
    pos = comma + 1;
  }
  CHECK(mask != 0);
  return mask;
}

static std::vector<int> parse_rank_order_csv(const std::string& s) {
  std::vector<int> order;
  size_t pos = 0;
  while (pos < s.size()) {
    size_t comma = s.find(',', pos);
    std::string tok = (comma == std::string::npos) ? s.substr(pos) : s.substr(pos, comma - pos);
    if (!tok.empty()) {
      order.push_back(atoi(tok.c_str()));
    }
    if (comma == std::string::npos) break;
    pos = comma + 1;
  }
  CHECK(!order.empty());
  return order;
}

static std::vector<int> parse_int_csv(const std::string& s) {
  std::vector<int> out;
  size_t pos = 0;
  while (pos <= s.size()) {
    size_t comma = s.find(',', pos);
    std::string tok = (comma == std::string::npos) ? s.substr(pos) : s.substr(pos, comma - pos);
    if (!tok.empty()) out.push_back(atoi(tok.c_str()));
    if (comma == std::string::npos) break;
    pos = comma + 1;
  }
  return out;
}

static std::vector<std::string> parse_pipe_list(const std::string& s) {
  std::vector<std::string> out;
  size_t pos = 0;
  while (pos <= s.size()) {
    size_t sep = s.find('|', pos);
    out.push_back((sep == std::string::npos) ? s.substr(pos) : s.substr(pos, sep - pos));
    if (sep == std::string::npos) break;
    pos = sep + 1;
  }
  return out;
}

static std::vector<std::vector<int>> parse_group_ring_orders(const std::string& s) {
  std::vector<std::vector<int>> out;
  for (const std::string& item : parse_pipe_list(s)) {
    if (item.empty()) {
      out.push_back(std::vector<int>());
    } else {
      out.push_back(parse_rank_order_csv(item));
    }
  }
  return out;
}

static void finalize_ring_order(std::vector<int>* ring_order,
                                std::vector<int>* ring_pos_by_rank,
                                int rank,
                                int ring_size,
                                const char* arg_name) {
  CHECK(ring_order != nullptr);
  CHECK(ring_pos_by_rank != nullptr);
  if (ring_order->empty()) {
    ring_order->resize((size_t)ring_size, 0);
    for (int i = 0; i < ring_size; ++i) (*ring_order)[(size_t)i] = i;
  }
  if ((int)ring_order->size() != ring_size) {
    if (rank == 0) fprintf(stderr, "%s must list exactly %d ranks\n", arg_name, ring_size);
    MPI_Abort(MPI_COMM_WORLD, 1);
  }
  ring_pos_by_rank->assign((size_t)ring_size, -1);
  for (int pos = 0; pos < ring_size; ++pos) {
    int ring_rank = (*ring_order)[(size_t)pos];
    if (ring_rank < 0 || ring_rank >= ring_size) {
      if (rank == 0) fprintf(stderr, "%s rank %d is out of range for ring size %d\n", arg_name, ring_rank, ring_size);
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    if ((*ring_pos_by_rank)[(size_t)ring_rank] != -1) {
      if (rank == 0) fprintf(stderr, "%s must be a permutation of ranks 0..%d\n", arg_name, ring_size - 1);
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    (*ring_pos_by_rank)[(size_t)ring_rank] = pos;
  }
}

static int ring_next_rank(const std::vector<int>& ring_order,
                          const std::vector<int>& ring_pos_by_rank,
                          int rank,
                          int ring_size) {
  CHECK(rank >= 0 && rank < ring_size);
  CHECK((int)ring_pos_by_rank.size() == ring_size);
  int pos = ring_pos_by_rank[(size_t)rank];
  CHECK(pos >= 0 && pos < ring_size);
  return ring_order[(size_t)((pos + 1) % ring_size)];
}

static int ring_prev_rank(const std::vector<int>& ring_order,
                          const std::vector<int>& ring_pos_by_rank,
                          int rank,
                          int ring_size) {
  CHECK(rank >= 0 && rank < ring_size);
  CHECK((int)ring_pos_by_rank.size() == ring_size);
  int pos = ring_pos_by_rank[(size_t)rank];
  CHECK(pos >= 0 && pos < ring_size);
  return ring_order[(size_t)((pos - 1 + ring_size) % ring_size)];
}

static void usage_and_abort(int rank) {
  if (rank == 0) {
    fprintf(stderr,
      "Usage: mpi_verbs_p2p_ring4 [--bench bw|latency] --mode write [--sizes 16M] [--warmup N] [--iters N] "
      "[--inflight 1] [--sig-interval N] [--write-chunk X] [--write-notify imm|none] [--latency-metric rtt2|fct] "
      "[--no-ack] [--independent-flows] [--independent-all-flows] [--active-src-list 0,2] "
      "[--single-flow-src N] [--ring-order 0,4,1,5] [--group-nps 8,8] "
      "[--group-ring-orders 0,2,4,6|0,4,1,5] [--iter-barrier|--no-iter-barrier] "
      "[--dump-iter-fct PATH] [--group-dump-iter-fct PATH_A|PATH_B] "
      "\n");
  }
  MPI_Abort(MPI_COMM_WORLD, 1);
}

static Config parse_args(int argc, char** argv, int rank) {
  Config c;
  c.sizes = parse_sizes_csv("8M,4M,2M,1M");
  const char* gid_env = getenv("GID_INDEX");
  if (gid_env && *gid_env) c.gid_index = atoi(gid_env);
  bool active_src_list_set = false;

  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    auto need = [&](const char* name) -> std::string {
      if (i + 1 >= argc) {
        if (rank == 0) fprintf(stderr, "Missing value for %s\n", name);
        usage_and_abort(rank);
      }
      return std::string(argv[++i]);
    };

    if (a == "--bench") {
      std::string v = need("--bench");
      if (v == "bw") c.bench = Config::Bench::BW;
      else if (v == "latency") c.bench = Config::Bench::LATENCY;
      else usage_and_abort(rank);
    } else if (a == "--mode") {
      std::string v = need("--mode");
      if (v != "write") usage_and_abort(rank);
    } else if (a == "--sizes") {
      c.sizes = parse_sizes_csv(need("--sizes"));
    } else if (a == "--warmup") {
      c.warmup = atoi(need("--warmup").c_str());
    } else if (a == "--iters") {
      c.iters = atoi(need("--iters").c_str());
    } else if (a == "--inflight") {
      c.inflight = atoi(need("--inflight").c_str());
    } else if (a == "--sig-interval") {
      c.sig_interval = atoi(need("--sig-interval").c_str());
    } else if (a == "--write-chunk") {
      c.write_chunk = parse_size_token(need("--write-chunk"));
    } else if (a == "--write-notify") {
      std::string v = need("--write-notify");
      if (v == "imm") c.write_notify = Config::WriteNotify::IMM;
      else if (v == "none") c.write_notify = Config::WriteNotify::NONE;
      else usage_and_abort(rank);
    } else if (a == "--latency-metric") {
      std::string v = need("--latency-metric");
      if (v == "rtt2") c.latency_metric = Config::LatencyMetric::RTT2;
      else if (v == "fct") c.latency_metric = Config::LatencyMetric::FCT;
      else usage_and_abort(rank);
    } else if (a == "--active-src-list") {
      c.active_src_mask = parse_src_mask_csv(need("--active-src-list"));
      c.active_src_mask_user_set = true;
      active_src_list_set = true;
    } else if (a == "--no-ack") {
      c.no_ack = true;
    } else if (a == "--independent-flows") {
      c.independent_flows = true;
    } else if (a == "--independent-all-flows") {
      c.independent_all_flows = true;
    } else if (a == "--single-flow-src") {
      c.single_flow_src = atoi(need("--single-flow-src").c_str());
      c.active_src_mask_user_set = true;
    } else if (a == "--ring-order") {
      c.ring_order = parse_rank_order_csv(need("--ring-order"));
    } else if (a == "--group-nps") {
      c.group_nps = parse_int_csv(need("--group-nps"));
    } else if (a == "--group-ring-orders") {
      c.group_ring_orders = parse_group_ring_orders(need("--group-ring-orders"));
    } else if (a == "--iter-barrier") {
      c.iter_barrier = true;
    } else if (a == "--no-iter-barrier") {
      c.iter_barrier = false;
    } else if (a == "--dump-iter-fct") {
      c.dump_iter_fct_path = need("--dump-iter-fct");
    } else if (a == "--group-dump-iter-fct") {
      c.group_dump_iter_fct_paths = parse_pipe_list(need("--group-dump-iter-fct"));
    } else {
      usage_and_abort(rank);
    }
  }

  if (c.warmup < 0 || c.iters <= 0 || c.inflight <= 0 || c.sig_interval <= 0 || c.write_chunk == 0) {
    usage_and_abort(rank);
  }
  if (!c.independent_flows && c.inflight != 1) {
    if (rank == 0) fprintf(stderr, "ring4 benchmark currently requires --inflight 1\n");
    usage_and_abort(rank);
  }
  if (c.bench == Config::Bench::LATENCY && c.inflight != 1) {
    if (rank == 0) fprintf(stderr, "latency benchmark currently requires --inflight 1\n");
    usage_and_abort(rank);
  }
  if (c.single_flow_src < -1 || c.single_flow_src >= 32) {
    if (rank == 0) fprintf(stderr, "--single-flow-src must be -1 or in [0,31]\n");
    usage_and_abort(rank);
  }
  if (active_src_list_set && c.single_flow_src >= 0) {
    if (rank == 0) fprintf(stderr, "Use either --active-src-list or --single-flow-src, not both\n");
    usage_and_abort(rank);
  }
  if (c.single_flow_src >= 0) {
    c.active_src_mask = (1u << (uint32_t)c.single_flow_src);
  }
  if (c.independent_flows) {
    c.write_notify = Config::WriteNotify::NONE;
    c.no_ack = true;
  }
  return c;
}

static GroupRuntime build_group_runtime(const Config& cfg, int rank, int world_size) {
  GroupRuntime g;
  g.world_rank = rank;
  g.world_size = world_size;

  std::vector<int> group_nps = cfg.group_nps;
  if (group_nps.empty()) group_nps.push_back(world_size);

  int sum_group_nps = 0;
  for (int np : group_nps) {
    if (np <= 0) {
      if (rank == 0) fprintf(stderr, "--group-nps entries must be positive\n");
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    sum_group_nps += np;
  }
  if (sum_group_nps != world_size) {
    if (rank == 0) fprintf(stderr, "--group-nps must sum to world size %d\n", world_size);
    MPI_Abort(MPI_COMM_WORLD, 1);
  }

  int base = 0;
  for (size_t i = 0; i < group_nps.size(); ++i) {
    int next = base + group_nps[i];
    if (rank >= base && rank < next) {
      g.group_id = (int)i;
      g.group_base = base;
      g.group_size = group_nps[i];
      break;
    }
    base = next;
  }
  CHECK(g.group_size > 0);

  MPI_Comm_split(MPI_COMM_WORLD, g.group_id, rank, &g.group_comm);
  MPI_Comm_rank(g.group_comm, &g.group_rank);

  g.group_world_ranks.reserve((size_t)g.group_size);
  for (int i = 0; i < g.group_size; ++i) {
    g.group_world_ranks.push_back(g.group_base + i);
  }

  if (!cfg.group_ring_orders.empty()) {
    if (cfg.group_ring_orders.size() != group_nps.size()) {
      if (rank == 0) fprintf(stderr, "--group-ring-orders must provide one entry per group\n");
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    g.ring_order = cfg.group_ring_orders[(size_t)g.group_id];
  } else {
    if (!cfg.ring_order.empty() && group_nps.size() != 1) {
      if (rank == 0) fprintf(stderr, "--ring-order is only valid for single-group runs; use --group-ring-orders instead\n");
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    g.ring_order = cfg.ring_order;
  }
  finalize_ring_order(&g.ring_order, &g.ring_pos_by_rank, rank, g.group_size,
                      (!cfg.group_ring_orders.empty()) ? "--group-ring-orders" : "--ring-order");

  if (!cfg.group_dump_iter_fct_paths.empty()) {
    if (cfg.group_dump_iter_fct_paths.size() != group_nps.size()) {
      if (rank == 0) fprintf(stderr, "--group-dump-iter-fct must provide one entry per group\n");
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    g.dump_iter_fct_path = cfg.group_dump_iter_fct_paths[(size_t)g.group_id];
  } else {
    if (!cfg.dump_iter_fct_path.empty() && group_nps.size() != 1) {
      if (rank == 0) fprintf(stderr, "--dump-iter-fct is only valid for single-group runs; use --group-dump-iter-fct instead\n");
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    g.dump_iter_fct_path = cfg.dump_iter_fct_path;
  }

  return g;
}

static void qp_to_init(ibv_qp* qp, const Config& cfg) {
  ibv_qp_attr a{};
  a.qp_state = IBV_QPS_INIT;
  a.port_num = (uint8_t)cfg.ib_port;
  a.pkey_index = 0;
  a.qp_access_flags = IBV_ACCESS_REMOTE_WRITE;
  int rc = ibv_modify_qp(qp, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS);
  if (rc) die("ibv_modify_qp INIT", rc);
}

static void qp_to_rtr(ibv_qp* qp, const Config& cfg, const ConnInfo& remote) {
  ibv_qp_attr a{};
  a.qp_state = IBV_QPS_RTR;
  a.path_mtu = IBV_MTU_1024;
  a.dest_qp_num = remote.qpn;
  a.rq_psn = remote.psn;
  a.max_dest_rd_atomic = 1;
  a.min_rnr_timer = 12;
  a.ah_attr.is_global = 1;
  a.ah_attr.grh.dgid.global.interface_id = ((const uint64_t*)remote.gid)[1];
  a.ah_attr.grh.dgid.global.subnet_prefix = ((const uint64_t*)remote.gid)[0];
  a.ah_attr.grh.sgid_index = (uint8_t)cfg.gid_index;
  a.ah_attr.grh.hop_limit = 1;
  a.ah_attr.dlid = remote.lid;
  a.ah_attr.sl = 0;
  a.ah_attr.src_path_bits = 0;
  a.ah_attr.port_num = (uint8_t)cfg.ib_port;

  int flags = IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN |
              IBV_QP_RQ_PSN | IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER;
  int rc = ibv_modify_qp(qp, &a, flags);
  if (rc) die("ibv_modify_qp RTR", rc);
}

static void qp_to_rts(ibv_qp* qp, const ConnInfo& local) {
  ibv_qp_attr a{};
  a.qp_state = IBV_QPS_RTS;
  a.timeout = 14;
  a.retry_cnt = 7;
  a.rnr_retry = 7;
  a.sq_psn = local.psn;
  a.max_rd_atomic = 1;

  int rc = ibv_modify_qp(qp, &a,
                         IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT |
                         IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC);
  if (rc) die("ibv_modify_qp RTS", rc);
}

static ConnInfo local_conn_info(ibv_qp* qp, ibv_context* ctx, const Config& cfg) {
  ConnInfo c{};
  ibv_port_attr pa{};
  int rc = ibv_query_port(ctx, (uint8_t)cfg.ib_port, &pa);
  if (rc) die("ibv_query_port", rc);
  c.lid = pa.lid;
  c.qpn = qp->qp_num;
  c.psn = (uint32_t)(lrand48() & 0xffffff);

  union ibv_gid gid{};
  rc = ibv_query_gid(ctx, (uint8_t)cfg.ib_port, cfg.gid_index, &gid);
  if (rc) die("ibv_query_gid", rc);
  memcpy(c.gid, &gid, 16);
  return c;
}

static void verbs_setup(VerbsRes* r, const Config& cfg, size_t max_size, int world_rank, int world_size) {
  std::string dev_name = pick_device_name(world_rank, world_size);
  int resolved_gid = resolve_gid_index_for_host_dev(dev_name, cfg.gid_index);
  r->gid_index = resolved_gid;
  Config cfg_local = cfg;
  cfg_local.gid_index = resolved_gid;

  if (world_rank == 0) {
    fprintf(stdout,
            "[BINDING] rank=%d host=%s dev=%s gid_index=%d IB_DEV_MAP=%s GID_INDEX=%s GID_INDEX_BY_HOST_DEV=%s\n",
            world_rank,
            short_hostname().c_str(),
            dev_name.c_str(),
            r->gid_index,
            env_or_empty("IB_DEV_MAP"),
            env_or_empty("GID_INDEX"),
            env_or_empty("GID_INDEX_BY_HOST_DEV"));
  }

  int num = 0;
  ibv_device** list = ibv_get_device_list(&num);
  CHECK(list && num > 0);

  ibv_device* chosen = nullptr;
  for (int i = 0; i < num; ++i) {
    if (dev_name == ibv_get_device_name(list[i])) {
      chosen = list[i];
      break;
    }
  }
  CHECK(chosen != nullptr);

  r->ctx = ibv_open_device(chosen);
  CHECK(r->ctx != nullptr);
  ibv_free_device_list(list);

  r->pd = ibv_alloc_pd(r->ctx);
  CHECK(r->pd != nullptr);

  const int cq_depth = 4096;
  r->cq_next = ibv_create_cq(r->ctx, cq_depth, nullptr, nullptr, 0);
  r->cq_prev = ibv_create_cq(r->ctx, cq_depth, nullptr, nullptr, 0);
  CHECK(r->cq_next != nullptr && r->cq_prev != nullptr);

  ibv_qp_init_attr q{};
  q.qp_type = IBV_QPT_RC;
  q.sq_sig_all = 0;
  q.send_cq = r->cq_next;
  q.recv_cq = r->cq_next;
  q.cap.max_send_wr = 4096;
  q.cap.max_recv_wr = 4096;
  q.cap.max_send_sge = 1;
  q.cap.max_recv_sge = 1;
  r->qp_next = ibv_create_qp(r->pd, &q);
  CHECK(r->qp_next != nullptr);

  q.send_cq = r->cq_prev;
  q.recv_cq = r->cq_prev;
  r->qp_prev = ibv_create_qp(r->pd, &q);
  CHECK(r->qp_prev != nullptr);

  r->buf_size = std::max((size_t)8, max_size);
  CHECK(posix_memalign((void**)&r->send_buf, 4096, r->buf_size) == 0);
  CHECK(posix_memalign((void**)&r->recv_buf, 4096, r->buf_size) == 0);
  memset(r->send_buf, 0x5a, r->buf_size);
  memset(r->recv_buf, 0, r->buf_size);

  r->mr_send = ibv_reg_mr(r->pd, r->send_buf, r->buf_size, IBV_ACCESS_LOCAL_WRITE);
  r->mr_recv = ibv_reg_mr(r->pd, r->recv_buf, r->buf_size,
                          IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE);
  CHECK(r->mr_send != nullptr && r->mr_recv != nullptr);

  qp_to_init(r->qp_next, cfg_local);
  qp_to_init(r->qp_prev, cfg_local);
}

static void verbs_connect_qps(VerbsRes* r, const Config& cfg, const GroupRuntime& group) {
  int next = ring_next_rank(group.ring_order, group.ring_pos_by_rank, group.group_rank, group.group_size);
  int prev = ring_prev_rank(group.ring_order, group.ring_pos_by_rank, group.group_rank, group.group_size);

  Config cfg_local = cfg;
  cfg_local.gid_index = r->gid_index;

  ConnPair local{};
  local.next = local_conn_info(r->qp_next, r->ctx, cfg_local);
  local.prev = local_conn_info(r->qp_prev, r->ctx, cfg_local);

  std::vector<ConnPair> all((size_t)group.group_size);
  MPI_Allgather(&local, (int)sizeof(ConnPair), MPI_BYTE,
                all.data(), (int)sizeof(ConnPair), MPI_BYTE,
                group.group_comm);

  const ConnInfo& remote_for_next = all[(size_t)next].prev;
  const ConnInfo& remote_for_prev = all[(size_t)prev].next;

  qp_to_rtr(r->qp_next, cfg_local, remote_for_next);
  qp_to_rtr(r->qp_prev, cfg_local, remote_for_prev);
  qp_to_rts(r->qp_next, local.next);
  qp_to_rts(r->qp_prev, local.prev);
}

static void cleanup(VerbsRes* r) {
  if (r->qp_next) ibv_destroy_qp(r->qp_next);
  if (r->qp_prev) ibv_destroy_qp(r->qp_prev);
  if (r->mr_send) ibv_dereg_mr(r->mr_send);
  if (r->mr_recv) ibv_dereg_mr(r->mr_recv);
  if (r->cq_next) ibv_destroy_cq(r->cq_next);
  if (r->cq_prev) ibv_destroy_cq(r->cq_prev);
  if (r->pd) ibv_dealloc_pd(r->pd);
  if (r->ctx) ibv_close_device(r->ctx);
  free(r->send_buf);
  free(r->recv_buf);
}

static void post_recv_on_qp(ibv_qp* qp, ibv_mr* mr, uint8_t* buf, size_t len, uint64_t wr_id) {
  ibv_sge s{};
  s.addr = (uintptr_t)buf;
  s.length = (uint32_t)len;
  s.lkey = mr->lkey;

  ibv_recv_wr wr{};
  wr.wr_id = wr_id;
  wr.sg_list = &s;
  wr.num_sge = 1;

  ibv_recv_wr* bad = nullptr;
  int rc = ibv_post_recv(qp, &wr, &bad);
  if (rc) die("ibv_post_recv", rc);
}

static void post_send_on_qp(ibv_qp* qp, ibv_mr* mr, uint8_t* buf, size_t len, bool signaled, uint64_t wr_id) {
  ibv_sge s{};
  s.addr = (uintptr_t)buf;
  s.length = (uint32_t)len;
  s.lkey = mr->lkey;

  ibv_send_wr wr{};
  wr.wr_id = wr_id;
  wr.sg_list = &s;
  wr.num_sge = 1;
  wr.opcode = IBV_WR_SEND;
  wr.send_flags = signaled ? IBV_SEND_SIGNALED : 0;

  ibv_send_wr* bad = nullptr;
  int rc = ibv_post_send(qp, &wr, &bad);
  if (rc) die("ibv_post_send SEND", rc);
}

static void post_write_on_qp(ibv_qp* qp,
                             ibv_mr* mr,
                             uint8_t* buf,
                             size_t local_off,
                             size_t len,
                             uint64_t remote_addr,
                             uint32_t rkey,
                             bool with_imm,
                             uint32_t imm_data,
                             bool signaled,
                             uint64_t wr_id) {
  ibv_sge s{};
  s.addr = (uintptr_t)(buf + local_off);
  s.length = (uint32_t)len;
  s.lkey = mr->lkey;

  ibv_send_wr wr{};
  wr.wr_id = wr_id;
  wr.sg_list = &s;
  wr.num_sge = 1;
  wr.opcode = with_imm ? IBV_WR_RDMA_WRITE_WITH_IMM : IBV_WR_RDMA_WRITE;
  wr.send_flags = signaled ? IBV_SEND_SIGNALED : 0;
  if (with_imm) wr.imm_data = htonl(imm_data);
  wr.wr.rdma.remote_addr = remote_addr;
  wr.wr.rdma.rkey = rkey;

  ibv_send_wr* bad = nullptr;
  int rc = ibv_post_send(qp, &wr, &bad);
  if (rc) die("ibv_post_send WRITE", rc);
}

struct LatencyStats {
  double p50 = 0.0;
  double p95 = 0.0;
  double p99 = 0.0;
  double min = 0.0;
  double max = 0.0;
  double avg = 0.0;
};

struct RunResult {
  LatencyStats stats;
  std::vector<double> iter_fct_us;
};

static size_t pct_index(size_t n, double p) {
  CHECK(n > 0);
  size_t idx = (size_t)std::ceil(p * (double)n) - 1;
  if (idx >= n) idx = n - 1;
  return idx;
}

static LatencyStats summarize(const std::vector<double>& in) {
  CHECK(!in.empty());
  std::vector<double> s = in;
  std::sort(s.begin(), s.end());
  LatencyStats st;
  st.min = s.front();
  st.max = s.back();
  st.p50 = s[pct_index(s.size(), 0.50)];
  st.p95 = s[pct_index(s.size(), 0.95)];
  st.p99 = s[pct_index(s.size(), 0.99)];
  double sum = 0.0;
  for (double v : s) sum += v;
  st.avg = sum / (double)s.size();
  return st;
}

static int poll_cq_once(ibv_cq* cq, ibv_wc* wc, int cap) {
  int n = ibv_poll_cq(cq, cap, wc);
  if (n < 0) die("ibv_poll_cq", n);
  return n;
}

static bool independent_pair_mode(const Config& cfg, int world_size) {
  return cfg.independent_flows && !cfg.independent_all_flows && (world_size == 8 || world_size == 16);
}

static RunResult run_size_ring(VerbsRes* r,
                               const Config& cfg,
                               const GroupRuntime& group,
                               size_t msg_size,
                               const RemoteMrInfo& remote_next) {
  RunResult out;
  std::vector<double>& samples_us = out.iter_fct_us;
  samples_us.reserve((size_t)cfg.iters);
  const int rank = group.group_rank;
  const int world_size = group.group_size;
  bool active_src = false;
  bool active_dst = false;
  if (independent_pair_mode(cfg, world_size)) {
    if ((rank % 2) == 0) {
      int pair_id = rank / 2;
      active_src = ((cfg.active_src_mask >> (uint32_t)pair_id) & 1u) != 0;
    } else {
      int pair_id = (rank - 1) / 2;
      active_dst = ((cfg.active_src_mask >> (uint32_t)pair_id) & 1u) != 0;
    }
  } else {
    active_src = ((cfg.active_src_mask >> (uint32_t)rank) & 1u) != 0;
    const int prev = ring_prev_rank(group.ring_order, group.ring_pos_by_rank, rank, world_size);
    active_dst = ((cfg.active_src_mask >> (uint32_t)prev) & 1u) != 0;
  }
  const bool use_imm_notify = (cfg.write_notify == Config::WriteNotify::IMM);
  const bool wait_for_data = use_imm_notify && !cfg.no_ack;
  const bool wait_for_ack = use_imm_notify && !cfg.no_ack;

  MPI_Barrier(group.group_comm);

  if (cfg.independent_flows) {
    const int total = cfg.warmup + cfg.iters;
    if (active_src) {
      std::vector<double> t0_sec((size_t)total, 0.0);
      double measure_start_sec = 0.0;
      double measure_end_sec = 0.0;
      uint64_t posted = 0;
      uint64_t completed = 0;
      auto need_signal = [&](uint64_t iter_idx) -> bool {
        if (cfg.sig_interval <= 1) return true;
        if (((iter_idx + 1) % (uint64_t)cfg.sig_interval) == 0) return true;
        if (iter_idx + 1 == (uint64_t)total) return true;
        return false;
      };

      while (completed < (uint64_t)total) {
        while (posted < (uint64_t)total && (posted - completed) < (uint64_t)cfg.inflight) {
          t0_sec[(size_t)posted] = now_sec();
          if ((int)posted == cfg.warmup) measure_start_sec = t0_sec[(size_t)posted];
          size_t off = 0;
          bool signal_this_iter = need_signal(posted);
          while (off < msg_size) {
            size_t chunk = std::min(cfg.write_chunk, msg_size - off);
            bool last_chunk = (off + chunk == msg_size);
            bool signaled = last_chunk && signal_this_iter;
            post_write_on_qp(r->qp_next,
                             r->mr_send,
                             r->send_buf,
                             off,
                             chunk,
                             remote_next.addr + off,
                             remote_next.rkey,
                             false,
                             0,
                             signaled,
                             signaled ? (posted + 1) : 0);
            off += chunk;
          }
          posted++;
        }

        ibv_wc wc_next[16];
        int nn = poll_cq_once(r->cq_next, wc_next, 16);
        if (nn == 0) continue;
        double now = now_sec();
        for (int i = 0; i < nn; ++i) {
          if (wc_next[i].status != IBV_WC_SUCCESS) {
            fprintf(stderr, "independent cq_next CQE error status=%d opcode=%d wr_id=%llu rank=%d\n",
                    wc_next[i].status, wc_next[i].opcode,
                    (unsigned long long)wc_next[i].wr_id, rank);
            MPI_Abort(MPI_COMM_WORLD, 1);
          }
          if (wc_next[i].opcode != IBV_WC_RDMA_WRITE) continue;
          uint64_t done_upto = wc_next[i].wr_id;
          if (done_upto == 0 || done_upto <= completed) continue;
          if (done_upto > posted) done_upto = posted;
          while (completed < done_upto) {
            int iter = (int)completed;
            if (iter >= cfg.warmup) {
              if (cfg.bench == Config::Bench::LATENCY) {
                double fct_us = (now - t0_sec[(size_t)iter]) * 1e6;
                double sample = (cfg.latency_metric == Config::LatencyMetric::RTT2) ? (fct_us * 0.5) : fct_us;
                samples_us.push_back(sample);
              }
              if (iter == total - 1) {
                measure_end_sec = now;
              }
            }
            completed++;
          }
        }
      }

      if (cfg.bench == Config::Bench::BW) {
        CHECK(cfg.iters > 0);
        CHECK(measure_end_sec > measure_start_sec);
        double avg_us = (measure_end_sec - measure_start_sec) * 1e6 / (double)cfg.iters;
        samples_us.assign((size_t)cfg.iters, avg_us);
      }
    }

    MPI_Barrier(group.group_comm);
    if (!samples_us.empty()) {
      out.stats = summarize(samples_us);
    } else {
      samples_us.assign((size_t)cfg.iters, 0.0);
    }
    return out;
  }

  const int total = cfg.warmup + cfg.iters;
  for (int iter = 0; iter < total; ++iter) {
    const uint64_t wrid_ack_recv = 1000000ull + (uint64_t)iter + 1;
    const uint64_t wrid_imm_recv = 2000000ull + (uint64_t)iter + 1;
    const uint64_t wrid_tx = (uint64_t)iter + 1;
    const uint64_t wrid_ack_send = 3000000ull + (uint64_t)iter + 1;

    if (wait_for_ack && active_src) {
      post_recv_on_qp(r->qp_next, r->mr_recv, r->recv_buf, sizeof(uint32_t), wrid_ack_recv);
    }
    if (use_imm_notify && active_dst) {
      post_recv_on_qp(r->qp_prev, r->mr_recv, r->recv_buf, sizeof(uint32_t), wrid_imm_recv);
    }

    double t0 = 0.0;
    if (active_src) {
      t0 = now_sec();
    }

    if (active_src) {
      size_t off = 0;
      while (off < msg_size) {
        size_t chunk = std::min(cfg.write_chunk, msg_size - off);
        bool last_chunk = (off + chunk == msg_size);
        // In latency mode each iteration waits for local TX completion, so the
        // last chunk of every message must be signaled.
        bool signaled = last_chunk;
        post_write_on_qp(r->qp_next,
                         r->mr_send,
                         r->send_buf,
                         off,
                         chunk,
                         remote_next.addr + off,
                         remote_next.rkey,
                         use_imm_notify && last_chunk,
                         (uint32_t)(iter + 1),
                         signaled,
                         signaled ? wrid_tx : 0);
        off += chunk;
      }
    }

    bool got_ack_from_next = (!active_src || !wait_for_ack);
    bool got_data_from_prev = (!active_dst || !wait_for_data);
    bool got_tx_done = !active_src;
    bool ack_send_posted = (!active_dst || !wait_for_ack);
    bool ack_send_done = (!active_dst || !wait_for_ack);

    while (!(got_ack_from_next && got_data_from_prev && got_tx_done && ack_send_posted && ack_send_done)) {
      ibv_wc wc_next[8];
      int nn = poll_cq_once(r->cq_next, wc_next, 8);
      for (int i = 0; i < nn; ++i) {
        if (wc_next[i].status != IBV_WC_SUCCESS) {
          fprintf(stderr, "cq_next CQE error status=%d opcode=%d wr_id=%llu rank=%d iter=%d\n",
                  wc_next[i].status, wc_next[i].opcode,
                  (unsigned long long)wc_next[i].wr_id, rank, iter);
          MPI_Abort(MPI_COMM_WORLD, 1);
        }
        if (wc_next[i].opcode == IBV_WC_RECV) {
          if (wait_for_ack && active_src && wc_next[i].wr_id == wrid_ack_recv) got_ack_from_next = true;
        } else if (wc_next[i].opcode == IBV_WC_RDMA_WRITE) {
          if (active_src && wc_next[i].wr_id == wrid_tx) got_tx_done = true;
        }
      }

      if (use_imm_notify) {
        ibv_wc wc_prev[8];
        int np = poll_cq_once(r->cq_prev, wc_prev, 8);
        for (int i = 0; i < np; ++i) {
          if (wc_prev[i].status != IBV_WC_SUCCESS) {
            fprintf(stderr, "cq_prev CQE error status=%d opcode=%d wr_id=%llu rank=%d iter=%d\n",
                    wc_prev[i].status, wc_prev[i].opcode,
                    (unsigned long long)wc_prev[i].wr_id, rank, iter);
            MPI_Abort(MPI_COMM_WORLD, 1);
          }
          if (wc_prev[i].opcode == IBV_WC_RECV_RDMA_WITH_IMM) {
            if (active_dst && wc_prev[i].wr_id == wrid_imm_recv) {
              if (wait_for_data) got_data_from_prev = true;
              if (wait_for_ack && !ack_send_posted) {
                post_send_on_qp(r->qp_prev, r->mr_recv, r->recv_buf, sizeof(uint32_t), true, wrid_ack_send);
                ack_send_posted = true;
              }
            }
          } else if (wc_prev[i].opcode == IBV_WC_SEND) {
            if (wait_for_ack && active_dst && wc_prev[i].wr_id == wrid_ack_send) ack_send_done = true;
          }
        }
      }
    }

    if (active_src) {
      double t1 = now_sec();
      if (iter >= cfg.warmup) {
        double fct_us = (t1 - t0) * 1e6;
        double sample = (cfg.latency_metric == Config::LatencyMetric::RTT2) ? (fct_us * 0.5) : fct_us;
        samples_us.push_back(sample);
      }
    }

    if (cfg.iter_barrier) {
      MPI_Barrier(MPI_COMM_WORLD);
    }
  }

  MPI_Barrier(group.group_comm);
  if (!samples_us.empty()) {
    out.stats = summarize(samples_us);
  } else {
    samples_us.assign((size_t)cfg.iters, 0.0);
  }
  return out;
}

int main(int argc, char** argv) {
  MPI_Init(&argc, &argv);

  int rank = 0;
  int world_size = 0;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Comm_size(MPI_COMM_WORLD, &world_size);

  Config cfg = parse_args(argc, argv, rank);
  GroupRuntime group = build_group_runtime(cfg, rank, world_size);
  if (!cfg.independent_flows && (group.group_size < 2 || group.group_size > 32 || (group.group_size % 2) != 0)) {
    if (rank == 0) fprintf(stderr, "Ring mode requires each group size to be even and in [2,32].\n");
    MPI_Finalize();
    return 1;
  }
  if (cfg.independent_flows && group.group_size != 4 && group.group_size != 8 && group.group_size != 16) {
    if (rank == 0) fprintf(stderr, "--independent-flows supports per-group size 4, 8, or 16.\n");
    MPI_Finalize();
    return 1;
  }
  if (cfg.single_flow_src >= group.group_size) {
    if (rank == 0) fprintf(stderr, "--single-flow-src must be < group size (%d).\n", group.group_size);
    MPI_Finalize();
    return 1;
  }
  if (!cfg.active_src_mask_user_set) {
    cfg.active_src_mask = (group.group_size == 32) ? 0xFFFFFFFFu : ((1u << (uint32_t)group.group_size) - 1u);
  }

  size_t max_size = 0;
  for (size_t s : cfg.sizes) max_size = std::max(max_size, s);

  VerbsRes r;
  verbs_setup(&r, cfg, max_size, rank, world_size);
  verbs_connect_qps(&r, cfg, group);

  RemoteMrInfo local_mr{};
  local_mr.addr = (uint64_t)(uintptr_t)r.recv_buf;
  local_mr.rkey = r.mr_recv->rkey;
  std::vector<RemoteMrInfo> all_mr((size_t)group.group_size);
  MPI_Allgather(&local_mr, (int)sizeof(local_mr), MPI_BYTE,
                all_mr.data(), (int)sizeof(local_mr), MPI_BYTE,
                group.group_comm);
  int remote_rank_for_write = ring_next_rank(group.ring_order, group.ring_pos_by_rank, group.group_rank, group.group_size);
  if (independent_pair_mode(cfg, group.group_size) && (group.group_rank % 2) == 1) {
    remote_rank_for_write = group.group_rank - 1;
  }
  RemoteMrInfo remote_next = all_mr[(size_t)remote_rank_for_write];

  if (rank == 0) {
    const char* write_notify_str = (cfg.write_notify == Config::WriteNotify::IMM) ? "imm" : "none";
    fprintf(stdout,
            "bench=%s mode=write latency_metric=%s warmup=%d iters=%d inflight=%d sig_interval=%d write_chunk=%zu gid_index=%d single_flow_src=%d active_src_mask=0x%x no_ack=%d write_notify=%s independent_flows=%d independent_all_flows=%d\n",
            cfg.bench == Config::Bench::BW ? "bw" : "latency",
            cfg.latency_metric == Config::LatencyMetric::RTT2 ? "rtt2" : "fct",
            cfg.warmup,
            cfg.iters,
            cfg.inflight,
            cfg.sig_interval,
            cfg.write_chunk,
            r.gid_index,
            cfg.single_flow_src,
            cfg.active_src_mask,
            cfg.no_ack ? 1 : 0,
            write_notify_str,
            cfg.independent_flows ? 1 : 0,
            cfg.independent_all_flows ? 1 : 0);
    fprintf(stdout, "iter_barrier=%d\n", cfg.iter_barrier ? 1 : 0);
    fprintf(stdout, "group_count=%zu world_size=%d\n", cfg.group_nps.empty() ? size_t(1) : cfg.group_nps.size(), world_size);
    if (cfg.bench == Config::Bench::LATENCY) {
      fprintf(stdout, "flow,src_rank,dst_rank,mode,size_bytes,iters,p50_fct_us,p95_fct_us,p99_fct_us,min_fct_us,max_fct_us\n");
    } else {
      fprintf(stdout, "flow,src_rank,dst_rank,mode,size_bytes,iters,avg_Gbps,p50_Gbps,p95_Gbps,max_Gbps\n");
    }
  }

  if (group.group_rank == 0) {
    fprintf(stdout, "group_id=%d group_base=%d group_size=%d ring_order=",
            group.group_id, group.group_base, group.group_size);
    for (int i = 0; i < group.group_size; ++i) {
      fprintf(stdout, "%s%d", i == 0 ? "" : ",", group.ring_order[(size_t)i]);
    }
    fputc('\n', stdout);
    if (!group.dump_iter_fct_path.empty()) {
      fprintf(stdout, "group_id=%d dump_iter_fct=%s\n", group.group_id, group.dump_iter_fct_path.c_str());
    }
    fflush(stdout);
  }

  FILE* dump_iter_fp = nullptr;
  if (group.group_rank == 0 && !group.dump_iter_fct_path.empty()) {
    dump_iter_fp = fopen(group.dump_iter_fct_path.c_str(), "w");
    if (!dump_iter_fp) {
      fprintf(stderr, "fopen(%s) failed errno=%d (%s)\n",
              group.dump_iter_fct_path.c_str(), errno, strerror(errno));
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    fprintf(dump_iter_fp, "iter,jct_us");
    for (int src = 0; src < group.group_size; ++src) {
      fprintf(dump_iter_fp, ",fct_rank%d_us", group.group_world_ranks[(size_t)src]);
    }
    fputc('\n', dump_iter_fp);
  }

  for (size_t msg_size : cfg.sizes) {
    RunResult run = run_size_ring(&r, cfg, group, msg_size, remote_next);
    LatencyStats st = run.stats;

    struct LineOut {
      double p50;
      double p95;
      double p99;
      double min;
      double max;
      double avg;
    } local{};
    std::vector<LineOut> all((size_t)group.group_size);
    std::vector<double> gathered_iter_fct;

    if (!group.dump_iter_fct_path.empty()) {
      CHECK((int)run.iter_fct_us.size() == cfg.iters);
      if (group.group_rank == 0) {
        gathered_iter_fct.resize((size_t)group.group_size * (size_t)cfg.iters, 0.0);
      }
      MPI_Gather(run.iter_fct_us.data(), cfg.iters, MPI_DOUBLE,
                 group.group_rank == 0 ? gathered_iter_fct.data() : nullptr, cfg.iters, MPI_DOUBLE,
                 0, group.group_comm);
    }

    if (cfg.bench == Config::Bench::LATENCY) {
      local = {st.p50, st.p95, st.p99, st.min, st.max, st.avg};
    } else {
      auto to_gbps = [&](double us) -> double {
        if (us <= 0.0) return 0.0;
        return ((double)msg_size * 8.0) / (us * 1000.0);
      };
      local.avg = to_gbps(st.avg);
      local.p50 = to_gbps(st.p50);
      local.p95 = to_gbps(st.p95);
      local.max = to_gbps(st.min);
      local.p99 = 0.0;
      local.min = 0.0;
    }

    MPI_Gather(&local, (int)sizeof(local), MPI_BYTE,
               all.data(), (int)sizeof(local), MPI_BYTE,
               0, group.group_comm);

    if (group.group_rank == 0) {
      if (dump_iter_fp) {
        std::vector<double> rank_fct((size_t)group.group_size, 0.0);
        for (int iter = 0; iter < cfg.iters; ++iter) {
          double jct_us = 0.0;
          for (int src = 0; src < group.group_size; ++src) {
            double fct_us = gathered_iter_fct[(size_t)src * (size_t)cfg.iters + (size_t)iter];
            rank_fct[src] = fct_us;
            if (fct_us > jct_us) jct_us = fct_us;
          }
          fprintf(dump_iter_fp, "%d,%.3f", iter, jct_us);
          for (int src = 0; src < group.group_size; ++src) {
            fprintf(dump_iter_fp, ",%.3f", rank_fct[src]);
          }
          fputc('\n', dump_iter_fp);
        }
        fflush(dump_iter_fp);
      }
      if (independent_pair_mode(cfg, group.group_size)) {
        const int pair_count = group.group_size / 2;
        for (int pair = 0; pair < pair_count; ++pair) {
          if (((cfg.active_src_mask >> (uint32_t)pair) & 1u) == 0) continue;
          int src = pair * 2;
          int dst = src + 1;
          const LineOut& x = all[(size_t)src];
          if (cfg.bench == Config::Bench::LATENCY) {
            fprintf(stdout,
                    "flow,%d,%d,write,%zu,%d,%.3f,%.3f,%.3f,%.3f,%.3f\n",
                    group.group_world_ranks[(size_t)src], group.group_world_ranks[(size_t)dst], msg_size, cfg.iters,
                    x.p50, x.p95, x.p99, x.min, x.max);
          } else {
            fprintf(stdout,
                    "flow,%d,%d,write,%zu,%d,%.3f,%.3f,%.3f,%.3f\n",
                    group.group_world_ranks[(size_t)src], group.group_world_ranks[(size_t)dst], msg_size, cfg.iters,
                    x.avg, x.p50, x.p95, x.max);
          }
        }
      } else {
        for (int src = 0; src < group.group_size; ++src) {
          if (((cfg.active_src_mask >> (uint32_t)src) & 1u) == 0) continue;
          int dst = ring_next_rank(group.ring_order, group.ring_pos_by_rank, src, group.group_size);
          const LineOut& x = all[(size_t)src];
          if (cfg.bench == Config::Bench::LATENCY) {
            fprintf(stdout,
                    "flow,%d,%d,write,%zu,%d,%.3f,%.3f,%.3f,%.3f,%.3f\n",
                    group.group_world_ranks[(size_t)src], group.group_world_ranks[(size_t)dst], msg_size, cfg.iters,
                    x.p50, x.p95, x.p99, x.min, x.max);
          } else {
            fprintf(stdout,
                    "flow,%d,%d,write,%zu,%d,%.3f,%.3f,%.3f,%.3f\n",
                    group.group_world_ranks[(size_t)src], group.group_world_ranks[(size_t)dst], msg_size, cfg.iters,
                    x.avg, x.p50, x.p95, x.max);
          }
        }
      }
      fflush(stdout);
    }
  }

  if (dump_iter_fp) fclose(dump_iter_fp);

  cleanup(&r);
  MPI_Finalize();
  return 0;
}
