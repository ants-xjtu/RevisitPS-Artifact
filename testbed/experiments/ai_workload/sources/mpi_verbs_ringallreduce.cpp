#include <mpi.h>
#include <infiniband/verbs.h>
#include <rdma/rdma_cma.h>
#include <arpa/inet.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cmath>
#include <ctime>
#include <unistd.h>

#include <string>
#include <vector>
#include <algorithm>
#include <map>
#include <sstream>
#include <limits>
#include <numeric>

#define WRID_MASK 0xF0000000ULL
#define WRID_SEND 0x50000000ULL
#define WRID_RECV 0x60000000ULL
#define WRID_PEER_SHIFT 16
#define WRID_PEER_MASK 0x0FFFULL
#define WRID_CHUNK_MASK 0xFFFFULL

#define CHECK(x) do { if (!(x)) { \
  fprintf(stderr, "CHECK failed at %s:%d : %s\n", __FILE__, __LINE__, #x); \
  exit(1); } } while(0)

#ifndef CQE
#define CQE 8192
#endif

#define RDMA_BASE_PORT 18515

static inline double now_sec() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

enum bench_mode_t {
  BENCH_BW = 0,
  BENCH_JCT = 1,
  BENCH_STREAM = 2,
};

enum jct_mode_t {
  JCT_MODE_SAFE = 0,
  JCT_MODE_PERFORMANCE = 1,
};

static bool g_auto_port_probe = false;
static bool g_dev_names_ready = false;
static std::vector<std::string> g_dev_names;
static bool g_jct_sync_recvs = false;
static jct_mode_t g_jct_mode = JCT_MODE_SAFE;
static int g_peer_batch = 0;
static int g_inflight_per_peer = 1;
static int g_signal_interval = 1;
static size_t g_chunk_bytes = 65536;
static bool g_phase_timing = false;
static bool g_stream_iter_barrier = true;
static bool g_stream_chunked_exchange = false;
static int g_stream_window = 1;
static bool g_stream_start_barrier = true;

static inline uint64_t make_wr_id(uint64_t kind, int peer, int chunk) {
  return kind | (((uint64_t)peer & WRID_PEER_MASK) << WRID_PEER_SHIFT) |
         ((uint64_t)chunk & WRID_CHUNK_MASK);
}

static inline int wr_id_peer(uint64_t wr_id) {
  return (int)((wr_id >> WRID_PEER_SHIFT) & WRID_PEER_MASK);
}

static inline int wr_id_chunk(uint64_t wr_id) {
  return (int)(wr_id & WRID_CHUNK_MASK);
}

static void die(const char* what, int rc) {
  fprintf(stderr, "%s failed rc=%d (errno=%d: %s)\n", what, rc, errno, strerror(errno));
  exit(1);
}

struct verbs_ctx_t {
  int world_rank = 0;
  int world_size = 0;
  int rank = 0;
  int size = 0;
  int group_id = 0;
  int group_rank = 0;
  int group_size = 0;
  std::vector<int> group_world_ranks;
  MPI_Comm group_comm = MPI_COMM_NULL;

  // device identity
  std::string dev_name;
  int local_rank = 0;
  uint32_t local_ip = 0;  // network byte order
  int gid_index = 3;
  union ibv_gid gid;
  ibv_context* ibv_ctx = nullptr;

  // rdma_cm resources
  rdma_event_channel* ec = nullptr;
  rdma_cm_id* listen_id = nullptr;

  // per-peer connections
  std::vector<rdma_cm_id*> cm_ids;  // cm_ids[peer]
  std::vector<ibv_qp*> qps;         // qps[peer] = cm_ids[peer]->qp

  // shared resources (created after first connection)
  ibv_pd* pd = nullptr;
  ibv_cq* cq = nullptr;

  // buffers
  uint8_t* send_buf = nullptr;
  uint8_t* recv_buf = nullptr;
  size_t msg_size = 4096;
  size_t buf_size = 0;
  ibv_mr* mr_send = nullptr;
  ibv_mr* mr_recv = nullptr;

  // IP addresses of all ranks (gathered via MPI)
  std::vector<uint32_t> all_ips;  // network byte order
};

struct iter_phase_t {
  double post_recv_us = 0.0;
  double barrier_us = 0.0;
  double post_send_us = 0.0;
  double poll_cq_us = 0.0;
  std::vector<double> peer_send_us;
  std::vector<double> msg_send_us;
  std::vector<int> msg_dst_world;
};

static void build_counts_displs(int total_count, int size,
                                std::vector<int>& counts,
                                std::vector<int>& displs) {
  counts.assign(size, 0);
  displs.assign(size, 0);
  int base = total_count / size;
  int rem = total_count % size;
  int disp = 0;
  for (int i = 0; i < size; i++) {
    counts[i] = base + (i < rem ? 1 : 0);
    displs[i] = disp;
    disp += counts[i];
  }
}

/* -------------------------- helpers -------------------------- */
static bool peer_in_group(const verbs_ctx_t* v, int peer) {
  int base = v->group_id * v->group_size;
  return peer >= base && peer < base + v->group_size;
}

static std::vector<std::string> list_matched_devices(const char* prefix) {
  int num_devs = 0;
  ibv_device** dev_list = ibv_get_device_list(&num_devs);
  CHECK(dev_list && num_devs > 0);

  size_t prelen = strlen(prefix);
  std::vector<std::string> names;
  for (int i = 0; i < num_devs; i++) {
    const char* name = ibv_get_device_name(dev_list[i]);
    if (!strncmp(name, prefix, prelen)) names.emplace_back(name);
  }
  ibv_free_device_list(dev_list);

  std::sort(names.begin(), names.end());
  return names;
}

static std::vector<std::string> parse_dev_list_env(const char* text) {
  std::vector<std::string> out;
  if (!text || !*text) return out;
  std::stringstream ss(text);
  std::string tok;
  while (std::getline(ss, tok, ',')) {
    if (!tok.empty()) out.push_back(tok);
  }
  return out;
}

static std::string get_short_hostname() {
  char buf[256];
  if (gethostname(buf, sizeof(buf)) != 0) return "";
  buf[sizeof(buf) - 1] = '\0';
  std::string host(buf);
  size_t dot = host.find('.');
  if (dot != std::string::npos) host.resize(dot);
  return host;
}

static std::vector<std::string> parse_host_dev_map_for_host(const char* text, const std::string& host) {
  std::vector<std::string> out;
  if (!text || !*text || host.empty()) return out;

  std::string map_text(text);
  for (char& c : map_text) {
    if (c == '|') c = ';';
  }

  std::stringstream ss(map_text);
  std::string entry;
  while (std::getline(ss, entry, ';')) {
    if (entry.empty()) continue;
    size_t pos = entry.find(':');
    if (pos == std::string::npos || pos == 0 || pos + 1 >= entry.size()) continue;
    std::string h = entry.substr(0, pos);
    if (h != host) continue;
    std::string dev_csv = entry.substr(pos + 1);
    return parse_dev_list_env(dev_csv.c_str());
  }
  return out;
}

static bool parse_host_int_map_for_host(const char* text, const std::string& host, int* out_val) {
  if (!text || !*text || host.empty() || !out_val) return false;

  std::string map_text(text);
  for (char& c : map_text) {
    if (c == '|') c = ';';
  }

  std::stringstream ss(map_text);
  std::string entry;
  while (std::getline(ss, entry, ';')) {
    if (entry.empty()) continue;
    size_t pos = entry.find(':');
    if (pos == std::string::npos || pos == 0 || pos + 1 >= entry.size()) continue;
    std::string h = entry.substr(0, pos);
    if (h != host) continue;
    std::string val = entry.substr(pos + 1);
    *out_val = atoi(val.c_str());
    return true;
  }
  return false;
}

static bool parse_host_dev_int_map(const char* text, const std::string& host,
                                   const std::string& dev, int* out_val) {
  if (!text || !*text || host.empty() || dev.empty() || !out_val) return false;

  std::string map_text(text);
  for (char& c : map_text) {
    if (c == '|') c = ';';
  }

  std::stringstream ss(map_text);
  std::string entry;
  while (std::getline(ss, entry, ';')) {
    if (entry.empty()) continue;
    size_t pos = entry.find(':');
    if (pos == std::string::npos || pos == 0 || pos + 1 >= entry.size()) continue;
    std::string h = entry.substr(0, pos);
    if (h != host) continue;
    std::string dev_map = entry.substr(pos + 1);
    std::stringstream ds(dev_map);
    std::string pair;
    while (std::getline(ds, pair, ',')) {
      if (pair.empty()) continue;
      size_t eq = pair.find('=');
      if (eq == std::string::npos || eq == 0 || eq + 1 >= pair.size()) continue;
      std::string d = pair.substr(0, eq);
      if (d != dev) continue;
      std::string v = pair.substr(eq + 1);
      *out_val = atoi(v.c_str());
      return true;
    }
  }
  return false;
}

static bool is_port_active(const std::string& dev_name) {
  int num_devs = 0;
  ibv_device** dev_list = ibv_get_device_list(&num_devs);
  if (!dev_list || num_devs <= 0) return false;

  ibv_device* dev = nullptr;
  for (int i = 0; i < num_devs; i++) {
    if (dev_name == ibv_get_device_name(dev_list[i])) {
      dev = dev_list[i];
      break;
    }
  }
  if (!dev) {
    ibv_free_device_list(dev_list);
    return false;
  }

  ibv_context* ctx = ibv_open_device(dev);
  if (!ctx) {
    ibv_free_device_list(dev_list);
    return false;
  }

  ibv_port_attr pa;
  memset(&pa, 0, sizeof(pa));
  int rc = ibv_query_port(ctx, 1, &pa);
  ibv_close_device(ctx);
  ibv_free_device_list(dev_list);
  if (rc != 0) return false;
  return pa.state == IBV_PORT_ACTIVE;
}

static const std::vector<std::string>& get_candidate_devices() {
  if (g_dev_names_ready) return g_dev_names;
  g_dev_names_ready = true;

  std::vector<std::string> names;
  const char* dev_list_env = getenv("IB_DEV_LIST");
  if (dev_list_env && *dev_list_env) {
    names = parse_dev_list_env(dev_list_env);
  } else {
    const char* prefix = getenv("IB_DEV_PREFIX");
    if (!prefix || !*prefix) prefix = "mlx5_";
    names = list_matched_devices(prefix);
  }
  if (!g_auto_port_probe) {
    g_dev_names = names;
    return g_dev_names;
  }

  for (const auto& name : names) {
    if (is_port_active(name)) g_dev_names.push_back(name);
  }
  return g_dev_names;
}

static std::string pick_devname_for_local_rank(int local_rank) {
  const char* by_host_env = getenv("IB_DEV_MAP_BY_HOST");
  if (by_host_env && *by_host_env) {
    std::string host = get_short_hostname();
    auto mapped = parse_host_dev_map_for_host(by_host_env, host);
    if (!mapped.empty()) {
      int idx = local_rank % (int)mapped.size();
      return mapped[idx];
    }
  }

  auto names = get_candidate_devices();
  if (names.empty()) {
    int num_devs = 0;
    ibv_device** dev_list = ibv_get_device_list(&num_devs);
    CHECK(dev_list && num_devs > 0);
    std::string fallback = ibv_get_device_name(dev_list[0]);
    ibv_free_device_list(dev_list);
    return fallback;
  }

  // Map local_rank to NIC: 0->mlx5_0, 1->mlx5_1, 2->mlx5_2, 3->mlx5_3
  // Note: same-NIC port communication requires static ARP entries
  int idx = local_rank % 4;
  if (idx >= (int)names.size()) idx = 0;
  return names[idx];
}

static int get_host_local_rank() {
  MPI_Comm local_comm = MPI_COMM_NULL;
  int rc = MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, 0, MPI_INFO_NULL, &local_comm);
  if (rc != MPI_SUCCESS || local_comm == MPI_COMM_NULL) return 0;

  int local_rank = 0;
  MPI_Comm_rank(local_comm, &local_rank);
  MPI_Comm_free(&local_comm);
  return local_rank;
}

static int get_gid_index_for_dev(const std::string& dev_name) {
  const char* by_host_dev_env = getenv("GID_INDEX_BY_HOST_DEV");
  if (by_host_dev_env && *by_host_dev_env) {
    std::string host = get_short_hostname();
    int mapped = -1;
    if (parse_host_dev_int_map(by_host_dev_env, host, dev_name, &mapped) && mapped >= 0) {
      return mapped;
    }
  }
  const char* by_host_env = getenv("GID_INDEX_BY_HOST");
  if (by_host_env && *by_host_env) {
    std::string host = get_short_hostname();
    int mapped = -1;
    if (parse_host_int_map_for_host(by_host_env, host, &mapped) && mapped >= 0) {
      return mapped;
    }
  }
  const char* env = getenv("GID_INDEX");
  if (!env || !*env) return 3;
  return atoi(env);
}

static union ibv_gid query_gid_or_die(ibv_context* ctx, int port, int gid_index) {
  union ibv_gid gid;
  int rc = ibv_query_gid(ctx, port, gid_index, &gid);
  if (rc != 0) {
    fprintf(stderr, "ibv_query_gid(port=%d, gid_index=%d) failed rc=%d\n",
            port, gid_index, rc);
    exit(1);
  }
  return gid;
}

// Get IPv4 address for a device (from GID table, RoCE v2)
static uint32_t get_device_ipv4(const std::string& dev_name) {
  int num_devs = 0;
  ibv_device** dev_list = ibv_get_device_list(&num_devs);
  CHECK(dev_list && num_devs > 0);

  ibv_device* dev = nullptr;
  for (int i = 0; i < num_devs; i++) {
    if (dev_name == ibv_get_device_name(dev_list[i])) {
      dev = dev_list[i];
      break;
    }
  }
  CHECK(dev);

  ibv_context* ctx = ibv_open_device(dev);
  CHECK(ctx);

  // Find RoCE v2 IPv4-mapped GID (typically index 3)
  union ibv_gid gid;
  for (int idx = 3; idx < 256; idx++) {
    int rc = ibv_query_gid(ctx, 1, idx, &gid);
    if (rc != 0) continue;
    // Check for IPv4-mapped: ::ffff:a.b.c.d
    bool is_ipv4 = true;
    for (int i = 0; i < 10; i++) if (gid.raw[i] != 0) is_ipv4 = false;
    if (gid.raw[10] != 0xff || gid.raw[11] != 0xff) is_ipv4 = false;
    if (is_ipv4) {
      uint32_t ip;
      memcpy(&ip, &gid.raw[12], 4);
      ibv_close_device(ctx);
      ibv_free_device_list(dev_list);
      return ip;  // network byte order
    }
  }

  // Fallback: try lower indices
  for (int idx = 0; idx < 3; idx++) {
    int rc = ibv_query_gid(ctx, 1, idx, &gid);
    if (rc != 0) continue;
    bool is_ipv4 = true;
    for (int i = 0; i < 10; i++) if (gid.raw[i] != 0) is_ipv4 = false;
    if (gid.raw[10] != 0xff || gid.raw[11] != 0xff) is_ipv4 = false;
    if (is_ipv4) {
      uint32_t ip;
      memcpy(&ip, &gid.raw[12], 4);
      ibv_close_device(ctx);
      ibv_free_device_list(dev_list);
      return ip;
    }
  }

  ibv_close_device(ctx);
  ibv_free_device_list(dev_list);
  fprintf(stderr, "No IPv4 GID found for %s\n", dev_name.c_str());
  exit(1);
}

static void create_qp_verbs(verbs_ctx_t* v, ibv_qp** out_qp) {
  ibv_qp_init_attr qp_attr;
  memset(&qp_attr, 0, sizeof(qp_attr));
  qp_attr.send_cq = v->cq;
  qp_attr.recv_cq = v->cq;
  qp_attr.qp_type = IBV_QPT_RC;
  qp_attr.cap.max_send_wr = 256;
  qp_attr.cap.max_recv_wr = 256;
  qp_attr.cap.max_send_sge = 1;
  qp_attr.cap.max_recv_sge = 1;

  ibv_qp* qp = ibv_create_qp(v->pd, &qp_attr);
  CHECK(qp);
  *out_qp = qp;
}

static void create_qp(verbs_ctx_t* v, rdma_cm_id* id) {
  ibv_qp_init_attr qp_attr;
  memset(&qp_attr, 0, sizeof(qp_attr));
  qp_attr.send_cq = v->cq;
  qp_attr.recv_cq = v->cq;
  qp_attr.qp_type = IBV_QPT_RC;
  qp_attr.cap.max_send_wr = 256;
  qp_attr.cap.max_recv_wr = 256;
  qp_attr.cap.max_send_sge = 1;
  qp_attr.cap.max_recv_sge = 1;

  int rc = rdma_create_qp(id, v->pd, &qp_attr);
  if (rc) die("rdma_create_qp", rc);
}

/* -------------------------- rdma_cm connection -------------------------- */

static void setup_listen(verbs_ctx_t* v) {
  v->ec = rdma_create_event_channel();
  CHECK(v->ec);

  int rc = rdma_create_id(v->ec, &v->listen_id, nullptr, RDMA_PS_TCP);
  if (rc) die("rdma_create_id (listen)", rc);

  // Bind to local IP
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = v->local_ip;
  addr.sin_port = htons(RDMA_BASE_PORT + v->rank);

  rc = rdma_bind_addr(v->listen_id, (struct sockaddr*)&addr);
  if (rc) die("rdma_bind_addr", rc);

  // Now we have the device context
  v->pd = ibv_alloc_pd(v->listen_id->verbs);
  CHECK(v->pd);

  v->cq = ibv_create_cq(v->listen_id->verbs, CQE, nullptr, nullptr, 0);
  CHECK(v->cq);

  rc = rdma_listen(v->listen_id, v->size);
  if (rc) die("rdma_listen", rc);
}

static rdma_cm_id* wait_for_connect_request(verbs_ctx_t* v, int* out_peer_rank) {
  struct rdma_cm_event* event = nullptr;
  int rc = rdma_get_cm_event(v->ec, &event);
  if (rc) die("rdma_get_cm_event", rc);

  CHECK(event->event == RDMA_CM_EVENT_CONNECT_REQUEST);

  rdma_cm_id* id = event->id;

  // Extract peer rank from private data
  int peer_rank = -1;
  if (event->param.conn.private_data_len >= sizeof(int)) {
    memcpy(&peer_rank, event->param.conn.private_data, sizeof(int));
  }
  *out_peer_rank = peer_rank;

  rdma_ack_cm_event(event);
  return id;
}

static void accept_connection(verbs_ctx_t* v, rdma_cm_id* id) {
  create_qp(v, id);

  struct rdma_conn_param param;
  memset(&param, 0, sizeof(param));
  param.private_data = &v->rank;
  param.private_data_len = sizeof(v->rank);
  param.responder_resources = 0;
  param.initiator_depth = 0;
  param.rnr_retry_count = 7;

  int rc = rdma_accept(id, &param);
  if (rc) die("rdma_accept", rc);

  // Wait for established
  struct rdma_cm_event* event = nullptr;
  rc = rdma_get_cm_event(v->ec, &event);
  if (rc) die("rdma_get_cm_event (established)", rc);
  CHECK(event->event == RDMA_CM_EVENT_ESTABLISHED);
  rdma_ack_cm_event(event);
}

static rdma_cm_id* connect_to_peer(verbs_ctx_t* v, int peer) {
  rdma_cm_id* id = nullptr;
  int rc = rdma_create_id(v->ec, &id, nullptr, RDMA_PS_TCP);
  if (rc) die("rdma_create_id (connect)", rc);

  // Bind to local IP first
  struct sockaddr_in local_addr;
  memset(&local_addr, 0, sizeof(local_addr));
  local_addr.sin_family = AF_INET;
  local_addr.sin_addr.s_addr = v->local_ip;
  local_addr.sin_port = 0;  // any port

  rc = rdma_bind_addr(id, (struct sockaddr*)&local_addr);
  if (rc) die("rdma_bind_addr (connect)", rc);

  // Now resolve peer address
  struct sockaddr_in peer_addr;
  memset(&peer_addr, 0, sizeof(peer_addr));
  peer_addr.sin_family = AF_INET;
  peer_addr.sin_addr.s_addr = v->all_ips[peer];
  peer_addr.sin_port = htons(RDMA_BASE_PORT + peer);

  char peer_ip_str[INET_ADDRSTRLEN];
  inet_ntop(AF_INET, &peer_addr.sin_addr, peer_ip_str, sizeof(peer_ip_str));
  fprintf(stderr, "rank %d: resolving addr to peer %d (%s:%d)\n",
          v->rank, peer, peer_ip_str, ntohs(peer_addr.sin_port));
  fflush(stderr);

  rc = rdma_resolve_addr(id, nullptr, (struct sockaddr*)&peer_addr, 10000);
  if (rc) die("rdma_resolve_addr", rc);

  // Wait for addr resolved
  struct rdma_cm_event* event = nullptr;
  rc = rdma_get_cm_event(v->ec, &event);
  if (rc) die("rdma_get_cm_event (addr)", rc);
  if (event->event != RDMA_CM_EVENT_ADDR_RESOLVED) {
    fprintf(stderr, "rank %d: expected ADDR_RESOLVED, got event %d (status=%d)\n",
            v->rank, event->event, event->status);
    exit(1);
  }
  rdma_ack_cm_event(event);

  // Resolve route
  rc = rdma_resolve_route(id, 5000);
  if (rc) die("rdma_resolve_route", rc);

  rc = rdma_get_cm_event(v->ec, &event);
  if (rc) die("rdma_get_cm_event (route)", rc);
  CHECK(event->event == RDMA_CM_EVENT_ROUTE_RESOLVED);
  rdma_ack_cm_event(event);

  // Create QP
  create_qp(v, id);

  // Connect
  struct rdma_conn_param param;
  memset(&param, 0, sizeof(param));
  param.private_data = &v->rank;
  param.private_data_len = sizeof(v->rank);
  param.responder_resources = 0;
  param.initiator_depth = 0;
  param.retry_count = 7;
  param.rnr_retry_count = 7;

  rc = rdma_connect(id, &param);
  if (rc) die("rdma_connect", rc);

  // Wait for established
  rc = rdma_get_cm_event(v->ec, &event);
  if (rc) die("rdma_get_cm_event (connect)", rc);
  CHECK(event->event == RDMA_CM_EVENT_ESTABLISHED);
  rdma_ack_cm_event(event);

  return id;
}

/* -------------------------- post/poll -------------------------- */

static void post_recv(ibv_qp* qp, void* buf, size_t len, ibv_mr* mr, uint64_t wr_id) {
  ibv_sge sge;
  memset(&sge, 0, sizeof(sge));
  sge.addr = (uintptr_t)buf;
  sge.length = (uint32_t)len;
  sge.lkey = mr->lkey;

  ibv_recv_wr wr;
  memset(&wr, 0, sizeof(wr));
  wr.wr_id = wr_id;
  wr.sg_list = &sge;
  wr.num_sge = 1;

  ibv_recv_wr* bad = nullptr;
  int rc = ibv_post_recv(qp, &wr, &bad);
  if (rc) die("ibv_post_recv", rc);
}

static void post_send(ibv_qp* qp, void* buf, size_t len, ibv_mr* mr, uint64_t wr_id, bool signaled = true) {
  ibv_sge sge;
  memset(&sge, 0, sizeof(sge));
  sge.addr = (uintptr_t)buf;
  sge.length = (uint32_t)len;
  sge.lkey = mr->lkey;

  ibv_send_wr wr;
  memset(&wr, 0, sizeof(wr));
  wr.wr_id = wr_id;
  wr.sg_list = &sge;
  wr.num_sge = 1;
  wr.opcode = IBV_WR_SEND;
  wr.send_flags = signaled ? IBV_SEND_SIGNALED : 0;

  ibv_send_wr* bad = nullptr;
  int rc = ibv_post_send(qp, &wr, &bad);
  if (rc) die("ibv_post_send", rc);
}

static void poll_n(ibv_cq* cq, int want_send, int want_recv, int rank_dbg) {
  int need_send = want_send;
  int need_recv = want_recv;
  int idle = 0;

  while (need_send > 0 || need_recv > 0) {
    ibv_wc wc[32];
    int n = ibv_poll_cq(cq, 32, wc);
    if (n < 0) die("ibv_poll_cq", n);

    if (n == 0) {
      if (++idle > 20000) { usleep(1); idle = 0; }
      continue;
    }

    idle = 0;
    for (int i = 0; i < n; i++) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "rank %d: WC error status=%d wr_id=0x%llx vendor_err=%u\n",
                rank_dbg, wc[i].status,
                (unsigned long long)wc[i].wr_id,
                wc[i].vendor_err);
        exit(1);
      }
      uint64_t id = wc[i].wr_id;
      if ((id & WRID_MASK) == WRID_SEND) need_send--;
      else if ((id & WRID_MASK) == WRID_RECV) need_recv--;
    }
  }
}

static void poll_n_with_timestamps(ibv_cq* cq,
                                   int want_send, int want_recv, int rank_dbg,
                                   double* send_done_sec,
                                   double* recv_done_sec) {
  int need_send = want_send;
  int need_recv = want_recv;
  int idle = 0;
  *send_done_sec = 0.0;
  *recv_done_sec = 0.0;

  while (need_send > 0 || need_recv > 0) {
    ibv_wc wc[32];
    int n = ibv_poll_cq(cq, 32, wc);
    if (n < 0) die("ibv_poll_cq", n);

    if (n == 0) {
      if (++idle > 20000) { usleep(1); idle = 0; }
      continue;
    }

    idle = 0;
    for (int i = 0; i < n; i++) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "rank %d: WC error status=%d wr_id=0x%llx vendor_err=%u\n",
                rank_dbg, wc[i].status,
                (unsigned long long)wc[i].wr_id,
                wc[i].vendor_err);
        exit(1);
      }
      uint64_t id = wc[i].wr_id;
      if ((id & WRID_MASK) == WRID_SEND) {
        need_send--;
        if (*send_done_sec == 0.0) *send_done_sec = now_sec();
      } else if ((id & WRID_MASK) == WRID_RECV) {
        need_recv--;
        if (*recv_done_sec == 0.0) *recv_done_sec = now_sec();
      }
    }
  }
}

static void poll_stream_iter_with_timestamps(ibv_cq* cq,
                                             int rank_dbg,
                                             int send_peer_expected,
                                             int recv_peer_expected,
                                             int tag_expected,
                                             double* send_done_sec,
                                             double* recv_done_sec) {
  int need_send = 1;
  int need_recv = 1;
  int idle = 0;
  int unexpected = 0;
  *send_done_sec = 0.0;
  *recv_done_sec = 0.0;

  while (need_send > 0 || need_recv > 0) {
    ibv_wc wc[32];
    int n = ibv_poll_cq(cq, 32, wc);
    if (n < 0) die("ibv_poll_cq", n);

    if (n == 0) {
      if (++idle > 20000) { usleep(1); idle = 0; }
      continue;
    }

    idle = 0;
    for (int i = 0; i < n; i++) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "rank %d: WC error status=%d wr_id=0x%llx vendor_err=%u\n",
                rank_dbg, wc[i].status,
                (unsigned long long)wc[i].wr_id,
                wc[i].vendor_err);
        exit(1);
      }
      uint64_t id = wc[i].wr_id;
      const uint64_t kind = id & WRID_MASK;
      const int peer = wr_id_peer(id);
      const int tag = wr_id_chunk(id);

      if (kind == WRID_SEND && peer == send_peer_expected && tag == tag_expected) {
        if (need_send > 0) need_send--;
        if (*send_done_sec == 0.0) *send_done_sec = now_sec();
      } else if (kind == WRID_RECV && peer == recv_peer_expected && tag == tag_expected) {
        if (need_recv > 0) need_recv--;
        if (*recv_done_sec == 0.0) *recv_done_sec = now_sec();
      } else {
        unexpected++;
      }
    }
  }

  if (unexpected > 0 && getenv("IB_STREAM_DEBUG") != nullptr) {
    fprintf(stderr, "rank %d: stream iter consumed unexpected CQEs=%d (send_peer=%d recv_peer=%d tag=%d)\n",
            rank_dbg, unexpected, send_peer_expected, recv_peer_expected, tag_expected);
  }
}

static void poll_progress(ibv_cq* cq, int* need_send, int* need_recv,
                          std::vector<int>* peer_acked, int rank_dbg) {
  int idle = 0;
  while (true) {
    ibv_wc wc[32];
    int n = ibv_poll_cq(cq, 32, wc);
    if (n < 0) die("ibv_poll_cq", n);
    if (n == 0) {
      if (++idle > 20000) { usleep(1); idle = 0; }
      continue;
    }
    for (int i = 0; i < n; i++) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "rank %d: WC error status=%d wr_id=0x%llx vendor_err=%u\n",
                rank_dbg, wc[i].status,
                (unsigned long long)wc[i].wr_id,
                wc[i].vendor_err);
        exit(1);
      }
      uint64_t id = wc[i].wr_id;
      if ((id & WRID_MASK) == WRID_SEND) {
        if (need_send && *need_send > 0) (*need_send)--;
        if (peer_acked) {
          int peer = wr_id_peer(id);
          int chunk = wr_id_chunk(id);
          if (peer >= 0 && peer < (int)peer_acked->size()) {
            int acked = chunk + 1;
            if ((*peer_acked)[peer] < acked) (*peer_acked)[peer] = acked;
          }
        }
      } else if ((id & WRID_MASK) == WRID_RECV) {
        if (need_recv && *need_recv > 0) (*need_recv)--;
      }
    }
    return;
  }
}

/* -------------------------- setup/teardown -------------------------- */

static void setup_verbs(verbs_ctx_t* v, size_t msg_size) {
  MPI_Comm_rank(MPI_COMM_WORLD, &v->world_rank);
  MPI_Comm_size(MPI_COMM_WORLD, &v->world_size);
  v->rank = v->world_rank;
  v->size = v->world_size;

  v->msg_size = msg_size;
  v->local_rank = get_host_local_rank();
  v->dev_name = pick_devname_for_local_rank(v->local_rank);
  v->gid_index = get_gid_index_for_dev(v->dev_name);
  v->local_ip = get_device_ipv4(v->dev_name);

  char ip_str[INET_ADDRSTRLEN];
  inet_ntop(AF_INET, &v->local_ip, ip_str, sizeof(ip_str));
  fprintf(stdout, "rank=%d dev=%s ip=%s gid_index=%d\n",
          v->rank, v->dev_name.c_str(), ip_str, v->gid_index);
  fflush(stdout);

  // Gather all IPs
  v->all_ips.resize(v->size);
  MPI_Allgather(&v->local_ip, sizeof(uint32_t), MPI_BYTE,
                v->all_ips.data(), sizeof(uint32_t), MPI_BYTE,
                MPI_COMM_WORLD);

  // Initialize connection structures
  v->cm_ids.assign(v->size, nullptr);
  v->qps.assign(v->size, nullptr);

  // Setup listening
  setup_listen(v);

  // Allocate buffers
  CHECK(v->group_size > 0);
  v->buf_size = (size_t)v->group_size * v->msg_size;
  void* p1 = nullptr;
  void* p2 = nullptr;
  CHECK(posix_memalign(&p1, 4096, v->buf_size) == 0);
  CHECK(posix_memalign(&p2, 4096, v->buf_size) == 0);
  v->send_buf = (uint8_t*)p1;
  v->recv_buf = (uint8_t*)p2;
  memset(v->send_buf, 0, v->buf_size);
  memset(v->recv_buf, 0, v->buf_size);

  v->mr_send = ibv_reg_mr(v->pd, v->send_buf, v->buf_size, IBV_ACCESS_LOCAL_WRITE);
  v->mr_recv = ibv_reg_mr(v->pd, v->recv_buf, v->buf_size, IBV_ACCESS_LOCAL_WRITE);
  CHECK(v->mr_send && v->mr_recv);

  MPI_Barrier(MPI_COMM_WORLD);
}

struct qp_info_t {
  uint32_t qpn;
  uint32_t psn;
  uint8_t gid[16];
};

static uint32_t rand_psn() {
  return (uint32_t)(lrand48() & 0xffffff);
}

static void modify_qp_to_init(ibv_qp* qp) {
  ibv_qp_attr attr;
  memset(&attr, 0, sizeof(attr));
  attr.qp_state = IBV_QPS_INIT;
  attr.pkey_index = 0;
  attr.port_num = 1;
  attr.qp_access_flags = 0;

  int rc = ibv_modify_qp(qp, &attr,
                         IBV_QP_STATE | IBV_QP_PKEY_INDEX |
                         IBV_QP_PORT | IBV_QP_ACCESS_FLAGS);
  if (rc) die("ibv_modify_qp INIT", rc);
}

static void modify_qp_to_rtr(ibv_qp* qp, const qp_info_t& remote,
                             int gid_index, int my_rank, int peer_rank) {
  ibv_qp_attr attr;
  memset(&attr, 0, sizeof(attr));
  attr.qp_state = IBV_QPS_RTR;
  attr.path_mtu = IBV_MTU_1024;
  attr.dest_qp_num = remote.qpn;
  attr.rq_psn = remote.psn;
  attr.max_dest_rd_atomic = 0;
  attr.min_rnr_timer = 12;

  attr.ah_attr.is_global = 1;
  attr.ah_attr.grh.dgid = *(const union ibv_gid*)remote.gid;
  attr.ah_attr.grh.sgid_index = gid_index;
  attr.ah_attr.grh.hop_limit = 64;
  attr.ah_attr.grh.traffic_class = 0;
  attr.ah_attr.grh.flow_label = 0;
  attr.ah_attr.dlid = 0;
  attr.ah_attr.sl = 0;
  attr.ah_attr.src_path_bits = 0;
  attr.ah_attr.port_num = 1;

  // Extract target IP from GID for debugging
  char ip_str[INET_ADDRSTRLEN];
  inet_ntop(AF_INET, &remote.gid[12], ip_str, sizeof(ip_str));
  fprintf(stderr, "rank %d: modify_qp_to_rtr for peer %d (target IP %s)\n",
          my_rank, peer_rank, ip_str);
  fflush(stderr);

  int rc = ibv_modify_qp(qp, &attr,
                         IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU |
                         IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
                         IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER);
  if (rc) {
    fprintf(stderr, "rank %d: ibv_modify_qp RTR for peer %d FAILED rc=%d errno=%d\n",
            my_rank, peer_rank, rc, errno);
    die("ibv_modify_qp RTR", rc);
  }
}

static void modify_qp_to_rts(ibv_qp* qp, uint32_t local_psn) {
  ibv_qp_attr attr;
  memset(&attr, 0, sizeof(attr));
  attr.qp_state = IBV_QPS_RTS;
  attr.timeout = 14;
  attr.retry_cnt = 7;
  attr.rnr_retry = 7;
  attr.sq_psn = local_psn;
  attr.max_rd_atomic = 0;

  int rc = ibv_modify_qp(qp, &attr,
                         IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT |
                         IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN |
                         IBV_QP_MAX_QP_RD_ATOMIC);
  if (rc) die("ibv_modify_qp RTS", rc);
}

static void setup_verbs_direct(verbs_ctx_t* v, size_t msg_size) {
  MPI_Comm_rank(MPI_COMM_WORLD, &v->world_rank);
  MPI_Comm_size(MPI_COMM_WORLD, &v->world_size);
  v->rank = v->world_rank;
  v->size = v->world_size;

  v->msg_size = msg_size;
  v->local_rank = get_host_local_rank();
  v->dev_name = pick_devname_for_local_rank(v->local_rank);
  v->gid_index = get_gid_index_for_dev(v->dev_name);

  int num_devs = 0;
  ibv_device** dev_list = ibv_get_device_list(&num_devs);
  CHECK(dev_list && num_devs > 0);

  ibv_device* dev = nullptr;
  for (int i = 0; i < num_devs; i++) {
    if (v->dev_name == ibv_get_device_name(dev_list[i])) {
      dev = dev_list[i];
      break;
    }
  }
  CHECK(dev);

  v->ibv_ctx = ibv_open_device(dev);
  CHECK(v->ibv_ctx);
  v->gid = query_gid_or_die(v->ibv_ctx, 1, v->gid_index);
  ibv_free_device_list(dev_list);

  memcpy(&v->local_ip, &v->gid.raw[12], 4);
  char ip_str[INET_ADDRSTRLEN];
  inet_ntop(AF_INET, &v->local_ip, ip_str, sizeof(ip_str));
  fprintf(stdout, "rank=%d dev=%s ip=%s gid_index=%d (direct)\n",
          v->rank, v->dev_name.c_str(), ip_str, v->gid_index);
  fflush(stdout);

  v->pd = ibv_alloc_pd(v->ibv_ctx);
  CHECK(v->pd);

  v->cq = ibv_create_cq(v->ibv_ctx, CQE, nullptr, nullptr, 0);
  CHECK(v->cq);

  CHECK(v->group_size > 0);
  v->buf_size = (size_t)v->group_size * v->msg_size;
  void* p1 = nullptr;
  void* p2 = nullptr;
  CHECK(posix_memalign(&p1, 4096, v->buf_size) == 0);
  CHECK(posix_memalign(&p2, 4096, v->buf_size) == 0);
  v->send_buf = (uint8_t*)p1;
  v->recv_buf = (uint8_t*)p2;
  memset(v->send_buf, 0, v->buf_size);
  memset(v->recv_buf, 0, v->buf_size);

  v->mr_send = ibv_reg_mr(v->pd, v->send_buf, v->buf_size, IBV_ACCESS_LOCAL_WRITE);
  v->mr_recv = ibv_reg_mr(v->pd, v->recv_buf, v->buf_size, IBV_ACCESS_LOCAL_WRITE);
  CHECK(v->mr_send && v->mr_recv);

  v->cm_ids.assign(v->size, nullptr);
  v->qps.assign(v->size, nullptr);

  MPI_Barrier(MPI_COMM_WORLD);
}

static void establish_connections(verbs_ctx_t* v) {
  // Connection strategy: process by source rank
  // In each round, one rank connects to all higher ranks
  // Higher ranks accept one connection each

  for (int src = 0; src < v->size; src++) {
    if (v->rank == src) {
      // This rank connects to all higher ranks
      for (int dst = src + 1; dst < v->size; dst++) {
        if (!peer_in_group(v, dst)) continue;
        rdma_cm_id* id = connect_to_peer(v, dst);
        v->cm_ids[dst] = id;
        v->qps[dst] = id->qp;
      }
    } else if (v->rank > src && peer_in_group(v, src)) {
      // Accept one connection from src
      int peer_rank = -1;
      rdma_cm_id* id = wait_for_connect_request(v, &peer_rank);
      CHECK(peer_rank == src);
      accept_connection(v, id);
      v->cm_ids[peer_rank] = id;
      v->qps[peer_rank] = id->qp;
    }
    // Ranks < src do nothing this round

    MPI_Barrier(MPI_COMM_WORLD);
  }

  if (v->group_rank == 0) {
    printf("All connections established.\n");
  }
}

static void establish_connections_direct(verbs_ctx_t* v) {
  srand48((long)time(nullptr) + v->rank * 1000);

  uint32_t local_psn = rand_psn();

  for (int peer = 0; peer < v->size; peer++) {
    if (peer == v->rank) continue;
    if (!peer_in_group(v, peer)) continue;
    create_qp_verbs(v, &v->qps[peer]);
    modify_qp_to_init(v->qps[peer]);
  }

  // Build local info array: one entry per peer QP
  std::vector<qp_info_t> local(v->size);
  for (int peer = 0; peer < v->size; peer++) {
    if (peer == v->rank) {
      memset(&local[peer], 0, sizeof(local[peer]));
      continue;
    }
    if (!peer_in_group(v, peer)) {
      memset(&local[peer], 0, sizeof(local[peer]));
      continue;
    }
    local[peer].qpn = v->qps[peer]->qp_num;
    local[peer].psn = local_psn;
    memcpy(local[peer].gid, v->gid.raw, 16);
  }

  // Gather all peers' arrays: all_info[rank][peer]
  std::vector<qp_info_t> all_info(v->size * v->size);
  MPI_Allgather(local.data(), sizeof(qp_info_t) * v->size, MPI_BYTE,
                all_info.data(), sizeof(qp_info_t) * v->size, MPI_BYTE,
                MPI_COMM_WORLD);

  for (int peer = 0; peer < v->size; peer++) {
    if (peer == v->rank) continue;
    if (!peer_in_group(v, peer)) continue;
    const qp_info_t& remote = all_info[peer * v->size + v->rank];
    modify_qp_to_rtr(v->qps[peer], remote, v->gid_index, v->rank, peer);
    modify_qp_to_rts(v->qps[peer], local_psn);
  }

  if (v->group_rank == 0) {
    printf("All connections established (verbs direct).\n");
  }
}

static void cleanup(verbs_ctx_t* v) {
  for (int i = 0; i < v->size; i++) {
    if (v->cm_ids[i]) {
      rdma_disconnect(v->cm_ids[i]);
      rdma_destroy_qp(v->cm_ids[i]);
      rdma_destroy_id(v->cm_ids[i]);
    }
  }
  if (v->mr_send) ibv_dereg_mr(v->mr_send);
  if (v->mr_recv) ibv_dereg_mr(v->mr_recv);
  if (v->send_buf) free(v->send_buf);
  if (v->recv_buf) free(v->recv_buf);
  if (v->cq) ibv_destroy_cq(v->cq);
  if (v->pd) ibv_dealloc_pd(v->pd);
  if (v->listen_id) {
    rdma_destroy_id(v->listen_id);
  }
  if (v->ec) rdma_destroy_event_channel(v->ec);
  if (v->ibv_ctx) ibv_close_device(v->ibv_ctx);
}

/* -------------------------- ringallreduce -------------------------- */

static void exchange_left_right(verbs_ctx_t* v,
                                int left_peer, int right_peer,
                                const uint8_t* send_ptr, size_t send_len,
                                uint8_t* recv_ptr, size_t recv_len,
                                iter_phase_t* phase) {
  size_t max_len = std::max(send_len, recv_len);
  if (max_len == 0) return;
  size_t chunk_size = g_chunk_bytes;
  if (chunk_size == 0) chunk_size = 65536;
  if (max_len < chunk_size) chunk_size = max_len;
  int send_chunks = (int)((send_len + chunk_size - 1) / chunk_size);
  int recv_chunks = (int)((recv_len + chunk_size - 1) / chunk_size);

  double tr0 = now_sec();
  for (int c = 0; c < recv_chunks; c++) {
    size_t off = (size_t)c * chunk_size;
    size_t len = std::min(chunk_size, recv_len - off);
    post_recv(v->qps[left_peer], recv_ptr + off, len, v->mr_recv, make_wr_id(WRID_RECV, left_peer, c));
  }
  double tr1 = now_sec();
  if (phase) phase->post_recv_us += (tr1 - tr0) * 1e6;

  int need_send = 0;
  int need_recv = recv_chunks;
  std::vector<int> peer_acked(v->size, 0);
  int posted = 0;
  double ts_acc = 0.0;
  double tp_acc = 0.0;
  double step_send_start = now_sec();
  while (posted < send_chunks || peer_acked[right_peer] < send_chunks || need_recv > 0 || need_send > 0) {
    while (posted < send_chunks) {
      int in_flight = posted - peer_acked[right_peer];
      if (in_flight >= g_inflight_per_peer) break;
      int c = posted;
      size_t off = (size_t)c * chunk_size;
      size_t len = std::min(chunk_size, send_len - off);
      bool signaled = (((c + 1) % g_signal_interval) == 0) ||
                      ((c + 1) == send_chunks) ||
                      ((in_flight + 1) >= g_inflight_per_peer);
      double ts0 = now_sec();
      post_send(v->qps[right_peer], (void*)(send_ptr + off), len, v->mr_send,
                make_wr_id(WRID_SEND, right_peer, c), signaled);
      double ts1 = now_sec();
      ts_acc += (ts1 - ts0) * 1e6;
      posted++;
      if (signaled) need_send++;
    }
    int in_flight = posted - peer_acked[right_peer];
    bool recv_backlog = (need_recv > 0) &&
                        ((posted >= send_chunks) || (in_flight >= g_inflight_per_peer));
    if (need_send > 0 || recv_backlog || (posted >= send_chunks && need_recv > 0)) {
      double tp0 = now_sec();
      poll_progress(v->cq, &need_send, &need_recv, &peer_acked, v->rank);
      double tp1 = now_sec();
      tp_acc += (tp1 - tp0) * 1e6;
    }
  }
  if (phase) {
    phase->post_send_us += ts_acc;
    phase->poll_cq_us += tp_acc;
    int gi = right_peer - v->group_id * v->group_size;
    if (gi >= 0 && gi < (int)phase->peer_send_us.size()) {
      phase->peer_send_us[gi] += (now_sec() - step_send_start) * 1e6;
    }
  }
}

static void exchange_with_peer_single(verbs_ctx_t* v,
                                      int peer,
                                      const uint8_t* send_ptr, size_t send_len,
                                      uint8_t* recv_ptr, size_t recv_len,
                                      iter_phase_t* phase) {
  int need_send = (send_len > 0) ? 1 : 0;
  int need_recv = (recv_len > 0) ? 1 : 0;

  double tr0 = now_sec();
  if (need_recv) {
    post_recv(v->qps[peer], recv_ptr, recv_len, v->mr_recv, make_wr_id(WRID_RECV, peer, 0));
  }
  double tr1 = now_sec();
  if (phase) phase->post_recv_us += (tr1 - tr0) * 1e6;

  if (g_jct_sync_recvs) {
    double tb0 = now_sec();
    MPI_Barrier(v->group_comm);
    double tb1 = now_sec();
    if (phase) phase->barrier_us += (tb1 - tb0) * 1e6;
  }

  double ts0 = now_sec();
  if (need_send) {
    post_send(v->qps[peer], (void*)send_ptr, send_len, v->mr_send, make_wr_id(WRID_SEND, peer, 0), true);
  }
  double ts1 = now_sec();
  if (phase) phase->post_send_us += (ts1 - ts0) * 1e6;

  double tp0 = now_sec();
  poll_n(v->cq, need_send, need_recv, v->rank);
  double tp1 = now_sec();
  if (phase) {
    phase->poll_cq_us += (tp1 - tp0) * 1e6;
    if (need_send) {
      phase->msg_send_us.push_back((tp1 - ts0) * 1e6);
      phase->msg_dst_world.push_back(peer);
    }
    int gi = peer - v->group_id * v->group_size;
    if (need_send && gi >= 0 && gi < (int)phase->peer_send_us.size()) {
      phase->peer_send_us[gi] += (tp1 - ts0) * 1e6;
    }
  }
}

static void verbs_alltoall(verbs_ctx_t* v, iter_phase_t* phase = nullptr) {
  const int n = v->group_size;
  if (phase) {
    phase->post_recv_us = 0.0;
    phase->barrier_us = 0.0;
    phase->post_send_us = 0.0;
    phase->poll_cq_us = 0.0;
    phase->peer_send_us.assign(v->group_size, 0.0);
    phase->msg_send_us.clear();
    phase->msg_dst_world.clear();
  }
  if (n <= 1 || v->msg_size == 0) return;

  const int base = v->group_id * v->group_size;
  const int left_world = base + ((v->group_rank - 1 + n) % n);
  const int right_world = base + ((v->group_rank + 1) % n);

  int total_count = (int)(v->msg_size / sizeof(double));
  std::vector<int> counts;
  std::vector<int> displs;
  build_counts_displs(total_count, n, counts, displs);

  double* buf = reinterpret_cast<double*>(v->send_buf);
  double* tmp = reinterpret_cast<double*>(v->recv_buf);

  if (g_jct_sync_recvs && n != 2) {
    double tb0 = now_sec();
    MPI_Barrier(v->group_comm);
    double tb1 = now_sec();
    if (phase) phase->barrier_us += (tb1 - tb0) * 1e6;
  }

  if (n == 2) {
    int peer_world = base + ((v->group_rank + 1) % 2);
    // Keep true ring semantics for np=2:
    // 1) reduce-scatter one step, 2) allgather one step.
    int rs_send_idx = v->group_rank;
    int rs_recv_idx = (v->group_rank - 1 + 2) % 2;
    size_t rs_send_bytes = (size_t)counts[rs_send_idx] * sizeof(double);
    size_t rs_recv_bytes = (size_t)counts[rs_recv_idx] * sizeof(double);
    const uint8_t* rs_send_ptr = reinterpret_cast<const uint8_t*>(buf + displs[rs_send_idx]);
    uint8_t* rs_recv_tmp = reinterpret_cast<uint8_t*>(tmp);
    exchange_with_peer_single(v, peer_world, rs_send_ptr, rs_send_bytes, rs_recv_tmp, rs_recv_bytes, phase);
    double* rs_recv_vals = reinterpret_cast<double*>(rs_recv_tmp);
    double* rs_dst = buf + displs[rs_recv_idx];
    for (int i = 0; i < counts[rs_recv_idx]; i++) {
      rs_dst[i] += rs_recv_vals[i];
    }

    int ag_send_idx = (v->group_rank + 1) % 2;
    int ag_recv_idx = v->group_rank;
    size_t ag_send_bytes = (size_t)counts[ag_send_idx] * sizeof(double);
    size_t ag_recv_bytes = (size_t)counts[ag_recv_idx] * sizeof(double);
    const uint8_t* ag_send_ptr = reinterpret_cast<const uint8_t*>(buf + displs[ag_send_idx]);
    uint8_t* ag_recv_tmp = reinterpret_cast<uint8_t*>(tmp);
    exchange_with_peer_single(v, peer_world, ag_send_ptr, ag_send_bytes, ag_recv_tmp, ag_recv_bytes, phase);
    memcpy(buf + displs[ag_recv_idx], ag_recv_tmp, ag_recv_bytes);
    return;
  }

  // Reduce-scatter
  for (int step = 0; step < n - 1; step++) {
    int send_idx = (v->group_rank - step + n) % n;
    int recv_idx = (v->group_rank - step - 1 + n) % n;
    size_t send_bytes = (size_t)counts[send_idx] * sizeof(double);
    size_t recv_bytes = (size_t)counts[recv_idx] * sizeof(double);
    const uint8_t* sptr = reinterpret_cast<const uint8_t*>(buf + displs[send_idx]);
    uint8_t* rtmp = reinterpret_cast<uint8_t*>(tmp);
    exchange_left_right(v, left_world, right_world, sptr, send_bytes, rtmp, recv_bytes, phase);
    double* recv_vals = reinterpret_cast<double*>(rtmp);
    double* dst = buf + displs[recv_idx];
    for (int i = 0; i < counts[recv_idx]; i++) dst[i] += recv_vals[i];
  }

  // Allgather
  for (int step = 0; step < n - 1; step++) {
    int send_idx = (v->group_rank + 1 - step + n) % n;
    int recv_idx = (v->group_rank - step + n) % n;
    size_t send_bytes = (size_t)counts[send_idx] * sizeof(double);
    size_t recv_bytes = (size_t)counts[recv_idx] * sizeof(double);
    const uint8_t* sptr = reinterpret_cast<const uint8_t*>(buf + displs[send_idx]);
    uint8_t* rtmp = reinterpret_cast<uint8_t*>(tmp);
    exchange_left_right(v, left_world, right_world, sptr, send_bytes, rtmp, recv_bytes, phase);
    memcpy(buf + displs[recv_idx], rtmp, recv_bytes);
  }
}

static void stream_exchange_neighbor(verbs_ctx_t* v, int send_peer_world, int recv_peer_world,
                                int iter_tag, double* tx_us, double* rx_us, double* total_us) {
  size_t bytes = v->msg_size;
  if (g_stream_chunked_exchange) {
    if (g_stream_iter_barrier) {
      MPI_Barrier(v->group_comm);
    }
    double t0 = now_sec();
    exchange_left_right(v, recv_peer_world, send_peer_world,
                        reinterpret_cast<const uint8_t*>(v->send_buf), bytes,
                        reinterpret_cast<uint8_t*>(v->recv_buf), bytes, nullptr);
    double done = now_sec();
    double total = (done - t0) * 1e6;
    *tx_us = total;
    *rx_us = total;
    *total_us = total;
    return;
  }

  post_recv(v->qps[recv_peer_world], v->recv_buf, bytes, v->mr_recv,
            make_wr_id(WRID_RECV, recv_peer_world, iter_tag & WRID_CHUNK_MASK));
  if (g_stream_iter_barrier) {
    MPI_Barrier(v->group_comm);
  }
  double t0 = now_sec();
  post_send(v->qps[send_peer_world], v->send_buf, bytes, v->mr_send,
            make_wr_id(WRID_SEND, send_peer_world, iter_tag & WRID_CHUNK_MASK), true);
  double send_done = 0.0;
  double recv_done = 0.0;
  poll_stream_iter_with_timestamps(v->cq, v->rank, send_peer_world, recv_peer_world,
                                   (iter_tag & WRID_CHUNK_MASK), &send_done, &recv_done);
  double done = std::max(send_done, recv_done);
  *tx_us = (send_done - t0) * 1e6;
  *rx_us = (recv_done - t0) * 1e6;
  *total_us = (done - t0) * 1e6;
}

static void stream_exchange_windowed(verbs_ctx_t* v, int send_peer_world, int recv_peer_world,
                                     int start_tag, int count,
                                     std::vector<double>& tx_us,
                                     std::vector<double>& rx_us,
                                     std::vector<double>& total_us) {
  if (count <= 0) return;
  const size_t bytes = v->msg_size;
  const int window = std::max(1, g_stream_window);
  std::vector<double> send_t0((size_t)count, 0.0);
  std::vector<double> recv_t0((size_t)count, 0.0);
  int next_recv_post = 0;
  int next_send_post = 0;
  int done_send = 0;
  int done_recv = 0;

  int prepost = std::min(window, count);
  for (int i = 0; i < prepost; i++) {
    int tag = (start_tag + i) & (int)WRID_CHUNK_MASK;
    recv_t0[(size_t)i] = now_sec();
    post_recv(v->qps[recv_peer_world], v->recv_buf, bytes, v->mr_recv,
              make_wr_id(WRID_RECV, recv_peer_world, tag));
    next_recv_post++;
  }

  if (g_stream_start_barrier) {
    MPI_Barrier(v->group_comm);
  }

  while (done_send < count || done_recv < count) {
    while (next_send_post < count && (next_send_post - done_send) < window) {
      int idx = next_send_post;
      int tag = (start_tag + idx) & (int)WRID_CHUNK_MASK;
      send_t0[(size_t)idx] = now_sec();
      post_send(v->qps[send_peer_world], v->send_buf, bytes, v->mr_send,
                make_wr_id(WRID_SEND, send_peer_world, tag), true);
      next_send_post++;
    }

    ibv_wc wc[32];
    int n = ibv_poll_cq(v->cq, 32, wc);
    if (n < 0) die("ibv_poll_cq", n);
    if (n == 0) {
      usleep(1);
      continue;
    }

    for (int i = 0; i < n; i++) {
      if (wc[i].status != IBV_WC_SUCCESS) {
        fprintf(stderr, "rank %d: WC error status=%d wr_id=0x%llx vendor_err=%u\n",
                v->rank, wc[i].status, (unsigned long long)wc[i].wr_id, wc[i].vendor_err);
        exit(1);
      }
      uint64_t id = wc[i].wr_id;
      const uint64_t kind = id & WRID_MASK;
      const int peer = wr_id_peer(id);
      const int tag = wr_id_chunk(id);
      const int idx = (tag - start_tag) & (int)WRID_CHUNK_MASK;
      if (idx < 0 || idx >= count) continue;

      double now = now_sec();
      if (kind == WRID_SEND && peer == send_peer_world) {
        if (tx_us[(size_t)idx] == 0.0 && send_t0[(size_t)idx] > 0.0) {
          tx_us[(size_t)idx] = (now - send_t0[(size_t)idx]) * 1e6;
          done_send++;
        }
      } else if (kind == WRID_RECV && peer == recv_peer_world) {
        if (rx_us[(size_t)idx] == 0.0 && recv_t0[(size_t)idx] > 0.0) {
          rx_us[(size_t)idx] = (now - recv_t0[(size_t)idx]) * 1e6;
          done_recv++;
          if (next_recv_post < count) {
            int next_idx = next_recv_post;
            int next_tag = (start_tag + next_idx) & (int)WRID_CHUNK_MASK;
            recv_t0[(size_t)next_idx] = now_sec();
            post_recv(v->qps[recv_peer_world], v->recv_buf, bytes, v->mr_recv,
                      make_wr_id(WRID_RECV, recv_peer_world, next_tag));
            next_recv_post++;
          }
        }
      }
    }
  }

  for (int i = 0; i < count; i++) {
    total_us[(size_t)i] = std::max(tx_us[(size_t)i], rx_us[(size_t)i]);
  }
}

static void verify_data(verbs_ctx_t* v) {
  int total_count = (int)(v->msg_size / sizeof(double));
  std::vector<int> counts;
  std::vector<int> displs;
  build_counts_displs(total_count, v->group_size, counts, displs);

  double* buf = reinterpret_cast<double*>(v->send_buf);
  double init_val = (double)(v->group_rank + 1);
  for (int i = 0; i < total_count; i++) buf[i] = init_val;

  verbs_alltoall(v);

  double expected = (double)v->group_size * (double)(v->group_size + 1) / 2.0;
  int errors = 0;
  for (int i = 0; i < total_count; i++) {
    if (fabs(buf[i] - expected) > 1e-9) {
      errors++;
      if (errors < 4) {
        fprintf(stderr, "rank %d: mismatch at %d got=%f expect=%f\n",
                v->rank, i, buf[i], expected);
      }
    }
  }
  int global_errors = 0;
  MPI_Allreduce(&errors, &global_errors, 1, MPI_INT, MPI_SUM, v->group_comm);
  if (v->group_rank == 0) {
    if (global_errors == 0) printf("✓ Data verification PASSED\n");
    else printf("✗ Data verification FAILED (total errors=%d)\n", global_errors);
  }
}

static std::vector<size_t> parse_size_list(const std::string& text) {
  std::vector<size_t> out;
  std::stringstream ss(text);
  std::string tok;
  while (std::getline(ss, tok, ',')) {
    if (tok.empty()) continue;
    size_t x = (size_t)strtoull(tok.c_str(), nullptr, 10);
    if (x > 0) out.push_back(x);
  }
  return out;
}

static double percentile_us(std::vector<double> vals, double p) {
  if (vals.empty()) return 0.0;
  std::sort(vals.begin(), vals.end());
  double pos = (p / 100.0) * (double)(vals.size() - 1);
  size_t lo = (size_t)pos;
  size_t hi = std::min(lo + 1, vals.size() - 1);
  double frac = pos - (double)lo;
  return vals[lo] * (1.0 - frac) + vals[hi] * frac;
}

/* -------------------------- main -------------------------- */

int main(int argc, char** argv) {
  MPI_Init(&argc, &argv);

  size_t total_size = 150 * 1024 * 1024;
  int group_size = 8;
  bool group_size_set = false;
  int iters = 100;
  int warmup = 5;
  bench_mode_t bench_mode = BENCH_BW;
  jct_mode_t jct_mode = JCT_MODE_SAFE;
  bool dump_fct = false;
  std::vector<size_t> size_list;

  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "-size") && i + 1 < argc) {
      total_size = (size_t)atoll(argv[++i]);
    } else if (!strcmp(argv[i], "--sizes") && i + 1 < argc) {
      size_list = parse_size_list(argv[++i]);
    } else if ((!strcmp(argv[i], "-iters") || !strcmp(argv[i], "--iters")) && i + 1 < argc) {
      iters = atoi(argv[++i]);
    } else if ((!strcmp(argv[i], "-warmup") || !strcmp(argv[i], "--warmup")) && i + 1 < argc) {
      warmup = atoi(argv[++i]);
    } else if ((!strcmp(argv[i], "-groupsize") || !strcmp(argv[i], "--groupsize")) && i + 1 < argc) {
      group_size = atoi(argv[++i]);
      group_size_set = true;
    } else if (!strcmp(argv[i], "--bench") && i + 1 < argc) {
      const char* m = argv[++i];
      if (!strcmp(m, "bw")) bench_mode = BENCH_BW;
      else if (!strcmp(m, "jct")) bench_mode = BENCH_JCT;
      else if (!strcmp(m, "stream")) bench_mode = BENCH_STREAM;
      else {
        int r = 0;
        MPI_Comm_rank(MPI_COMM_WORLD, &r);
        if (r == 0) fprintf(stderr, "Error: --bench supports bw|jct|stream\n");
        MPI_Finalize();
        return 1;
      }
    } else if (!strcmp(argv[i], "--jct-mode") && i + 1 < argc) {
      const char* m = argv[++i];
      if (!strcmp(m, "safe")) jct_mode = JCT_MODE_SAFE;
      else if (!strcmp(m, "performance")) jct_mode = JCT_MODE_PERFORMANCE;
      else {
        int r = 0;
        MPI_Comm_rank(MPI_COMM_WORLD, &r);
        if (r == 0) fprintf(stderr, "Error: --jct-mode supports safe|performance\n");
        MPI_Finalize();
        return 1;
      }
    } else if (!strcmp(argv[i], "--peer-batch") && i + 1 < argc) {
      g_peer_batch = atoi(argv[++i]);
    } else if (!strcmp(argv[i], "--inflight-per-peer") && i + 1 < argc) {
      g_inflight_per_peer = atoi(argv[++i]);
    } else if (!strcmp(argv[i], "--signal-interval") && i + 1 < argc) {
      g_signal_interval = atoi(argv[++i]);
    } else if (!strcmp(argv[i], "--chunk-bytes") && i + 1 < argc) {
      g_chunk_bytes = (size_t)strtoull(argv[++i], nullptr, 10);
    } else if (!strcmp(argv[i], "--phase-timing")) {
      g_phase_timing = true;
    } else if (!strcmp(argv[i], "--stream-iter-barrier") && i + 1 < argc) {
      g_stream_iter_barrier = atoi(argv[++i]) != 0;
    } else if (!strcmp(argv[i], "--stream-window") && i + 1 < argc) {
      g_stream_window = atoi(argv[++i]);
    } else if (!strcmp(argv[i], "--stream-start-barrier") && i + 1 < argc) {
      g_stream_start_barrier = atoi(argv[++i]) != 0;
    } else if (!strcmp(argv[i], "--stream-chunked-exchange") && i + 1 < argc) {
      g_stream_chunked_exchange = atoi(argv[++i]) != 0;
    } else if (!strcmp(argv[i], "--auto-port-probe")) {
      g_auto_port_probe = true;
    } else if (!strcmp(argv[i], "--dump-fct")) {
      dump_fct = true;
    } else {
      int r = 0;
      MPI_Comm_rank(MPI_COMM_WORLD, &r);
      if (r == 0) {
        fprintf(stderr, "Unknown arg: %s\n", argv[i]);
        fprintf(stderr, "Usage: %s [-size BYTES] [--sizes a,b,c] [--bench bw|jct|stream] [--jct-mode safe|performance] [--peer-batch N] [--inflight-per-peer N] [--signal-interval N] [--chunk-bytes N] [--phase-timing] [--stream-iter-barrier 0|1] [--stream-window N] [--stream-start-barrier 0|1] [--stream-chunked-exchange 0|1] [--auto-port-probe] [--dump-fct] [-iters N] [-warmup N] [-groupsize N]\n", argv[0]);
        fprintf(stderr, "Env:\n");
        fprintf(stderr, "  IB_DEV_PREFIX=mlx5_   (default mlx5_)\n");
        fprintf(stderr, "  IB_DEV_LIST=mlx5_0,mlx5_1,... (optional whitelist)\n");
        fprintf(stderr, "  IB_DEV_MAP_BY_HOST=dc20:mlx5_0,mlx5_1|dc21:mlx5_2,mlx5_3 (optional per-host list)\n");
        fprintf(stderr, "  USE_RDMA_CM=1|0       (default 1)\n");
        fprintf(stderr, "  GID_INDEX_BY_HOST_DEV=dc20:mlx5_0=3,mlx5_1=4|dc23:mlx5_2=4 (optional per-host per-dev GID index)\n");
        fprintf(stderr, "  GID_INDEX_BY_HOST=dc20:3|dc23:4 (optional per-host GID index)\n");
        fprintf(stderr, "  GID_INDEX=3           (default 3)\n");
        fprintf(stderr, "Notes:\n");
        fprintf(stderr, "  -size is total bytes per rank across the group.\n");
        fprintf(stderr, "  This program assumes 4 ranks per host (rank%%4 maps NIC).\n");
      }
      MPI_Finalize();
      return 1;
    }
  }

  int world_rank = 0;
  int world_size = 0;
  MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);
  MPI_Comm_size(MPI_COMM_WORLD, &world_size);
  if (!group_size_set && group_size > world_size) {
    group_size = world_size;
  }
  if (group_size <= 0 || (world_size % group_size) != 0) {
    if (world_rank == 0) fprintf(stderr, "Error: groupsize must divide world_size\n");
    MPI_Finalize();
    return 1;
  }
  if (size_list.empty()) {
    if (total_size % (size_t)group_size != 0) {
      if (world_rank == 0) fprintf(stderr, "Error: size must be divisible by groupsize\n");
      MPI_Finalize();
      return 1;
    }
    size_list.push_back(total_size / (size_t)group_size);
  }
  size_t max_msg_size = 0;
  for (size_t x : size_list) max_msg_size = std::max(max_msg_size, x);
  if (g_peer_batch < 0) g_peer_batch = 0;
  if (g_inflight_per_peer < 1) g_inflight_per_peer = 1;
  if (g_signal_interval < 1) g_signal_interval = 1;
  if (g_chunk_bytes < 1) g_chunk_bytes = 65536;
  if (g_stream_window < 1) g_stream_window = 1;

  int group_id = world_rank / group_size;
  MPI_Comm group_comm;
  MPI_Comm_split(MPI_COMM_WORLD, group_id, world_rank, &group_comm);
  int group_rank = 0;
  MPI_Comm_rank(group_comm, &group_rank);

  int group_base = group_id * group_size;
  std::vector<int> group_world_ranks;
  group_world_ranks.reserve(group_size);
  for (int i = 0; i < group_size; i++) {
    group_world_ranks.push_back(group_base + i);
  }

  verbs_ctx_t v;
  v.group_size = group_size;
  v.group_id = group_id;
  v.group_rank = group_rank;
  v.group_comm = group_comm;
  v.group_world_ranks = group_world_ranks;
  const char* use_cm_env = getenv("USE_RDMA_CM");
  bool use_cm = true;
  if (use_cm_env && *use_cm_env) {
    use_cm = atoi(use_cm_env) != 0;
  }
  g_jct_sync_recvs = (bench_mode == BENCH_JCT && jct_mode == JCT_MODE_SAFE);
  g_jct_mode = jct_mode;

  if (use_cm) {
    setup_verbs(&v, max_msg_size);
    establish_connections(&v);
  } else {
    setup_verbs_direct(&v, max_msg_size);
    establish_connections_direct(&v);
  }

  if (v.group_rank == 0) {
    const auto& cands = get_candidate_devices();
    const char* bench_name = (bench_mode == BENCH_BW ? "bw" :
                              (bench_mode == BENCH_JCT ? "jct" : "stream"));
    printf("\n=== Verbs RC RingAllReduce (%s) ===\n", use_cm ? "rdma_cm" : "direct");
    printf("ranks=%d max_msg_size=%zu bytes iters=%d warmup=%d bench=%s auto_port_probe=%d\n",
           v.size, max_msg_size, iters, warmup, bench_name,
           g_auto_port_probe ? 1 : 0);
    printf("jct_mode=%s peer_batch=%d inflight_per_peer=%d signal_interval=%d chunk_bytes=%zu phase_timing=%d stream_iter_barrier=%d stream_window=%d stream_start_barrier=%d stream_chunked_exchange=%d\n",
           (g_jct_mode == JCT_MODE_SAFE ? "safe" : "performance"),
           g_peer_batch, g_inflight_per_peer, g_signal_interval, g_chunk_bytes, g_phase_timing ? 1 : 0,
           g_stream_iter_barrier ? 1 : 0, g_stream_window, g_stream_start_barrier ? 1 : 0,
           g_stream_chunked_exchange ? 1 : 0);
    printf("candidate_devices=");
    for (size_t i = 0; i < cands.size(); i++) {
      printf("%s%s", cands[i].c_str(), (i + 1 == cands.size()) ? "" : ",");
    }
    printf("\n");
    printf("group_size=%d group_id=%d\n\n", v.group_size, v.group_id);
  }

  if (bench_mode == BENCH_BW) {
    v.msg_size = size_list[0];
    for (int i = 0; i < warmup; i++) {
      verbs_alltoall(&v);
    }

    if (v.group_rank == 0) printf("Verifying correctness...\n");
    verbs_alltoall(&v);
    verify_data(&v);

    MPI_Barrier(v.group_comm);

    if (v.group_rank == 0) printf("\nBenchmarking...\n");
    double t0 = now_sec();
    for (int i = 0; i < iters; i++) {
      verbs_alltoall(&v);
    }
    double t1 = now_sec();

    double elapsed = t1 - t0;
    double max_elapsed = 0.0;
    MPI_Reduce(&elapsed, &max_elapsed, 1, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);

    if (v.group_rank == 0) {
      double avg = max_elapsed / (double)iters;
      double total_bytes = (double)v.msg_size * 2.0 * (double)(v.group_size - 1) / (double)v.group_size;
      double bw_GBs = total_bytes / avg / 1e9;

      printf("Results:\n");
      printf("  total_time(max over ranks) = %.6f s\n", max_elapsed);
      printf("  avg_time_per_iter          = %.6f s\n", avg);
      printf("  effective_ring_bandwidth   = %.2f GB/s\n", bw_GBs);
      printf("\n");
    }
  } else {
    if (bench_mode == BENCH_STREAM) {
      int send_peer_world = v.group_world_ranks[(v.group_rank + 1) % v.group_size];
      int recv_peer_world = v.group_world_ranks[(v.group_rank - 1 + v.group_size) % v.group_size];
      if (v.group_rank == 0) {
        printf("stream,size_bytes,iters,p50_tx_us,p95_tx_us,p50_rx_us,p95_rx_us,p50_total_us,p95_total_us,tx_eff_gbps_p50,rx_eff_gbps_p50\n");
        if (dump_fct) {
          printf("stream_sample,size_bytes,iter,rank,tx_us,rx_us,total_us\n");
        }
      }
      for (size_t msg : size_list) {
        v.msg_size = msg;
        int stream_tag = 0;
        std::vector<double> local_tx(iters, 0.0);
        std::vector<double> local_rx(iters, 0.0);
        std::vector<double> local_total(iters, 0.0);
        if (g_stream_window > 1 && !g_stream_chunked_exchange) {
          if (warmup > 0) {
            std::vector<double> warm_tx((size_t)warmup, 0.0);
            std::vector<double> warm_rx((size_t)warmup, 0.0);
            std::vector<double> warm_total((size_t)warmup, 0.0);
            stream_exchange_windowed(&v, send_peer_world, recv_peer_world,
                                     stream_tag, warmup, warm_tx, warm_rx, warm_total);
            stream_tag += warmup;
          }
          MPI_Barrier(v.group_comm);
          stream_exchange_windowed(&v, send_peer_world, recv_peer_world,
                                   stream_tag, iters, local_tx, local_rx, local_total);
        } else {
          for (int i = 0; i < warmup; i++) {
            double tx_us = 0.0, rx_us = 0.0, total_us = 0.0;
            stream_exchange_neighbor(&v, send_peer_world, recv_peer_world, stream_tag++, &tx_us, &rx_us, &total_us);
          }
          MPI_Barrier(v.group_comm);
          for (int i = 0; i < iters; i++) {
            stream_exchange_neighbor(&v, send_peer_world, recv_peer_world, stream_tag++, &local_tx[i], &local_rx[i], &local_total[i]);
          }
        }

        std::vector<double> max_tx(iters, 0.0), max_rx(iters, 0.0), max_total(iters, 0.0);
        MPI_Reduce(local_tx.data(), max_tx.data(), iters, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);
        MPI_Reduce(local_rx.data(), max_rx.data(), iters, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);
        MPI_Reduce(local_total.data(), max_total.data(), iters, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);

        std::vector<double> packed((size_t)iters * 3, 0.0);
        for (int i = 0; i < iters; i++) {
          packed[(size_t)i * 3 + 0] = local_tx[i];
          packed[(size_t)i * 3 + 1] = local_rx[i];
          packed[(size_t)i * 3 + 2] = local_total[i];
        }
        std::vector<double> gathered;
        if (dump_fct && v.group_rank == 0) {
          gathered.resize((size_t)iters * (size_t)v.group_size * 3, 0.0);
        }
        MPI_Gather((dump_fct ? packed.data() : nullptr), (dump_fct ? iters * 3 : 0), MPI_DOUBLE,
                   ((dump_fct && v.group_rank == 0) ? gathered.data() : nullptr), (dump_fct ? iters * 3 : 0), MPI_DOUBLE,
                   0, v.group_comm);

        if (v.group_rank == 0) {
          if (dump_fct) {
            for (int gr = 0; gr < v.group_size; gr++) {
              int wrank = v.group_world_ranks[gr];
              for (int i = 0; i < iters; i++) {
                size_t off = (size_t)gr * (size_t)iters * 3 + (size_t)i * 3;
                printf("stream_sample,%zu,%d,%d,%.3f,%.3f,%.3f\n",
                       msg, i, wrank, gathered[off + 0], gathered[off + 1], gathered[off + 2]);
              }
            }
          }
          double p50_tx = percentile_us(max_tx, 50.0);
          double p95_tx = percentile_us(max_tx, 95.0);
          double p50_rx = percentile_us(max_rx, 50.0);
          double p95_rx = percentile_us(max_rx, 95.0);
          double p50_total = percentile_us(max_total, 50.0);
          double p95_total = percentile_us(max_total, 95.0);
          double tx_gbps_p50 = (p50_tx > 0.0) ? ((double)msg * 8.0) / (1000.0 * p50_tx) : 0.0;
          double rx_gbps_p50 = (p50_rx > 0.0) ? ((double)msg * 8.0) / (1000.0 * p50_rx) : 0.0;
          printf("stream,%zu,%d,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f\n",
                 msg, iters, p50_tx, p95_tx, p50_rx, p95_rx, p50_total, p95_total, tx_gbps_p50, rx_gbps_p50);
        }
      }
      cleanup(&v);
      MPI_Finalize();
      return 0;
    }
    if (v.group_rank == 0) {
      printf("mode,size_bytes,iters,p50_jct_us,p95_jct_us,p99_jct_us,min_jct_us,max_jct_us,outlier_ratio,nic_eff_gbps_p50,nic_eff_gbps_p95\n");
      if (dump_fct) {
        printf("fct_sample,size_bytes,iter,fct_us\n");
        if (v.group_size == 2) {
          printf("msg_fct_sample,size_bytes,iter,msg_step,src_world_rank,dst_world_rank,fct_us,eff_gbps\n");
        }
      }
      if (g_phase_timing) {
        printf("phase,size_bytes,avg_post_recv_us,avg_barrier_us,avg_post_send_us,avg_poll_cq_us\n");
        printf("peer_fct,size_bytes,peer_world_rank,max_avg_fct_us\n");
      }
    }
    for (size_t msg : size_list) {
      v.msg_size = msg;
      for (int i = 0; i < warmup; i++) {
        verbs_alltoall(&v);
      }

      verbs_alltoall(&v);
      verify_data(&v);
      MPI_Barrier(v.group_comm);

      std::vector<double> local_samples(iters, 0.0);
      std::vector<double> local_post_recv(iters, 0.0);
      std::vector<double> local_barrier(iters, 0.0);
      std::vector<double> local_post_send(iters, 0.0);
      std::vector<double> local_poll(iters, 0.0);
      std::vector<double> local_msg_fct_step0(iters, 0.0);
      std::vector<double> local_msg_fct_step1(iters, 0.0);
      std::vector<int> local_msg_dst_step0(iters, -1);
      std::vector<int> local_msg_dst_step1(iters, -1);
      std::vector<double> peer_sum(v.group_size, 0.0);
      std::vector<int> peer_cnt(v.group_size, 0);
      bool dump_msg_fct_np2 = dump_fct && (v.group_size == 2);
      for (int i = 0; i < iters; i++) {
        iter_phase_t phase;
        bool collect_phase = g_phase_timing || dump_msg_fct_np2;
        double t0 = now_sec();
        verbs_alltoall(&v, collect_phase ? &phase : nullptr);
        double t1 = now_sec();
        local_samples[i] = (t1 - t0) * 1e6;
        if (collect_phase) {
          if (dump_msg_fct_np2 && !phase.msg_send_us.empty()) {
            local_msg_fct_step0[i] = phase.msg_send_us[0];
            local_msg_dst_step0[i] = phase.msg_dst_world[0];
            if (phase.msg_send_us.size() > 1) {
              local_msg_fct_step1[i] = phase.msg_send_us[1];
              local_msg_dst_step1[i] = phase.msg_dst_world[1];
            }
          }
        }
        if (g_phase_timing) {
          local_post_recv[i] = phase.post_recv_us;
          local_barrier[i] = phase.barrier_us;
          local_post_send[i] = phase.post_send_us;
          local_poll[i] = phase.poll_cq_us;
          for (int gi = 0; gi < v.group_size; gi++) {
            int peer = v.group_world_ranks[gi];
            if (peer == v.rank) continue;
            if (phase.peer_send_us.size() == (size_t)v.group_size && phase.peer_send_us[gi] > 0.0) {
              peer_sum[gi] += phase.peer_send_us[gi];
              peer_cnt[gi]++;
            }
          }
        }
      }

      std::vector<double> max_samples(iters, 0.0);
      MPI_Reduce(local_samples.data(), max_samples.data(), iters, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);
      std::vector<double> gathered_msg_fct_step0;
      std::vector<double> gathered_msg_fct_step1;
      std::vector<int> gathered_msg_dst_step0;
      std::vector<int> gathered_msg_dst_step1;
      if (dump_msg_fct_np2) {
        if (v.group_rank == 0) {
          size_t total = (size_t)iters * (size_t)v.group_size;
          gathered_msg_fct_step0.resize(total, 0.0);
          gathered_msg_fct_step1.resize(total, 0.0);
          gathered_msg_dst_step0.resize(total, -1);
          gathered_msg_dst_step1.resize(total, -1);
        }
        MPI_Gather(local_msg_fct_step0.data(), iters, MPI_DOUBLE,
                   (v.group_rank == 0 ? gathered_msg_fct_step0.data() : nullptr), iters, MPI_DOUBLE,
                   0, v.group_comm);
        MPI_Gather(local_msg_fct_step1.data(), iters, MPI_DOUBLE,
                   (v.group_rank == 0 ? gathered_msg_fct_step1.data() : nullptr), iters, MPI_DOUBLE,
                   0, v.group_comm);
        MPI_Gather(local_msg_dst_step0.data(), iters, MPI_INT,
                   (v.group_rank == 0 ? gathered_msg_dst_step0.data() : nullptr), iters, MPI_INT,
                   0, v.group_comm);
        MPI_Gather(local_msg_dst_step1.data(), iters, MPI_INT,
                   (v.group_rank == 0 ? gathered_msg_dst_step1.data() : nullptr), iters, MPI_INT,
                   0, v.group_comm);
      }
      std::vector<double> max_post_recv(iters, 0.0), max_barrier(iters, 0.0), max_post_send(iters, 0.0), max_poll(iters, 0.0);
      if (g_phase_timing) {
        MPI_Reduce(local_post_recv.data(), max_post_recv.data(), iters, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);
        MPI_Reduce(local_barrier.data(), max_barrier.data(), iters, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);
        MPI_Reduce(local_post_send.data(), max_post_send.data(), iters, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);
        MPI_Reduce(local_poll.data(), max_poll.data(), iters, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);
      }

      std::vector<double> peer_mean(v.group_size, 0.0);
      for (int gi = 0; gi < v.group_size; gi++) {
        if (peer_cnt[gi] > 0) peer_mean[gi] = peer_sum[gi] / (double)peer_cnt[gi];
      }
      std::vector<double> peer_mean_max(v.group_size, 0.0);
      if (g_phase_timing) {
        MPI_Reduce(peer_mean.data(), peer_mean_max.data(), v.group_size, MPI_DOUBLE, MPI_MAX, 0, v.group_comm);
      }

      if (v.group_rank == 0) {
        if (dump_fct) {
          for (int i = 0; i < iters; i++) {
            printf("fct_sample,%zu,%d,%.3f\n", msg, i, max_samples[i]);
          }
          if (dump_msg_fct_np2) {
            for (int i = 0; i < iters; i++) {
              for (int gr = 0; gr < v.group_size; gr++) {
                size_t off = (size_t)gr * (size_t)iters + (size_t)i;
                int src_world = v.group_world_ranks[gr];
                double fct0 = gathered_msg_fct_step0[off];
                int dst0 = gathered_msg_dst_step0[off];
                if (fct0 > 0.0 && dst0 >= 0) {
                  int dst_world = dst0;
                  int dst_gr = dst_world - v.group_id * v.group_size;
                  if (dst_gr >= 0 && dst_gr < v.group_size) {
                    dst_world = v.group_world_ranks[dst_gr];
                  }
                  double eff_gbps = ((double)msg * 8.0) / (2.0 * 1000.0 * fct0);
                  printf("msg_fct_sample,%zu,%d,0,%d,%d,%.3f,%.3f\n",
                         msg, i, src_world, dst_world, fct0, eff_gbps);
                }
                double fct1 = gathered_msg_fct_step1[off];
                int dst1 = gathered_msg_dst_step1[off];
                if (fct1 > 0.0 && dst1 >= 0) {
                  int dst_world = dst1;
                  int dst_gr = dst_world - v.group_id * v.group_size;
                  if (dst_gr >= 0 && dst_gr < v.group_size) {
                    dst_world = v.group_world_ranks[dst_gr];
                  }
                  double eff_gbps = ((double)msg * 8.0) / (2.0 * 1000.0 * fct1);
                  printf("msg_fct_sample,%zu,%d,1,%d,%d,%.3f,%.3f\n",
                         msg, i, src_world, dst_world, fct1, eff_gbps);
                }
              }
            }
          }
        }
        std::vector<double> nic_eff_gbps(max_samples.size(), 0.0);
        double bytes_per_rank = (double)msg * 2.0 * (double)(v.group_size - 1) / (double)v.group_size;
        for (size_t i = 0; i < max_samples.size(); i++) {
          double us = max_samples[i];
          if (us > 0.0) nic_eff_gbps[i] = (bytes_per_rank * 8.0) / (1000.0 * us);
        }
        double p50 = percentile_us(max_samples, 50.0);
        double p95 = percentile_us(max_samples, 95.0);
        double p99 = percentile_us(max_samples, 99.0);
        double nic_p50 = percentile_us(nic_eff_gbps, 50.0);
        double nic_p95 = percentile_us(nic_eff_gbps, 95.0);
        double mn = *std::min_element(max_samples.begin(), max_samples.end());
        double mx = *std::max_element(max_samples.begin(), max_samples.end());
        int outliers = 0;
        for (double x : max_samples) if (x > 3.0 * p50) outliers++;
        double outlier_ratio = (double)outliers / (double)iters;
        printf("jct,%zu,%d,%.3f,%.3f,%.3f,%.3f,%.3f,%.4f,%.3f,%.3f\n",
               msg, iters, p50, p95, p99, mn, mx, outlier_ratio, nic_p50, nic_p95);
        if (g_phase_timing) {
          double avg_post_recv = std::accumulate(max_post_recv.begin(), max_post_recv.end(), 0.0) / (double)iters;
          double avg_barrier = std::accumulate(max_barrier.begin(), max_barrier.end(), 0.0) / (double)iters;
          double avg_post_send = std::accumulate(max_post_send.begin(), max_post_send.end(), 0.0) / (double)iters;
          double avg_poll = std::accumulate(max_poll.begin(), max_poll.end(), 0.0) / (double)iters;
          printf("phase,%zu,%.3f,%.3f,%.3f,%.3f\n",
                 msg, avg_post_recv, avg_barrier, avg_post_send, avg_poll);
          for (int gi = 0; gi < v.group_size; gi++) {
            int peer = v.group_world_ranks[gi];
            if (peer == v.rank) continue;
            printf("peer_fct,%zu,%d,%.3f\n", msg, peer, peer_mean_max[gi]);
          }
        }
      }
    }
  }

  cleanup(&v);
  MPI_Finalize();
  return 0;
}
