import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import os
import argparse

def plot_qp_stats_per_node(file_path, output_dir='qp_plots'):
    """
    读取 QP 统计数据并为每个节点生成一个绘图。

    Args:
        file_path (str): 输入的数据文件路径 (由 fout_conn 生成)。
        output_dir (str): 保存输出图像的目录。
    """
    # 根据您的 C++ 代码，定义列名
    column_names = ['timestamp', 'node_id', 'total_qp', 'active_qp']
    
    # 读取 CSV 文件
    try:
        df = pd.read_csv(file_path, header=None, names=column_names)
    except FileNotFoundError:
        print(f"错误：找不到文件 '{file_path}'。请确保文件名和路径正确。")
        return
    except Exception as e:
        print(f"读取或解析文件时发生错误: {e}")
        return

    # 创建一个用于保存图像的目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建输出目录: {output_dir}")

    # 按 node_id 分组，为每个节点创建一个独立的图表
    for node_id, node_df in df.groupby('node_id'):
        fig, ax = plt.subplots(figsize=(12, 7))
        plt.style.use('seaborn-v0_8-whitegrid')

        # 1. 绘制总 QP 数量曲线
        ax.plot(node_df['timestamp'], node_df['total_qp'], label='Total QPs',
                linestyle='-', color='deepskyblue', marker='.')
        
        # 2. 绘制活动 QP 数量曲线
        ax.plot(node_df['timestamp'], node_df['active_qp'], label='Active QPs',
                linestyle='--', color='darkorange', marker='.')
        
        # 格式化时间戳 (从纳秒转换为微秒)
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: f'{x/1e3:.1f} us'))

        # 设置图表标题和坐标轴标签
        ax.set_title(f'QP Statistics for Node {node_id}', fontsize=16)
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel('Number of QPs', fontsize=12)
        
        # 显示图例
        ax.legend()
        plt.tight_layout()
        
        # 定义并保存图表文件
        output_image = os.path.join(output_dir, f'qp_stats_node_{node_id}.png')
        plt.savefig(output_image, dpi=300)
        plt.close(fig)
    
    print(f"所有 QP 统计图已生成完毕，并保存在 '{output_dir}' 目录中。")


# --- 程序主入口 ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Plot QP statistics from simulation/mix/output/<ID>.')
    parser.add_argument('id', help='Simulation ID under mix/output')
    args = parser.parse_args()
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mix', 'output'))
    qp_stats_file = os.path.join(base_path, args.id, f'{args.id}_out_conn.txt')
    plot_qp_stats_per_node(file_path=qp_stats_file)
