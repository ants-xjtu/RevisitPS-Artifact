#!/usr/bin/env python3
"""
big_switch_topo_gen.py
以“服务器 → Big‑Switch”编号顺序输出 Big‑Switch 拓扑。
生成的 .txt 文件格式与 Leaf‑Spine / Fat‑Tree 版保持完全一致：

    第 1 行:   <总节点数> <交换机节点数> <链路数>
    第 2 行:   <所有交换机节点 ID（空格分隔）>
    第 3‥n 行: <src> <dst> <速率>Gbps <时延>ns <错误率>

若需要 trace 文件，则在脚本底部打开相应代码。
"""

# ── 可调参数 ────────────────────────────────────────────────────────────
n_hosts            = 128    # 服务器总数
link_rate_gbps     = 100    # 端口速率 (Gbps)
link_latency_ns    = 2000   # 单向传播时延 (ns)
# ───────────────────────────────────────────────────────────────────────

# 基本数值
n_switch_total  = 1                     # 仅 1 台 “大交换机”
n_nodes_total   = n_hosts + n_switch_total
n_links_total   = n_hosts               # host‑switch 单向链路共 n_hosts 条

# ID 规划
id_big_switch   = n_hosts               # 大交换机编号（服务器编号 0‥n_hosts‑1）

# 输出文件名
fname_topo = f"bigswitch_H{n_hosts}_{link_rate_gbps}G_OS1.txt"

with open(fname_topo, "w") as f:
    # header 1
    f.write(f"{n_nodes_total} {n_switch_total} {n_links_total}\n")
    # header 2：所有交换机 ID
    f.write(str(id_big_switch) + "\n")

    # 服务器 ↔ Big‑Switch
    for host_id in range(n_hosts):
        f.write(f"{host_id} {id_big_switch} {link_rate_gbps}Gbps {link_latency_ns}ns 0.000000\n")

print(f"Big‑Switch 拓扑已写入: {fname_topo}")
print(f"  总节点  : {n_nodes_total}")
print(f"  交换机  : {n_switch_total} (ID {id_big_switch})")
print(f"  服务器  : {n_hosts}")
print(f"  链路总数: {n_links_total}")

# ----------------------------------------------------------------------
# 如需生成一个简易的服务器 trace 文件（仅列出服务器总数与所有服务器 ID），
# 取消下方注释即可。
# ----------------------------------------------------------------------
#
# fname_trace = f"bigswitch_H{n_hosts}_trace.txt"
# with open(fname_trace, "w") as tf:
#     tf.write(str(n_hosts) + "\n")
#     tf.write(" ".join(str(i) for i in range(n_hosts)) + "\n")
# print(f"Trace 文件已写入: {fname_trace}")
