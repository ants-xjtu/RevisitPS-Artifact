def estimate_flows(nhost, bandwidth_str, load, avg_flow_size_bytes, time_s):
    # 解析带宽字符串，支持 G, M, K 单位
    def translate_bandwidth(b):
        if b[-1] == 'G':
            return float(b[:-1]) * 1e9
        elif b[-1] == 'M':
            return float(b[:-1]) * 1e6
        elif b[-1] == 'K':
            return float(b[:-1]) * 1e3
        else:
            return float(b)

    bandwidth_bps = translate_bandwidth(bandwidth_str)  # 转为 bps

    # 计算有效带宽(字节/s)
    effective_bandwidth_bytes_per_s = bandwidth_bps * load / 8.0

    # 每秒能发出的流数量
    flow_per_second_per_host = effective_bandwidth_bytes_per_s / avg_flow_size_bytes

    # 计算平均流间隔时间(s)
    avg_inter_arrival = 1.0 / flow_per_second_per_host

    # 总流数
    total_flows = int(time_s / avg_inter_arrival * nhost)

    return total_flows


if __name__ == "__main__":
    # 输入参数
    nhost = 128
    bandwidth = "100G"
    load = 0.9
    avg_flow_sizes = [121848.94, 39423.50, 40869.80, 2967.89]  # B
    time_ms = 20
    time_s = time_ms / 1000

    for avg_flow_size in avg_flow_sizes:
        flows = estimate_flows(nhost, bandwidth, load, avg_flow_size, time_s)
        print(f"平均流大小 {avg_flow_size:.2f} B, 在 {time_ms} ms 内，估计生成流数: {flows}")
