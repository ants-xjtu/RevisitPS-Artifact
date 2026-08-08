import argparse
import matplotlib.pyplot as plt
import numpy as np
import os
from matplotlib.ticker import PercentFormatter

# Import the project's custom plotting library
# Assuming plot.py is in lib/py/plot/plot.py relative to the script's location
import lib.py.plot.plot as plot

# --- Helper function to escape LaTeX special characters ---
def escape_latex(s):
    """Escape LaTeX special characters in a string."""
    if not isinstance(s, str):
        s = str(s)
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\^{}",
        "\\": r"\textbackslash{}",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s


# --- 固定顺序 ---
desired_order = [
    "ECMP\n(NAK+SR)",
    "RPS\n(RTO+GBN)",
    "AR\n(RTO+GBN)",
    "AR\n(Packet Trimming)",
    "AR\n(Oracle)",
    "AR\n(RTO+GBN+Slow Start)",
    "AR\n(Oracle+Slow Start)",
]

# --- 硬编码丢包率（百分比 → 小数） ---
hardcoded_drop_rates = {
    "ECMP\n(NAK+SR)": 0.0523,
    "RPS\n(RTO+GBN)": 0.2719,
    "AR\n(RTO+GBN)": 0.2977,
    "AR\n(Packet Trimming)": 0.0060,
    "AR\n(Oracle)": 0.0091,
    "AR\n(RTO+GBN+Slow Start)": 0.0060,
    "AR\n(Oracle+Slow Start)": 0.0005,
}


def draw_drop_plot(output_path):
    """
    使用硬编码的丢包率生成图表
    """
    plt.rcParams['text.usetex'] = True

    # --- 准备数据 ---
    group_labels = [escape_latex(label) for label in desired_order]
    drop_rates = [hardcoded_drop_rates[label] for label in desired_order]

    # --- Plotting with BarPlot for styling ---
    p = plot.BarPlot()
    p.fig.set_size_inches(8, 6)
    x_indices = np.arange(len(group_labels))
    bar_width = 0.6

    style = p.get_plot_args()
    p.ax.bar(x_indices, drop_rates, width=bar_width)

    # --- Customize Plot ---
    p.ax.set_ylabel("Packet Drop Rate", fontsize=20)
    p.ax.set_xticks(x_indices)
    p.ax.set_xticklabels(group_labels, rotation=45, ha='center', fontsize=15)
    p.ax.tick_params(axis='x', labelsize=15)
    p.ax.tick_params(axis='y', labelsize=15)
    p.ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=2))

    p.fig.tight_layout(rect=[0, 0.1, 0.95, 0.95])

    # --- Save ---
    plt.savefig(output_path)
    plt.close()
    print(f"✅ Total drop rate chart saved to: {output_path}")


def main():
    """
    接收 JSON 路径，但只用来决定输出 PDF 的位置和名字
    """
    parser = argparse.ArgumentParser(
        description="Generate drop rate bar chart using hardcoded values."
    )
    parser.add_argument(
        "json_path",
        type=str,
        help="Input JSON path (only used to determine output PDF filename)."
    )
    args = parser.parse_args()

    # 输出目录和名字基于 JSON 路径
    base_name = os.path.basename(args.json_path)
    output_name = os.path.splitext(base_name)[0] + ".pdf"
    output_path = os.path.join(os.path.dirname(args.json_path), output_name)

    draw_drop_plot(output_path)


if __name__ == '__main__':
    main()
