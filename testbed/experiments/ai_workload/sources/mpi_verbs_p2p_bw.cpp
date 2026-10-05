#include <mpi.h>
#include <infiniband/verbs.h>
#include <arpa/inet.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cinttypes>
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
  enum class Mode { SEND, WRITE };
  enum class WriteNotify { NONE, IMM };
  enum class LatencyMetric { RTT2, FCT };
  Bench bench = Bench::BW;
  Mode mode = Mode::SEND;
  WriteNotify write_notify = WriteNotify::IMM;
  LatencyMetric latency_metric = LatencyMetric::RTT2;
  std::vector<size_t> sizes;
  int warmup = 200;
  int iters = 2000;
  int inflight = 64;
  int sig_interval = 16;
  size_t write_chunk = 1u << 20;
  int ib_port = 1;
  int gid_index = 3;
};

struct ConnInfo {
  uint16_t lid;
  uint32_t qpn;
  uint32_t psn;
  uint8_t gid[16];
};

struct RemoteMrInfo {
  uint64_t addr;
  uint32_t rkey;
};

struct VerbsRes {
  ibv_context* ctx = nullptr;
  ibv_pd* pd = nullptr;
  ibv_cq* cq = nullptr;
  ibv_qp* qp = nullptr;
  ibv_mr* mr_send = nullptr;
  ibv_mr* mr_recv = nullptr;
  uint8_t* send_buf = nullptr;
  uint8_t* recv_buf = nullptr;
  size_t buf_size = 0;
  enum ibv_mtu active_mtu = IBV_MTU_1024;
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

static bool env_enabled(const char* name) {
  const char* v = getenv(name);
  if (!v || !*v) return false;
  return strcmp(v, "0") != 0;
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

static void usage_and_abort(int rank) {
  if (rank == 0) {
    fprintf(stderr,
      "Usage: mpi_verbs_p2p_bw [--bench bw|latency] --mode send|write [--sizes 8M,4M,...] [--warmup N] [--iters N] "
      "[--inflight N] [--sig-interval N] [--write-chunk X] [--write-notify imm|none] "
      "[--latency-metric rtt2|fct]\n");
  }
  MPI_Abort(MPI_COMM_WORLD, 1);
}

static Config parse_args(int argc, char** argv, int rank) {
  Config c;
  c.sizes = parse_sizes_csv("8M,4M,2M,1M,512K,256K,128K,64K");
  const char* gid_env = getenv("GID_INDEX");
  if (gid_env && *gid_env) c.gid_index = atoi(gid_env);

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
      if (v == "send") c.mode = Config::Mode::SEND;
      else if (v == "write") c.mode = Config::Mode::WRITE;
      else usage_and_abort(rank);
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
    } else {
      usage_and_abort(rank);
    }
  }

  if (c.warmup < 0 || c.iters <= 0 || c.inflight <= 0 || c.sig_interval <= 0 || c.write_chunk == 0) {
    usage_and_abort(rank);
  }
  if (c.bench == Config::Bench::LATENCY) {
    if (c.inflight != 1) {
      if (rank == 0) fprintf(stderr, "Latency benchmark requires --inflight 1\n");
      usage_and_abort(rank);
    }
    if (c.mode == Config::Mode::WRITE && c.write_notify != Config::WriteNotify::IMM) {
      if (rank == 0) fprintf(stderr, "Latency write mode requires --write-notify imm\n");
      usage_and_abort(rank);
    }
  }
  return c;
}

static ibv_context* open_device_by_name(const std::string& want) {
  int num = 0;
  ibv_device** list = ibv_get_device_list(&num);
  CHECK(list != nullptr && num > 0);
  ibv_context* out = nullptr;
  for (int i = 0; i < num; ++i) {
    const char* name = ibv_get_device_name(list[i]);
    if (want == name) {
      out = ibv_open_device(list[i]);
      break;
    }
  }
  ibv_free_device_list(list);
  CHECK(out != nullptr);
  return out;
}

static ConnInfo local_conn_info(VerbsRes* r, const Config& cfg) {
  ConnInfo c{};
  ibv_port_attr attr{};
  int rc = ibv_query_port(r->ctx, cfg.ib_port, &attr);
  if (rc) die("ibv_query_port", rc);
  c.lid = attr.lid;
  c.qpn = r->qp->qp_num;
  c.psn = (uint32_t)(lrand48() & 0xFFFFFF);

  union ibv_gid gid{};
  rc = ibv_query_gid(r->ctx, cfg.ib_port, r->gid_index, &gid);
  if (rc) die("ibv_query_gid", rc);
  memcpy(c.gid, gid.raw, 16);
  return c;
}

static bool gid_is_zero(const uint8_t gid[16]) {
  for (int i = 0; i < 16; ++i) if (gid[i] != 0) return false;
  return true;
}

static void qp_to_init(VerbsRes* r, const Config& cfg) {
  ibv_qp_attr attr{};
  attr.qp_state = IBV_QPS_INIT;
  attr.pkey_index = 0;
  attr.port_num = cfg.ib_port;
  attr.qp_access_flags = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE;
  int flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS;
  int rc = ibv_modify_qp(r->qp, &attr, flags);
  if (rc) die("ibv_modify_qp INIT", rc);
}

static void qp_to_rtr(VerbsRes* r, const Config& cfg, const ConnInfo& remote) {
  ibv_qp_attr attr{};
  attr.qp_state = IBV_QPS_RTR;
  attr.path_mtu = r->active_mtu;
  attr.dest_qp_num = remote.qpn;
  attr.rq_psn = remote.psn;
  attr.max_dest_rd_atomic = 1;
  attr.min_rnr_timer = 12;
  attr.ah_attr.port_num = cfg.ib_port;
  attr.ah_attr.sl = 0;
  attr.ah_attr.src_path_bits = 0;

  bool global = !gid_is_zero(remote.gid);
  if (global) {
    attr.ah_attr.is_global = 1;
    memcpy(&attr.ah_attr.grh.dgid, remote.gid, 16);
    attr.ah_attr.grh.sgid_index = r->gid_index;
    attr.ah_attr.grh.hop_limit = 1;
    attr.ah_attr.dlid = 0;
  } else {
    attr.ah_attr.is_global = 0;
    attr.ah_attr.dlid = remote.lid;
  }

  int flags =
      IBV_QP_STATE |
      IBV_QP_AV |
      IBV_QP_PATH_MTU |
      IBV_QP_DEST_QPN |
      IBV_QP_RQ_PSN |
      IBV_QP_MAX_DEST_RD_ATOMIC |
      IBV_QP_MIN_RNR_TIMER;

  int rc = ibv_modify_qp(r->qp, &attr, flags);
  if (rc) die("ibv_modify_qp RTR", rc);
}

static void qp_to_rts(VerbsRes* r, const ConnInfo& local) {
  ibv_qp_attr attr{};
  attr.qp_state = IBV_QPS_RTS;
  attr.timeout = 14;
  attr.retry_cnt = 7;
  attr.rnr_retry = 7;
  attr.sq_psn = local.psn;
  attr.max_rd_atomic = 1;

  int flags =
      IBV_QP_STATE |
      IBV_QP_TIMEOUT |
      IBV_QP_RETRY_CNT |
      IBV_QP_RNR_RETRY |
      IBV_QP_SQ_PSN |
      IBV_QP_MAX_QP_RD_ATOMIC;

  int rc = ibv_modify_qp(r->qp, &attr, flags);
  if (rc) die("ibv_modify_qp RTS", rc);
}

static void verbs_setup(VerbsRes* r, const Config& cfg, size_t max_size, int world_rank, int world_size) {
  std::string dev_name = pick_device_name(world_rank, world_size);
  std::string host = short_hostname();
  r->gid_index = resolve_gid_index_for_host_dev(dev_name, cfg.gid_index);
  if (env_enabled("IB_BINDING_DEBUG")) {
    fprintf(stderr,
            "[BINDING] rank=%d host=%s dev=%s gid_index=%d IB_DEV_MAP=%s IB_DEV_MAP_BY_HOST=%s GID_INDEX=%s GID_INDEX_BY_HOST_DEV=%s\n",
            world_rank,
            host.c_str(),
            dev_name.c_str(),
            r->gid_index,
            env_or_empty("IB_DEV_MAP"),
            env_or_empty("IB_DEV_MAP_BY_HOST"),
            env_or_empty("GID_INDEX"),
            env_or_empty("GID_INDEX_BY_HOST_DEV"));
  }
  r->ctx = open_device_by_name(dev_name);
  CHECK(r->ctx != nullptr);

  ibv_port_attr p{};
  int rc = ibv_query_port(r->ctx, cfg.ib_port, &p);
  if (rc) die("ibv_query_port", rc);
  r->active_mtu = p.active_mtu;

  r->pd = ibv_alloc_pd(r->ctx);
  CHECK(r->pd != nullptr);

  const int cq_depth = std::max(8192, cfg.inflight * 32);
  r->cq = ibv_create_cq(r->ctx, cq_depth, nullptr, nullptr, 0);
  CHECK(r->cq != nullptr);

  ibv_qp_init_attr q{};
  q.send_cq = r->cq;
  q.recv_cq = r->cq;
  q.qp_type = IBV_QPT_RC;
  q.cap.max_send_wr = std::max(4096, cfg.inflight * 64);
  q.cap.max_recv_wr = std::max(4096, cfg.inflight * 8);
  q.cap.max_send_sge = 1;
  q.cap.max_recv_sge = 1;
  r->qp = ibv_create_qp(r->pd, &q);
  CHECK(r->qp != nullptr);

  r->buf_size = max_size;
  CHECK(posix_memalign((void**)&r->send_buf, 4096, r->buf_size) == 0);
  CHECK(posix_memalign((void**)&r->recv_buf, 4096, r->buf_size) == 0);
  memset(r->send_buf, 0x5a, r->buf_size);
  memset(r->recv_buf, 0, r->buf_size);

  r->mr_send = ibv_reg_mr(r->pd, r->send_buf, r->buf_size, IBV_ACCESS_LOCAL_WRITE);
  r->mr_recv = ibv_reg_mr(r->pd, r->recv_buf, r->buf_size,
                          IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE);
  CHECK(r->mr_send != nullptr && r->mr_recv != nullptr);

  qp_to_init(r, cfg);
}

static void verbs_connect_qp(VerbsRes* r, const Config& cfg, MPI_Comm comm, int rank) {
  ConnInfo local = local_conn_info(r, cfg);
  ConnInfo remote{};
  int peer = 1 - rank;
  MPI_Sendrecv(&local, (int)sizeof(local), MPI_BYTE, peer, 100,
               &remote, (int)sizeof(remote), MPI_BYTE, peer, 100,
               comm, MPI_STATUS_IGNORE);

  qp_to_rtr(r, cfg, remote);
  qp_to_rts(r, local);
}

static void cleanup(VerbsRes* r) {
  if (r->qp) ibv_destroy_qp(r->qp);
  if (r->mr_send) ibv_dereg_mr(r->mr_send);
  if (r->mr_recv) ibv_dereg_mr(r->mr_recv);
  if (r->cq) ibv_destroy_cq(r->cq);
  if (r->pd) ibv_dealloc_pd(r->pd);
  if (r->ctx) ibv_close_device(r->ctx);
  free(r->send_buf);
  free(r->recv_buf);
}

static void post_recv(VerbsRes* r, size_t len, uint64_t wr_id) {
  ibv_sge s{};
  s.addr = (uintptr_t)r->recv_buf;
  s.length = (uint32_t)len;
  s.lkey = r->mr_recv->lkey;

  ibv_recv_wr wr{};
  wr.wr_id = wr_id;
  wr.sg_list = &s;
  wr.num_sge = 1;

  ibv_recv_wr* bad = nullptr;
  int rc = ibv_post_recv(r->qp, &wr, &bad);
  if (rc) die("ibv_post_recv", rc);
}

static void post_send_wr(VerbsRes* r, size_t len, bool signaled, uint64_t wr_id) {
  ibv_sge s{};
  s.addr = (uintptr_t)r->send_buf;
  s.length = (uint32_t)len;
  s.lkey = r->mr_send->lkey;

  ibv_send_wr wr{};
  wr.wr_id = wr_id;
  wr.sg_list = &s;
  wr.num_sge = 1;
  wr.opcode = IBV_WR_SEND;
  wr.send_flags = signaled ? IBV_SEND_SIGNALED : 0;

  ibv_send_wr* bad = nullptr;
  int rc = ibv_post_send(r->qp, &wr, &bad);
  if (rc) die("ibv_post_send SEND", rc);
}

static void post_write_wr(VerbsRes* r,
                          size_t local_off,
                          size_t len,
                          uint64_t remote_addr,
                          uint32_t rkey,
                          bool with_imm,
                          uint32_t imm_data,
                          bool signaled,
                          uint64_t wr_id) {
  ibv_sge s{};
  s.addr = (uintptr_t)(r->send_buf + local_off);
  s.length = (uint32_t)len;
  s.lkey = r->mr_send->lkey;

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
  int rc = ibv_post_send(r->qp, &wr, &bad);
  if (rc) die("ibv_post_send WRITE", rc);
}

static void wait_send_or_write_cqe(VerbsRes* r, uint64_t* acked) {
  while (true) {
    ibv_wc wc[16];
    int n = ibv_poll_cq(r->cq, 16, wc);
    if (n < 0) die("ibv_poll_cq", n);
    if (n == 0) continue;
    for (int i = 0; i < n; ++i) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                wc[i].status, wc[i].opcode, wc[i].wr_id);
        MPI_Abort(MPI_COMM_WORLD, 1);
      }
      if (wc[i].opcode == IBV_WC_RECV || wc[i].opcode == IBV_WC_RECV_RDMA_WITH_IMM) continue;
      if (wc[i].wr_id > *acked) *acked = wc[i].wr_id;
      return;
    }
  }
}

static void run_sender_send(VerbsRes* r, size_t msg_size, int count, const Config& cfg) {
  uint64_t posted = 0;
  uint64_t acked = 0;

  while (acked < (uint64_t)count) {
    while (posted < (uint64_t)count && (posted - acked) < (uint64_t)cfg.inflight) {
      uint64_t msg_id = posted + 1;
      bool signaled = (msg_id % (uint64_t)cfg.sig_interval == 0) || (msg_id == (uint64_t)count);
      post_send_wr(r, msg_size, signaled, signaled ? msg_id : 0);
      posted++;
    }
    if (acked < posted) wait_send_or_write_cqe(r, &acked);
  }
}

static void run_receiver_send(VerbsRes* r, size_t msg_size, int count, const Config& cfg) {
  int depth = std::min(count, cfg.inflight + 32);
  int posted = 0;
  for (int i = 0; i < depth; ++i) {
    post_recv(r, msg_size, (uint64_t)i + 1);
    posted++;
  }

  int received = 0;
  while (received < count) {
    ibv_wc wc[32];
    int n = ibv_poll_cq(r->cq, 32, wc);
    if (n < 0) die("ibv_poll_cq", n);
    if (n == 0) continue;
    for (int i = 0; i < n; ++i) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "Recv CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                wc[i].status, wc[i].opcode, wc[i].wr_id);
        MPI_Abort(MPI_COMM_WORLD, 1);
      }
      if (wc[i].opcode == IBV_WC_RECV || wc[i].opcode == IBV_WC_RECV_RDMA_WITH_IMM) {
        received++;
        if (posted < count) {
          post_recv(r, msg_size, (uint64_t)posted + 1);
          posted++;
        }
      }
    }
  }
}

static void run_sender_write(VerbsRes* r,
                             size_t msg_size,
                             int count,
                             const Config& cfg,
                             const RemoteMrInfo& remote) {
  uint64_t posted_msgs = 0;
  uint64_t acked_msgs = 0;

  while (acked_msgs < (uint64_t)count) {
    while (posted_msgs < (uint64_t)count && (posted_msgs - acked_msgs) < (uint64_t)cfg.inflight) {
      uint64_t msg_id = posted_msgs + 1;
      size_t off = 0;
      while (off < msg_size) {
        size_t chunk = std::min(cfg.write_chunk, msg_size - off);
        bool last_chunk = (off + chunk == msg_size);
        bool with_imm = last_chunk && cfg.write_notify == Config::WriteNotify::IMM;
        bool signaled = last_chunk && ((msg_id % (uint64_t)cfg.sig_interval == 0) || (msg_id == (uint64_t)count));
        post_write_wr(r,
                      off,
                      chunk,
                      remote.addr + off,
                      remote.rkey,
                      with_imm,
                      (uint32_t)msg_id,
                      signaled,
                      signaled ? msg_id : 0);
        off += chunk;
      }
      posted_msgs++;
    }
    if (acked_msgs < posted_msgs) wait_send_or_write_cqe(r, &acked_msgs);
  }
}

static void run_receiver_write_imm(VerbsRes* r, int count, const Config& cfg) {
  int depth = std::min(count, cfg.inflight + 32);
  int posted = 0;
  for (int i = 0; i < depth; ++i) {
    post_recv(r, 4, (uint64_t)i + 1);
    posted++;
  }

  std::vector<uint8_t> seen((size_t)count + 1, 0);
  int received = 0;
  while (received < count) {
    ibv_wc wc[32];
    int n = ibv_poll_cq(r->cq, 32, wc);
    if (n < 0) die("ibv_poll_cq", n);
    if (n == 0) continue;
    for (int i = 0; i < n; ++i) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "Write recv CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                wc[i].status, wc[i].opcode, wc[i].wr_id);
        MPI_Abort(MPI_COMM_WORLD, 1);
      }
      if (wc[i].opcode != IBV_WC_RECV_RDMA_WITH_IMM) continue;
      uint32_t seq = ntohl(wc[i].imm_data);
      if (seq == 0 || seq > (uint32_t)count) {
        fprintf(stderr, "Invalid imm seq=%u count=%d\n", seq, count);
        MPI_Abort(MPI_COMM_WORLD, 1);
      }
      if (!seen[seq]) {
        seen[seq] = 1;
        received++;
      }
      if (posted < count) {
        post_recv(r, 4, (uint64_t)posted + 1);
        posted++;
      }
    }
  }
}

static void wait_for_send_completion(VerbsRes* r, uint64_t want_wr_id) {
  while (true) {
    ibv_wc wc[8];
    int n = ibv_poll_cq(r->cq, 8, wc);
    if (n < 0) die("ibv_poll_cq", n);
    if (n == 0) continue;
    for (int i = 0; i < n; ++i) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                wc[i].status, wc[i].opcode, wc[i].wr_id);
        MPI_Abort(MPI_COMM_WORLD, 1);
      }
      if (wc[i].opcode == IBV_WC_RECV || wc[i].opcode == IBV_WC_RECV_RDMA_WITH_IMM) continue;
      if (wc[i].wr_id == want_wr_id) return;
    }
  }
}

static void drain_cq(VerbsRes* r) {
  while (true) {
    ibv_wc wc[32];
    int n = ibv_poll_cq(r->cq, 32, wc);
    if (n < 0) die("ibv_poll_cq", n);
    if (n == 0) break;
    for (int i = 0; i < n; ++i) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "Drain CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                wc[i].status, wc[i].opcode, wc[i].wr_id);
        MPI_Abort(MPI_COMM_WORLD, 1);
      }
    }
  }
}

static void wait_for_recv_completion(VerbsRes* r, int expect_opcode) {
  while (true) {
    ibv_wc wc[8];
    int n = ibv_poll_cq(r->cq, 8, wc);
    if (n < 0) die("ibv_poll_cq", n);
    if (n == 0) continue;
    for (int i = 0; i < n; ++i) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "Recv CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                wc[i].status, wc[i].opcode, wc[i].wr_id);
        MPI_Abort(MPI_COMM_WORLD, 1);
      }
      if (wc[i].opcode == expect_opcode) return;
      if (wc[i].opcode == IBV_WC_RECV || wc[i].opcode == IBV_WC_RECV_RDMA_WITH_IMM) continue;
    }
  }
}

static void post_ack_send(VerbsRes* r, uint32_t seq) {
  memcpy(r->send_buf, &seq, sizeof(seq));
  post_send_wr(r, sizeof(seq), true, (uint64_t)seq);
}

struct LatencyStats {
  double p50_us = 0.0;
  double p95_us = 0.0;
  double p99_us = 0.0;
  double min_us = 0.0;
  double max_us = 0.0;
};

static size_t pct_index(size_t n, double p) {
  CHECK(n > 0);
  size_t idx = (size_t)std::ceil(p * (double)n) - 1;
  if (idx >= n) idx = n - 1;
  return idx;
}

static LatencyStats summarize_latency_us(std::vector<double> samples_us) {
  CHECK(!samples_us.empty());
  std::sort(samples_us.begin(), samples_us.end());
  LatencyStats s;
  s.min_us = samples_us.front();
  s.max_us = samples_us.back();
  s.p50_us = samples_us[pct_index(samples_us.size(), 0.50)];
  s.p95_us = samples_us[pct_index(samples_us.size(), 0.95)];
  s.p99_us = samples_us[pct_index(samples_us.size(), 0.99)];
  return s;
}

struct LinearFit {
  bool ok = false;
  double intercept_us = 0.0;
  double slope_us_per_byte = 0.0;
};

static LinearFit fit_line_size_latency(const std::vector<size_t>& sizes,
                                       const std::vector<double>& lat_us) {
  LinearFit f;
  CHECK(sizes.size() == lat_us.size());
  if (sizes.size() < 2) return f;

  double n = (double)sizes.size();
  double sx = 0.0;
  double sy = 0.0;
  double sxx = 0.0;
  double sxy = 0.0;
  for (size_t i = 0; i < sizes.size(); ++i) {
    double x = (double)sizes[i];
    double y = lat_us[i];
    sx += x;
    sy += y;
    sxx += x * x;
    sxy += x * y;
  }

  double den = n * sxx - sx * sx;
  if (std::abs(den) < 1e-18) return f;

  f.slope_us_per_byte = (n * sxy - sx * sy) / den;
  f.intercept_us = (sy - f.slope_us_per_byte * sx) / n;
  f.ok = true;
  return f;
}

static LatencyStats run_size_latency(VerbsRes* r,
                                     const Config& cfg,
                                     size_t msg_size,
                                     MPI_Comm comm,
                                     int rank,
                                     const RemoteMrInfo& remote) {
  std::vector<double> samples_us;
  if (rank == 0) samples_us.reserve((size_t)cfg.iters);

  MPI_Barrier(comm);
  drain_cq(r);
  MPI_Barrier(comm);

  int total = cfg.warmup + cfg.iters;
  int recv_depth = std::min(total, 128);
  int posted_rx = 0;

  if (rank == 0) {
    for (int i = 0; i < recv_depth; ++i) {
      post_recv(r, sizeof(uint32_t), (uint64_t)i + 1);
      posted_rx++;
    }
  } else {
    size_t rx_len = (cfg.mode == Config::Mode::SEND) ? msg_size : sizeof(uint32_t);
    for (int i = 0; i < recv_depth; ++i) {
      post_recv(r, rx_len, (uint64_t)i + 1);
      posted_rx++;
    }
  }

  for (int iter = 0; iter < total; ++iter) {
    if (rank == 0) {
      double t0 = now_sec();

      if (cfg.mode == Config::Mode::SEND) {
        post_send_wr(r, msg_size, true, (uint64_t)iter + 1);
      } else {
        size_t off = 0;
        while (off < msg_size) {
          size_t chunk = std::min(cfg.write_chunk, msg_size - off);
          bool last_chunk = (off + chunk == msg_size);
          post_write_wr(r,
                        off,
                        chunk,
                        remote.addr + off,
                        remote.rkey,
                        last_chunk,
                        (uint32_t)iter + 1,
                        last_chunk,
                        last_chunk ? (uint64_t)iter + 1 : 0);
          off += chunk;
        }
      }

      bool got_ack = false;
      bool got_tx = false;
      while (!got_ack || !got_tx) {
        ibv_wc wc[8];
        int n = ibv_poll_cq(r->cq, 8, wc);
        if (n < 0) die("ibv_poll_cq", n);
        if (n == 0) continue;
        for (int i = 0; i < n; ++i) {
          if (wc[i].status != IBV_WC_SUCCESS) {
            fprintf(stderr, "CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                    wc[i].status, wc[i].opcode, wc[i].wr_id);
            MPI_Abort(MPI_COMM_WORLD, 1);
          }
          if (wc[i].opcode == IBV_WC_RECV) {
            got_ack = true;
            if (posted_rx < total) {
              post_recv(r, sizeof(uint32_t), (uint64_t)posted_rx + 1);
              posted_rx++;
            }
          } else if (wc[i].opcode == IBV_WC_SEND || wc[i].opcode == IBV_WC_RDMA_WRITE) {
            if (wc[i].wr_id == (uint64_t)iter + 1) got_tx = true;
          }
        }
      }
      double t1 = now_sec();
      if (iter >= cfg.warmup) {
        double fct_us = (t1 - t0) * 1e6;
        double sample = (cfg.latency_metric == Config::LatencyMetric::RTT2) ? (fct_us * 0.5) : fct_us;
        samples_us.push_back(sample);
      }
    } else {
      static uint64_t receiver_send_done = 0;
      if (iter == 0) receiver_send_done = 0;

      bool got_data = false;
      int expect_opcode = (cfg.mode == Config::Mode::SEND) ? IBV_WC_RECV : IBV_WC_RECV_RDMA_WITH_IMM;
      while (!got_data) {
        ibv_wc wc[8];
        int n = ibv_poll_cq(r->cq, 8, wc);
        if (n < 0) die("ibv_poll_cq", n);
        if (n == 0) continue;
        for (int i = 0; i < n; ++i) {
          if (wc[i].status != IBV_WC_SUCCESS) {
            fprintf(stderr, "CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                    wc[i].status, wc[i].opcode, wc[i].wr_id);
            MPI_Abort(MPI_COMM_WORLD, 1);
          }
          if (wc[i].opcode == IBV_WC_SEND || wc[i].opcode == IBV_WC_RDMA_WRITE) {
            if (wc[i].wr_id > receiver_send_done) receiver_send_done = wc[i].wr_id;
            continue;
          }
          if (wc[i].opcode == expect_opcode) {
            got_data = true;
            if (posted_rx < total) {
              size_t rx_len = (cfg.mode == Config::Mode::SEND) ? msg_size : sizeof(uint32_t);
              post_recv(r, rx_len, (uint64_t)posted_rx + 1);
              posted_rx++;
            }
          }
        }
      }
      post_ack_send(r, (uint32_t)iter + 1);
      while (receiver_send_done < (uint64_t)iter + 1) {
        ibv_wc wc[8];
        int n = ibv_poll_cq(r->cq, 8, wc);
        if (n < 0) die("ibv_poll_cq", n);
        if (n == 0) continue;
        for (int i = 0; i < n; ++i) {
          if (wc[i].status != IBV_WC_SUCCESS) {
            fprintf(stderr, "CQE error status=%d opcode=%d wr_id=%" PRIu64 "\n",
                    wc[i].status, wc[i].opcode, wc[i].wr_id);
            MPI_Abort(MPI_COMM_WORLD, 1);
          }
          if (wc[i].opcode == IBV_WC_SEND || wc[i].opcode == IBV_WC_RDMA_WRITE) {
            if (wc[i].wr_id > receiver_send_done) receiver_send_done = wc[i].wr_id;
          }
        }
      }
    }
  }

  MPI_Barrier(comm);
  LatencyStats local{};
  if (rank == 0) local = summarize_latency_us(samples_us);
  MPI_Bcast(&local, (int)sizeof(local), MPI_BYTE, 0, comm);
  return local;
}

static double run_size_bw(VerbsRes* r,
                          const Config& cfg,
                          size_t msg_size,
                          MPI_Comm comm,
                          int rank,
                          const RemoteMrInfo& remote) {
  MPI_Barrier(comm);
  if (cfg.mode == Config::Mode::SEND) {
    if (rank == 0) run_sender_send(r, msg_size, cfg.warmup, cfg);
    else run_receiver_send(r, msg_size, cfg.warmup, cfg);
  } else {
    if (rank == 0) run_sender_write(r, msg_size, cfg.warmup, cfg, remote);
    else if (cfg.write_notify == Config::WriteNotify::IMM) run_receiver_write_imm(r, cfg.warmup, cfg);
  }
  MPI_Barrier(comm);

  double t0 = 0.0;
  double t1 = 0.0;
  if (cfg.mode == Config::Mode::SEND) {
    if (rank == 0) {
      t0 = now_sec();
      run_sender_send(r, msg_size, cfg.iters, cfg);
      t1 = now_sec();
    } else {
      run_receiver_send(r, msg_size, cfg.iters, cfg);
    }
  } else {
    if (rank == 0) {
      t0 = now_sec();
      run_sender_write(r, msg_size, cfg.iters, cfg, remote);
      t1 = now_sec();
    } else if (cfg.write_notify == Config::WriteNotify::IMM) {
      run_receiver_write_imm(r, cfg.iters, cfg);
    }
  }

  MPI_Barrier(comm);
  double elapsed = (rank == 0) ? (t1 - t0) : 0.0;
  MPI_Bcast(&elapsed, 1, MPI_DOUBLE, 0, comm);
  return elapsed;
}

int main(int argc, char** argv) {
  MPI_Init(&argc, &argv);

  int rank = 0, size = 0;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Comm_size(MPI_COMM_WORLD, &size);

  if (size != 2) {
    if (rank == 0) fprintf(stderr, "This benchmark requires exactly 2 MPI ranks.\n");
    MPI_Finalize();
    return 1;
  }

  Config cfg = parse_args(argc, argv, rank);

  size_t max_size = 0;
  for (size_t s : cfg.sizes) max_size = std::max(max_size, s);

  VerbsRes r;
  verbs_setup(&r, cfg, max_size, rank, size);
  verbs_connect_qp(&r, cfg, MPI_COMM_WORLD, rank);

  RemoteMrInfo local_mr{};
  local_mr.addr = (uint64_t)(uintptr_t)r.recv_buf;
  local_mr.rkey = r.mr_recv->rkey;
  RemoteMrInfo remote_mr{};
  int peer = 1 - rank;
  MPI_Sendrecv(&local_mr, (int)sizeof(local_mr), MPI_BYTE, peer, 200,
               &remote_mr, (int)sizeof(remote_mr), MPI_BYTE, peer, 200,
               MPI_COMM_WORLD, MPI_STATUS_IGNORE);

  if (rank == 0) {
    fprintf(stdout,
            "bench=%s mode=%s latency_metric=%s warmup=%d iters=%d inflight=%d sig_interval=%d write_chunk=%zu gid_index=%d\n",
            cfg.bench == Config::Bench::BW ? "bw" : "latency",
            cfg.mode == Config::Mode::SEND ? "send" : "write",
            cfg.latency_metric == Config::LatencyMetric::RTT2 ? "rtt2" : "fct",
            cfg.warmup,
            cfg.iters,
            cfg.inflight,
            cfg.sig_interval,
            cfg.write_chunk,
            r.gid_index);
    fprintf(stdout,
            "write_notify=%s\n",
            cfg.write_notify == Config::WriteNotify::IMM ? "imm" : "none");
    if (cfg.bench == Config::Bench::BW) {
      fprintf(stdout,
              "mode,size,inflight,sig_interval,write_chunk,write_notify,avg_Gbps,p50_Gbps,p95_Gbps,max_Gbps\n");
    } else {
      const char* metric_col = cfg.latency_metric == Config::LatencyMetric::RTT2 ? "rtt2_us" : "fct_us";
      fprintf(stdout,
              "mode,size_bytes,iters,p50_%s,p95_%s,p99_%s,min_%s,max_%s\n",
              metric_col, metric_col, metric_col, metric_col, metric_col);
    }
  }

  std::vector<size_t> fit_sizes;
  std::vector<double> fit_p50_us;
  for (size_t msg_size : cfg.sizes) {
    if (cfg.bench == Config::Bench::BW) {
      double elapsed = run_size_bw(&r, cfg, msg_size, MPI_COMM_WORLD, rank, remote_mr);
      if (rank == 0) {
        double avg_gbps = (double)msg_size * (double)cfg.iters * 8.0 / elapsed / 1e9;
        fprintf(stdout,
                "%s,%zu,%d,%d,%zu,%s,%.3f,%.3f,%.3f,%.3f\n",
                cfg.mode == Config::Mode::SEND ? "send" : "write",
                msg_size,
                cfg.inflight,
                cfg.sig_interval,
                cfg.write_chunk,
                cfg.write_notify == Config::WriteNotify::IMM ? "imm" : "none",
                avg_gbps,
                avg_gbps,
                avg_gbps,
                avg_gbps);
        fflush(stdout);
      }
    } else {
      LatencyStats st = run_size_latency(&r, cfg, msg_size, MPI_COMM_WORLD, rank, remote_mr);
      if (rank == 0) {
        fit_sizes.push_back(msg_size);
        fit_p50_us.push_back(st.p50_us);
        fprintf(stdout,
                "%s,%zu,%d,%.3f,%.3f,%.3f,%.3f,%.3f\n",
                cfg.mode == Config::Mode::SEND ? "send" : "write",
                msg_size,
                cfg.iters,
                st.p50_us,
                st.p95_us,
                st.p99_us,
                st.min_us,
                st.max_us);
        fflush(stdout);
      }
    }
  }

  if (rank == 0 && cfg.bench == Config::Bench::LATENCY) {
    LinearFit fit = fit_line_size_latency(fit_sizes, fit_p50_us);
    if (fit.ok) {
      double eff_gbps = (fit.slope_us_per_byte > 0.0) ? (8.0 / fit.slope_us_per_byte) : 0.0;
      fprintf(stdout,
              "fit,model,p50_%s=a+b*size,a_us=%.3f,b_us_per_byte=%.9f,effective_gbps=%.3f\n",
              cfg.latency_metric == Config::LatencyMetric::RTT2 ? "rtt2" : "fct",
              fit.intercept_us,
              fit.slope_us_per_byte,
              eff_gbps);
      for (size_t i = 0; i < fit_sizes.size(); ++i) {
        double y = fit_p50_us[i];
        double fixed_pct = (y > 0.0) ? (fit.intercept_us / y * 100.0) : 0.0;
        if (fixed_pct < 0.0) fixed_pct = 0.0;
        if (fixed_pct > 100.0) fixed_pct = 100.0;
        fprintf(stdout,
                "fit,share,size=%zu,p50_us=%.3f,fixed_share_pct=%.2f\n",
                fit_sizes[i],
                y,
                fixed_pct);
      }
      fflush(stdout);
    }
  }

  cleanup(&r);
  MPI_Finalize();
  return 0;
}
