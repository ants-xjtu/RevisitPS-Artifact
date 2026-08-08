#!/usr/bin/env python3
"""
leaf_spine_topo_gen.py
以“服务器 → Leaf → Spine”编号顺序输出 Leaf‑Spine 拓扑。
生成的 .txt 文件格式与 Fat‑Tree 版保持完全一致：

    第 1 行:   <总节点数> <交换机节点数> <链路数>
    第 2 行:   <所有交换机节点 ID（空格分隔）>
    第 3‥n 行: <src> <dst> <速率>Gbps <时延>ns <错误率>

若需要 trace 文件，则在脚本底部打开相应代码。
"""

# ── 可调参数 ────────────────────────────────────────────────────────────
n_leaf              = 16     # Leaf 交换机数量
n_spine             = 16     # Spine 交换机数量
servers_per_leaf    = 16    # 每台 Leaf 下挂服务器数
link_rate_gbps      = 100   # 端口速率 (Gbps)
link_latency_ns     = 1000  # 单向传播时延 (ns)
oversubscript       = round((n_leaf * servers_per_leaf) / (n_leaf * n_spine), 2)  # 计算 OS 比例（可选固定）
# ───────────────────────────────────────────────────────────────────────

# 基本数值
n_servers_total = n_leaf * servers_per_leaf
n_switch_total  = n_leaf + n_spine
n_nodes_total   = n_servers_total + n_switch_total
n_links_total   = n_servers_total + n_leaf * n_spine   # server–leaf + leaf–spine

# ID 区间
id_offset_leaf  = n_servers_total                      # 第 1 台 Leaf 的编号
id_offset_spine = id_offset_leaf + n_leaf              # 第 1 台 Spine 的编号

# 输出文件名
fname_topo = f"leafspine_L{n_leaf}_S{n_spine}_{link_rate_gbps}G_OS{oversubscript}.txt"


with open(fname_topo, "w") as f:
    # header 1
    f.write(f"{n_nodes_total} {n_switch_total} {n_links_total}\n")
    # header 2：所有交换机 ID
    switch_ids = " ".join(str(i) for i in range(n_servers_total, n_nodes_total))
    f.write(switch_ids + "\n")

    # ① server ↔ leaf
    for leaf in range(n_leaf):
        leaf_id = id_offset_leaf + leaf
        for srv_idx in range(servers_per_leaf):
            srv_id = leaf * servers_per_leaf + srv_idx
            f.write(f"{srv_id} {leaf_id} {link_rate_gbps}Gbps {link_latency_ns}ns 0.000000\n")

    # ② leaf ↔ spine（全互连）
    for leaf in range(n_leaf):
        leaf_id = id_offset_leaf + leaf
        for spine in range(n_spine):
            spine_id = id_offset_spine + spine
            f.write(f"{leaf_id} {spine_id} {link_rate_gbps}Gbps {link_latency_ns}ns 0.000000\n")

print(f"Leaf–Spine 拓扑已写入: {fname_topo}")
print(f"  总节点  : {n_nodes_total}")
print(f"  交换机  : {n_switch_total} (Leaf {n_leaf}, Spine {n_spine})")
print(f"  服务器  : {n_servers_total} (每 Leaf {servers_per_leaf})")
print(f"  链路总数: {n_links_total}")

# ----------------------------------------------------------------------
# 如需生成一个简易的服务器 trace 文件（仅列出服务器总数与所有服务器 ID），
# 取消下方注释即可。
# ----------------------------------------------------------------------
#
# fname_trace = f"leafspine_L{n_leaf}_trace.txt"
# with open(fname_trace, "w") as tf:
#     tf.write(str(n_servers_total) + "\n")
#     tf.write(" ".join(str(i) for i in range(n_servers_total)) + "\n")
# print(f"Trace 文件已写入: {fname_trace}")
