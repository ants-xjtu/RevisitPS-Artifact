import pandas as pd
import numpy as np
import os

def transform_file(input_file, output_file, ascending=False):
    """
    转换：
    1. 读取文件
    2. 强制第一列为整数，第二列为数值（无效值丢弃）
    3. 第二列 +2
    4. 按第二列排序（默认从大到小）
    5. 保存到新文件
    """
    # 读取数据
    df = pd.read_csv(input_file, header=None, names=["col1", "col2"])

    # 第一列转为 int，第二列转为 float
    df["col1"] = pd.to_numeric(df["col1"], errors="coerce").astype("Int64")
    df["col2"] = pd.to_numeric(df["col2"], errors="coerce")
    df = df.dropna(subset=["col1", "col2"])

    # 转换类型：保证 col1 是普通 int
    df["col1"] = df["col1"].astype(int)

    # 第二列 +2
    # df["col2"] = df["col2"] - 2

    # 排序
    df = df.sort_values(by="col2", ascending=ascending).reset_index(drop=True)

    # 保存结果（第一列会保持整数格式）
    df.to_csv(output_file, index=False, header=False)
    print(f"✅ 转换完成（已按 col2 {'升序' if ascending else '降序'} 排序），结果保存到 {output_file}")

    return df


def compute_percentiles(series, percentiles=[50, 99, 99.9, 99.99], output_file=None):
    """
    计算百分位数并可选择保存到 CSV
    """
    # 确保是数值
    series = pd.to_numeric(series, errors="coerce").dropna()
    if len(series) == 0:
        raise ValueError("❌ 没有有效的数值可供计算百分位数")

    values = np.percentile(series, percentiles)
    results = {f"p{p}": v for p, v in zip(percentiles, values)}

    # 打印结果
    print("\n📊 百分位统计结果:")
    for k, v in results.items():
        print(f"  {k:<6}: {v:.6f}")

    # 保存到文件
    if output_file:
        stats_df = pd.DataFrame([results])
        stats_df.to_csv(output_file, index=False)
        print(f"💾 百分位统计结果已保存到 {output_file}")

    return results


if __name__ == "__main__":
    input_file = "AR_drop_10e-3.csv"         # 输入文件
    output_file = "AR_drop_10e-3.csv"        # 转换后输出文件
    stats_file = "result_drop10e-3_stats.csv" # 百分位数保存文件

    # 转换 & 排序
    df = transform_file(input_file, output_file, ascending=True)

    # 计算百分位数并保存
    compute_percentiles(df["col2"], output_file=stats_file)
