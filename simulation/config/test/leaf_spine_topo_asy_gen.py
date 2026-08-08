#!/usr/bin/env python3
"""
leaf_spine_topo_asy_gen.py
生成 Leaf-Spine 拓扑文件 (.txt) 和 对应的 Per-Destination 权重文件 (_weight.txt)。

权重逻辑：Path-Aware (路径感知)
对于流量 Src_Leaf -> Spine -> Dst_Leaf：
    Weight = min( Bandwidth(Src->Spine), Bandwidth(Spine->Dst) )

输出格式：
    Topology: NS-3 标准格式
    Weights:  SrcNodeID DstNodeID OutPortID Weight
"""

import random
from collections import defaultdict


def fmt_num(x):
    """统一数值格式化：整数不带小数点，否则保留 2 位小数。"""
    x = float(x)
    return int(x) if x.is_integer() else round(x, 2)


# ── 可调参数 ────────────────────────────────────────────────────────────
n_leaf              = 8     # Leaf 交换机数量
n_spine             = 16    # Spine 交换机数量
servers_per_leaf    = 16    # 每台 Leaf 下挂服务器数
link_rate_gbps      = 100.0 # 默认端口速率 (Gbps)
link_latency_ns     = 1000  # 默认单向传播时延 (ns)

# --- 不对称模式 (三选一，互斥) ---
#   "degrade" : 随机选一批 Leaf-Spine 链路降速（保留链路，改带宽）
#   "fail"    : 随机选一批 Leaf-Spine 链路失效（从拓扑中完全移除）
#   "delay"   : 随机选一批 Leaf-Spine 链路增大单向时延（带宽不变）
ASYM_MODE = "degrade"

# Mode "degrade" 专用参数
degrade_percentage  = 10    # 被降速链路占比 (%)
degrade_ratio       = 0.5   # 降速后带宽比例 (0.5 = 50Gbps)

# Mode "fail" 专用参数
fail_percentage     = 10    # 被失效链路占比 (%)

# Mode "delay" 专用参数
delay_percentage    = 10    # 被加延迟链路占比 (%)
delay_latency_ns    = 10000 # 加延迟后单向时延 (ns)，默认 10us

random_seed         = 42    # 固定随机种子，保证每次生成结果可复现

# --- Debug 开关 ---
DEBUG_GROUP         = True  # True 时额外写出 *_group_debug.txt，包含分组推导过程

# ───────────────────────────────────────────────────────────────────────

assert ASYM_MODE in ("degrade", "fail", "delay"), f"unknown ASYM_MODE={ASYM_MODE}"
random.seed(random_seed)

# 基础 ID 计算
n_servers_total = n_leaf * servers_per_leaf
n_switch_total  = n_leaf + n_spine
n_nodes_total   = n_servers_total + n_switch_total

id_offset_leaf  = n_servers_total
id_offset_spine = id_offset_leaf + n_leaf

# 计算 Oversubscription 用于文件名
oversubscript = round((n_leaf * servers_per_leaf) / (n_leaf * n_spine), 2)

# ── 第一步：按模式抽样被影响的链路集合 ──
all_ls_pairs   = [(l, s) for l in range(n_leaf) for s in range(n_spine)]
failed_pairs   = set()
degraded_pairs = set()
delayed_pairs  = set()

if ASYM_MODE == "degrade":
    n_pick = int(len(all_ls_pairs) * (degrade_percentage / 100.0))
    degraded_pairs = set(random.sample(all_ls_pairs, n_pick))
    asym_tag = f"AsymBw{degrade_percentage}pct_R{degrade_ratio}"
elif ASYM_MODE == "fail":
    n_pick = int(len(all_ls_pairs) * (fail_percentage / 100.0))
    failed_pairs = set(random.sample(all_ls_pairs, n_pick))
    asym_tag = f"AsymFail{fail_percentage}pct"
else:  # "delay"
    n_pick = int(len(all_ls_pairs) * (delay_percentage / 100.0))
    delayed_pairs = set(random.sample(all_ls_pairs, n_pick))
    asym_tag = f"AsymDelay{delay_percentage}pct_{delay_latency_ns // 1000}us"

# 失效链路会从拓扑中完全移除，要相应减少 num_links
n_links_total = n_servers_total + n_leaf * n_spine - len(failed_pairs)

# 文件名生成（包含模式标签）
base_name = f"leafspine_L{n_leaf}_S{n_spine}_{int(link_rate_gbps)}G_{asym_tag}_OS{oversubscript}"
fname_topo        = base_name + ".txt"
fname_weight      = base_name + "_weight.txt"
fname_group       = base_name + "_group.txt"
fname_group_debug = base_name + "_group_debug.txt"


# ── 第二步：构建带宽矩阵和时延矩阵 ──
#   失效链路：bw=0（生成 topo 时跳过；weight/group 会因 cap<=0 被忽略）
#   降速链路：bw = rate * ratio；时延不变
#   加延迟链路：bw 不变；时延 = delay_latency_ns
bw_matrix      = {}
latency_matrix = {}
for leaf in range(n_leaf):
    for spine in range(n_spine):
        if (leaf, spine) in failed_pairs:
            bw_matrix[(leaf, spine)]      = 0.0
            latency_matrix[(leaf, spine)] = link_latency_ns
        elif (leaf, spine) in degraded_pairs:
            bw_matrix[(leaf, spine)]      = link_rate_gbps * degrade_ratio
            latency_matrix[(leaf, spine)] = link_latency_ns
        elif (leaf, spine) in delayed_pairs:
            bw_matrix[(leaf, spine)]      = link_rate_gbps
            latency_matrix[(leaf, spine)] = delay_latency_ns
        else:
            bw_matrix[(leaf, spine)]      = link_rate_gbps
            latency_matrix[(leaf, spine)] = link_latency_ns


# ── 第三步：写入拓扑文件并记录端口映射 ──
# NS-3 设备索引从 1 开始 (0 通常是 Loopback)
# port_counter[node_id] = next_port_index
port_counter = {i: 1 for i in range(id_offset_leaf, n_nodes_total)}

# 记录：Leaf L 连接到 Spine S 使用的是哪个 Port
# leaf_to_spine_port[leaf_idx][spine_idx] = port_id
# 失效链路不会出现在这个映射里，下游查不到就跳过。
leaf_to_spine_port = {l: {} for l in range(n_leaf)}

print(f"Generating Topology: {fname_topo}")

with open(fname_topo, "w") as f:
    # Header
    f.write(f"{n_nodes_total} {n_switch_total} {n_links_total}\n")
    f.write(" ".join(str(i) for i in range(n_servers_total, n_nodes_total)) + "\n")

    # 1. Server <-> Leaf 链路
    # 这些链路先建立，占用 Leaf 的低号端口
    for leaf in range(n_leaf):
        leaf_id = id_offset_leaf + leaf
        for srv_idx in range(servers_per_leaf):
            srv_id = leaf * servers_per_leaf + srv_idx

            # 写入拓扑 (Server侧连接)
            f.write(f"{srv_id} {leaf_id} {int(link_rate_gbps)}Gbps {link_latency_ns}ns 0.000000\n")

            # 更新 Leaf 的端口计数 (连接了一个 Server)
            port_counter[leaf_id] += 1

    # 2. Leaf <-> Spine 链路
    # 这些链路后建立，占用 Leaf 的高号端口 (即 Uplink ports)
    # 注意：失效链路完全不写出；端口号因此在不同 Leaf 上可能错位。
    for leaf in range(n_leaf):
        leaf_id = id_offset_leaf + leaf
        for spine in range(n_spine):
            # 失效链路：完全不写入拓扑，也不占用端口号
            if (leaf, spine) in failed_pairs:
                continue

            spine_id = id_offset_spine + spine

            # 查带宽矩阵 / 时延矩阵
            real_bw  = bw_matrix[(leaf, spine)]
            real_lat = latency_matrix[(leaf, spine)]
            # 格式化输出 (如果是整数不带小数点，否则保留2位)
            bw_str = int(real_bw) if real_bw.is_integer() else round(real_bw, 2)

            # 写入拓扑
            f.write(f"{leaf_id} {spine_id} {bw_str}Gbps {real_lat}ns 0.000000\n")

            # 记录端口信息以便生成权重
            current_port = port_counter[leaf_id]
            leaf_to_spine_port[leaf][spine] = current_port

            # 更新两端的端口计数
            port_counter[leaf_id] += 1
            port_counter[spine_id] += 1


# ── 第四步：生成 Per-Destination 权重文件 ──
# 遍历所有 Src Leaf -> Dst Leaf 的组合，计算每一条通过 Spine 的路径权重
weight_records = []

print(f"Generating Weights: {fname_weight}")

for src_leaf in range(n_leaf):
    src_id = id_offset_leaf + src_leaf

    for dst_leaf in range(n_leaf):
        # 相同 Leaf 内的通信不走 Spine，不需要生成权重
        if src_leaf == dst_leaf:
            continue

        dst_id = id_offset_leaf + dst_leaf

        # 遍历所有可能的 Spine 路径
        for spine in range(n_spine):
            # 1. 获取 Src -> Spine 的上行带宽
            bw_up = bw_matrix[(src_leaf, spine)]

            # 2. 获取 Spine -> Dst 的下行带宽
            # (假设链路是对称双向的，所以直接查 (dst, spine) 即可)
            bw_down = bw_matrix[(dst_leaf, spine)]

            # 失效链路（bw=0）：这条路径不存在，跳过
            if bw_up <= 0 or bw_down <= 0:
                continue

            # 3. 计算路径瓶颈带宽 (Bottleneck Bandwidth)
            path_weight = min(bw_up, bw_down)

            # 4. 获取出端口号
            out_port = leaf_to_spine_port[src_leaf][spine]

            # 格式化权重
            w_val = int(path_weight) if path_weight.is_integer() else round(path_weight, 2)

            # 记录: SrcNodeID DstNodeID OutPortID Weight
            weight_records.append((src_id, dst_id, out_port, w_val))

# 写入权重文件
with open(fname_weight, "w") as fw:
    for src, dst, port, w in weight_records:
        fw.write(f"{src} {dst} {port} {w}\n")

# ── 第五步：生成 DRILL-style group 文件（基于 Quiver 算法）────────────
# group 文件格式:
#     SrcNodeID DstNodeID OutPortID GroupID GroupWeight
#
# 路径标签:
#     每条 (src_leaf, dst_leaf, spine) 路径 p 携带一个 label
#         (src, dst, cf)
#     其中 cf = bw(src_leaf -> spine) / bw(spine -> dst_leaf)
#     该 label 同时盖在 p 经过的上行链路 (src_leaf, spine)
#     和下行链路 (spine, dst_leaf) 上。
#
# 链路 score:
#     link_score(e) = hash( 该链路承载的所有路径 label 的多重集 )
#
# 路径 score:
#     path_score(p) = ( link_score(uplink_e), link_score(downlink_e) )
#
# 分组:
#     同一 (src, dst) 下 path_score 相同的路径属于同一个 group。
#
# group weight:
#     sum(path bottleneck capacity) over paths in that group,
#     即组内各路径 min(bw_up, bw_down) 之和。

# ── Step A: 构建 Quiver 上每条物理链路的标签多重集 ──
uplink_labels   = defaultdict(list)   # key = (leaf_a, spine_i)
downlink_labels = defaultdict(list)   # key = (spine_i, leaf_d)

for src_leaf in range(n_leaf):
    for dst_leaf in range(n_leaf):
        if src_leaf == dst_leaf:
            continue
        for spine in range(n_spine):
            cap_up   = bw_matrix[(src_leaf, spine)]
            cap_down = bw_matrix[(dst_leaf, spine)]
            # 异常链路直接跳过，不进入 Quiver
            if cap_up <= 0 or cap_down <= 0:
                continue
            cf = cap_up / cap_down
            label = (src_leaf, dst_leaf, fmt_num(cf))
            uplink_labels[(src_leaf, spine)].append(label)
            downlink_labels[(spine, dst_leaf)].append(label)

# ── Step B: link score = 对 (排序后的 label 多重集) 按首次出现分配的小整数 ID ──
#   相同 label 集合 → 相同 ID；上/下行各自独立编号。
def canonical(labels):
    return tuple(sorted(labels))

def assign_ids(label_dict):
    sig_to_id = {}     # canonical tuple -> int
    score_map = {}     # link key -> int
    for k, v in label_dict.items():
        sig = canonical(v)
        if sig not in sig_to_id:
            sig_to_id[sig] = len(sig_to_id)
        score_map[k] = sig_to_id[sig]
    return score_map, sig_to_id

uplink_score,   uplink_sig_to_id   = assign_ids(uplink_labels)
downlink_score, downlink_sig_to_id = assign_ids(downlink_labels)

# ── Step C: 对每个 (src, dst) 按 path_score 分组 ──
group_records = []
# Debug 统计：每对 (src,dst) 分成多少组
ngroups_per_pair = []

print(f"Generating Groups: {fname_group}")

# 打开 debug 文件（如果开关打开）
dbg = open(fname_group_debug, "w") if DEBUG_GROUP else None
if dbg:
    dbg.write(f"# DRILL group debug for {base_name}\n")
    dbg.write(f"# n_leaf={n_leaf} n_spine={n_spine} mode={ASYM_MODE}\n")
    if ASYM_MODE == "degrade":
        dbg.write(f"# degrade_pct={degrade_percentage} ratio={degrade_ratio}\n")
        dbg.write(f"# degraded_pairs (leaf_idx, spine_idx): "
                  f"{sorted(degraded_pairs)}\n")
    elif ASYM_MODE == "fail":
        dbg.write(f"# fail_pct={fail_percentage}\n")
        dbg.write(f"# failed_pairs (leaf_idx, spine_idx): "
                  f"{sorted(failed_pairs)}\n")
    else:  # "delay"
        dbg.write(f"# delay_pct={delay_percentage} "
                  f"delay_ns={delay_latency_ns} (default={link_latency_ns})\n")
        dbg.write(f"# delayed_pairs (leaf_idx, spine_idx): "
                  f"{sorted(delayed_pairs)}\n")
    dbg.write("#\n")

    # ── Section 1: 每个唯一 uplink / downlink score 对应的 label 集合 ──
    dbg.write(f"# {'=' * 70}\n")
    dbg.write(f"# Uplink link-score catalog "
              f"({len(uplink_sig_to_id)} unique out of {len(uplink_labels)} uplinks)\n")
    dbg.write(f"#   each entry: up_score=<id>  links=[(leaf,spine)...]\n"
              f"#               labels=[(src,dst,cf)...]\n")
    dbg.write(f"# {'=' * 70}\n")
    # 反查：id -> [link keys]
    up_id_to_links = defaultdict(list)
    for k, sid in uplink_score.items():
        up_id_to_links[sid].append(k)
    for sid in sorted(up_id_to_links):
        links = sorted(up_id_to_links[sid])
        # 任取一条 link 拿出它的 canonical label 列表
        sample_labels = canonical(uplink_labels[links[0]])
        dbg.write(f"up_score={sid:2d}  links={links}\n")
        dbg.write(f"             labels={list(sample_labels)}\n")
    dbg.write("\n")

    dbg.write(f"# {'=' * 70}\n")
    dbg.write(f"# Downlink link-score catalog "
              f"({len(downlink_sig_to_id)} unique out of {len(downlink_labels)} downlinks)\n")
    dbg.write(f"#   each entry: dn_score=<id>  links=[(spine,leaf)...]\n"
              f"#               labels=[(src,dst,cf)...]\n")
    dbg.write(f"# {'=' * 70}\n")
    dn_id_to_links = defaultdict(list)
    for k, sid in downlink_score.items():
        dn_id_to_links[sid].append(k)
    for sid in sorted(dn_id_to_links):
        links = sorted(dn_id_to_links[sid])
        sample_labels = canonical(downlink_labels[links[0]])
        dbg.write(f"dn_score={sid:2d}  links={links}\n")
        dbg.write(f"             labels={list(sample_labels)}\n")
    dbg.write("\n")

    dbg.write("# Per-(src,dst) block:\n")
    dbg.write("#   path line : spine=<i> port=<p> bw_up=<.> bw_down=<.> "
              "cf=<.> pcap=<.>\n")
    dbg.write("#               up_score=<.> dn_score=<.> pscore=(u,d) -> gid=<g>\n")
    dbg.write("#   group line: gid=<g> pscore=(u,d) spines=[...] gweight=<.>\n")
    dbg.write("#" + "=" * 70 + "\n\n")

for src_leaf in range(n_leaf):
    src_id = id_offset_leaf + src_leaf

    for dst_leaf in range(n_leaf):
        if src_leaf == dst_leaf:
            continue

        dst_id = id_offset_leaf + dst_leaf

        # 收集该 (src, dst) 的所有候选路径（每个 spine 一条）
        paths = []
        for spine in range(n_spine):
            cap_up   = bw_matrix[(src_leaf, spine)]
            cap_down = bw_matrix[(dst_leaf, spine)]
            if cap_up <= 0 or cap_down <= 0:
                continue

            pscore = (
                uplink_score[(src_leaf, spine)],
                downlink_score[(spine, dst_leaf)],
            )
            pcap = min(cap_up, cap_down)
            paths.append({
                "spine":    spine,
                "out_port": leaf_to_spine_port[src_leaf][spine],
                "pscore":   pscore,
                "pcap":     pcap,
                "bw_up":    cap_up,
                "bw_down":  cap_down,
                "cf":       cap_up / cap_down,
            })

        # 按 path_score 分配 group id（首次出现即登记）
        pscore_to_gid = {}
        for p in paths:
            if p["pscore"] not in pscore_to_gid:
                pscore_to_gid[p["pscore"]] = len(pscore_to_gid)
            p["gid"] = pscore_to_gid[p["pscore"]]

        # group weight = 组内路径 bottleneck capacity 之和
        group_weight = defaultdict(float)
        group_members = defaultdict(list)   # gid -> [spine ...]
        for p in paths:
            group_weight[p["gid"]] += p["pcap"]
            group_members[p["gid"]].append(p["spine"])

        # 每条 path 输出一行（同组的行共享相同 gid / GroupWeight）
        for p in paths:
            group_records.append((
                src_id,
                dst_id,
                p["out_port"],
                p["gid"],
                fmt_num(group_weight[p["gid"]]),
            ))

        ngroups_per_pair.append(len(pscore_to_gid))

        # Debug: 打印该 (src, dst) 的所有路径和分组结果
        if dbg:
            dbg.write(f"=== src_leaf={src_leaf} (id={src_id})  "
                      f"dst_leaf={dst_leaf} (id={dst_id})  "
                      f"n_paths={len(paths)}  n_groups={len(pscore_to_gid)} ===\n")
            for p in paths:
                u_sc, d_sc = p["pscore"]
                dbg.write(
                    f"  path : spine={p['spine']:2d}  port={p['out_port']:3d}  "
                    f"bw_up={fmt_num(p['bw_up']):>6}  "
                    f"bw_down={fmt_num(p['bw_down']):>6}  "
                    f"cf={fmt_num(p['cf']):>5}  "
                    f"pcap={fmt_num(p['pcap']):>5}  "
                    f"up_score={u_sc:2d}  dn_score={d_sc:2d}  "
                    f"pscore=({u_sc},{d_sc})  -> gid={p['gid']}\n"
                )
            # 取每个 gid 的代表 pscore
            gid_to_pscore = {p["gid"]: p["pscore"] for p in paths}
            for gid in sorted(group_members.keys()):
                ps = gid_to_pscore[gid]
                dbg.write(
                    f"  group: gid={gid}  pscore=({ps[0]},{ps[1]})  "
                    f"spines={group_members[gid]}  "
                    f"gweight={fmt_num(group_weight[gid])}\n"
                )
            dbg.write("\n")

if dbg:
    dbg.close()

with open(fname_group, "w") as fg:
    for src, dst, port, gid, gw in group_records:
        fg.write(f"{src} {dst} {port} {gid} {gw}\n")

print("-" * 40)
print(f"Done.")
print(f"Topo Nodes    : {n_nodes_total}")
print(f"Topo Links    : {n_links_total}")
print(f"Asym Mode     : {ASYM_MODE}")
if ASYM_MODE == "degrade":
    print(f"Degraded Links: {len(degraded_pairs)} "
          f"({degrade_percentage}%) @ ratio={degrade_ratio}")
elif ASYM_MODE == "fail":
    print(f"Failed Links  : {len(failed_pairs)} "
          f"({fail_percentage}%) -- removed from topo")
else:
    print(f"Delayed Links : {len(delayed_pairs)} "
          f"({delay_percentage}%) @ {delay_latency_ns}ns "
          f"(default {link_latency_ns}ns)")
print(f"Weight Format : SrcID DstID PortID Weight")
print(f"Group  Format : SrcID DstID PortID GroupID GroupWeight")
if ngroups_per_pair:
    from collections import Counter
    dist = Counter(ngroups_per_pair)
    print(f"Group Stats   : {len(ngroups_per_pair)} (src,dst) pairs | "
          f"min={min(ngroups_per_pair)}  max={max(ngroups_per_pair)}  "
          f"avg={sum(ngroups_per_pair)/len(ngroups_per_pair):.2f}")
    print(f"                #groups distribution: "
          f"{dict(sorted(dist.items()))}")
if DEBUG_GROUP:
    print(f"Group Debug   : {fname_group_debug}")
print("-" * 40)
# ```

# ### ⚠️ 重要提示：请同步修改 C++ 代码

# 由于你要求的格式是 `nodeid dstid portid weight`（即 **源 -> 目的 -> 端口 -> 权重**），你需要确保你的 `main.cc` 中的读取逻辑与此顺序匹配。

# 请检查 `main.cc` 中读取 `WEIGHT_FILE` 的部分，确保变量顺序如下：

# ```cpp
# // 在 main.cc 中读取权重文件的部分：
# if (wf.is_open()) {
#     uint32_t src_id, dst_id, port_id; // 注意变量声明
#     double w;
    
#     // 必须按照 Python 生成的顺序读取：Src, Dst, Port, Weight
#     while (wf >> src_id >> dst_id >> port_id >> w) {
        
#         // 存入 Map (Src -> Dst -> Port -> Weight)
#         Settings::smartWeights[src_id][dst_id][port_id] = w;
#     }
#     wf.close();
# }