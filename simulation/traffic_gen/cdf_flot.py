import os
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import lib.py.plot.plot as plot  # 使用你原来的 CDFPlot

def human_readable_formatter(x, pos):
    """将 KB 单位转换为 B, KB, MB, GB 可读格式"""
    if x <= 0:
        return '0'
    if x < 1:
        return f'{int(x*1024)}B'
    elif x < 1024:
        return f'{int(x)}KB'
    elif x < 1024**2:
        mb_val = x / 1024
        return f'{mb_val:.1f}MB' if mb_val != int(mb_val) else f'{int(mb_val)}MB'
    else:
        gb_val = x / 1024**2
        return f'{gb_val:.1f}GB' if gb_val != int(gb_val) else f'{int(gb_val)}GB'

def main():
    traffic_dir = os.path.dirname(os.path.abspath(__file__))
    files = {
        "MetaHadoop": os.path.join(traffic_dir, "FbHdp2015.txt"),
        "SolarRPC": os.path.join(traffic_dir, "Solar2022.txt"),
        "AliStorage": os.path.join(traffic_dir, "AliStorage2019.txt"),
        "WebSearch": os.path.join(traffic_dir, "WebSearch.txt"),
    }

    # 初始化 CDFPlot
    p_cdf = plot.CDFPlot()

    for name, filepath in files.items():
        print(f"\n--- 正在处理 {name} ---")
        if not os.path.exists(filepath):
            print(f"⚠️ 文件不存在，跳过: {filepath}")
            continue

        x_values_bytes = []
        y_values = []

        with open(filepath, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        x_values_bytes.append(float(parts[0]))
                        y_values.append(float(parts[1]))
                    except ValueError:
                        print(f"⚠️ 无法解析行: {line.strip()}")

        if not x_values_bytes:
            print(f"⚠️ 文件为空或格式不正确，跳过: {filepath}")
            continue

        # 转换为 KB，0 替换为极小值适应 log
        x_values_kb = [x/1024 if x>0 else 1e-3 for x in x_values_bytes]

        # 归一化 y
        y_max = max(y_values) if y_values else 1.0
        y_values_normalized = [y/y_max for y in y_values]

        print(f"前5个 x 值(KB): {x_values_kb[:5]}")
        print(f"前5个归一化 y 值: {y_values_normalized[:5]}")

        # 绘图，使用 CDFPlot，不改变颜色/线型
        p_cdf.plot(x_values_kb, cdf=y_values_normalized, label=name)

    # 设置 log 横坐标
    p_cdf.ax.set_xscale('log')
    p_cdf.ax.set_xlabel("Flow Size", fontsize=14)
    p_cdf.ax.set_ylabel("CDF", fontsize=14)
    p_cdf.ax.set_title("CDF of Flow Sizes for Different Workloads", fontsize=16)
    p_cdf.ax.set_ylim(0, 1.05)

    # 设置刻度格式
    p_cdf.ax.xaxis.set_major_locator(ticker.LogLocator(base=10.0, numticks=12))
    p_cdf.ax.xaxis.set_major_formatter(ticker.FuncFormatter(human_readable_formatter))
    p_cdf.ax.tick_params(axis='both', which='major', labelsize=12)

    # 显示图例和网格
    p_cdf.ax.legend(loc='upper left', fontsize=12)
    p_cdf.ax.grid(True, which='both', ls='--', lw=0.5)

    # 保存图表
    output_dir = traffic_dir
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "workloads_cdf_log_with_CDFPlot.pdf")
    plt.savefig(output_file, bbox_inches='tight')
    plt.close()

    print(f"\n🎉 CDF 图表已保存至: {output_file}")

if __name__ == "__main__":
    main()
