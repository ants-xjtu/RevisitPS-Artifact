import pandas as pd

def load_flow_data(filepath):
    """
    加载流量数据并预处理
    """
    df = pd.read_csv(filepath, sep=r"\s+", header=None,
                     names=["src", "dst", "proto", "size", "start_time"])
    df = df.dropna(subset=["start_time", "dst", "size"])
    df = df[df["start_time"].apply(lambda x: isinstance(x, (int, float)))]
    df["start_time_ms"] = (df["start_time"] - 2.0) * 1000
    df = df[df["start_time_ms"] >= 0]
    df["size"] = pd.to_numeric(df["size"], errors='coerce')
    df = df.dropna(subset=["size"])
    df["dst"] = pd.to_numeric(df["dst"], errors='coerce')
    df = df.dropna(subset=["dst"])
    df["dst"] = df["dst"].astype(int)
    return df

def calculate_large_flow_ratio(df, threshold_bytes=100*1024):
    """
    返回每个dst的大流占比 = 大流总字节 / 总字节
    """
    ratios = {}
    for dst, group in df.groupby("dst"):
        total_bytes = group["size"].sum()
        large_bytes = group[group["size"] >= threshold_bytes]["size"].sum()
        ratio = large_bytes / total_bytes if total_bytes > 0 else 0
        ratios[dst] = ratio
    return ratios

def print_large_flow_ratios(ratios, threshold_bytes, title_suffix=""):
    """
    打印每个dst的大流占比
    """
    print(f"\n每个dst的大流占比（阈值 = {threshold_bytes} 字节 ≈ {threshold_bytes/1024:.1f}KB）{title_suffix}")
    print("dst\t大流占比")
    for dst, ratio in sorted(ratios.items()):
        print(f"{dst}\t{ratio:.4%}")

def summarize_ratios(ratios, threshold_bytes, title_suffix=""):
    """
    输出最大值、平均值、倒数第二大的大流占比
    """
    if not ratios:
        print("没有有效数据可统计。")
        return

    sorted_ratios = sorted(ratios.items(), key=lambda x: x[1], reverse=True)
    values = [r for _, r in sorted_ratios]
    avg = sum(values) / len(values)
    max_val = values[0]
    second_max = values[1] if len(values) > 1 else None

    print(f"\n统计结果（大流阈值 = {threshold_bytes} 字节 ≈ {threshold_bytes / 1024:.1f}KB）{title_suffix}")
    print(f"最大大流占比: {max_val:.4%} (dst={sorted_ratios[0][0]})")
    if second_max is not None:
        print(f"倒数第二大占比: {second_max:.4%} (dst={sorted_ratios[1][0]})")
    else:
        print("只有一个dst，无法计算倒数第二大值。")
    print(f"平均大流占比: {avg:.4%}")

def main():
    import sys
    if len(sys.argv) < 2:
        print("用法: python script.py <数据文件路径> [阈值KB]")
        return

    filepath = sys.argv[1]
    threshold_kb = float(sys.argv[2]) if len(sys.argv) > 2 else 100
    threshold_bytes = threshold_kb * 1024

    df_all = load_flow_data(filepath)
    df_after_40ms = df_all[df_all["start_time_ms"] > 45]

    # 全量数据
    ratios_all = calculate_large_flow_ratio(df_all, threshold_bytes)
    print_large_flow_ratios(ratios_all, threshold_bytes, title_suffix="（全体数据）")
    summarize_ratios(ratios_all, threshold_bytes, title_suffix="（全体数据）")

    # 40ms之后
    ratios_40ms = calculate_large_flow_ratio(df_after_40ms, threshold_bytes)
    print_large_flow_ratios(ratios_40ms, threshold_bytes, title_suffix="（仅限 start_time > 40ms）")
    summarize_ratios(ratios_40ms, threshold_bytes, title_suffix="（仅限 start_time > 40ms）")

if __name__ == "__main__":
    main()
