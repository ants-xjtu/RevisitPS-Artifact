import pandas as pd
import numpy as np
import os
import glob
from concurrent.futures import ProcessPoolExecutor, as_completed


def _process_single_file(file_path):
    """处理单个 CSV 文件，返回 (df_result, error_msg)"""
    try:
        df = pd.read_csv(file_path)

        if not {"size", "start_time", "end_time"}.issubset(df.columns):
            return None, f"{os.path.basename(file_path)} 缺少 size/start_time/end_time 列，已跳过"

        df = df.sort_values(by="start_time").reset_index(drop=True)

        start_times = df["start_time"].values
        end_times = df["end_time"].values
        sizes = df["size"].values

        # 向量化计算 FCT
        prev_end = np.roll(end_times, 1)
        prev_end[0] = -np.inf  # 第一行没有前一个结束时间

        # 当 start < prev_end 时，fct = end - prev_end；否则 fct = end - start
        fct = np.where(start_times < prev_end, end_times - prev_end, end_times - start_times)

        # 过滤 fct > 0 的记录
        mask = fct > 0
        df_result = pd.DataFrame({
            "size": sizes[mask],
            "fct": fct[mask]
        })

        return df_result, None

    except Exception as e:
        return None, f"读取 {os.path.basename(file_path)} 失败: {e}"


def process_and_merge(input_dir, output_file="merged.csv", max_workers=None):
    """
    处理并合并目录下的所有 CSV 文件

    Args:
        input_dir: 输入目录路径
        output_file: 输出文件路径
        max_workers: 并行处理的最大进程数，None 表示使用 CPU 核心数
    """
    files = glob.glob(os.path.join(input_dir, "*.csv"))
    if not files:
        print(f"[WARN] 在目录 {input_dir} 下没有找到 CSV 文件")
        return

    all_data = []

    # 使用多进程并行处理文件
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_single_file, f): f for f in files}

        for future in as_completed(futures):
            df_result, error_msg = future.result()
            if error_msg:
                print(error_msg)
            elif df_result is not None and not df_result.empty:
                all_data.append(df_result)

    if all_data:
        merged = pd.concat(all_data, ignore_index=True)
        merged.to_csv(output_file, index=False)
        print(f"[OK] 已生成合并文件: {output_file}")
    else:
        print("[WARN] 没有生成任何数据")
