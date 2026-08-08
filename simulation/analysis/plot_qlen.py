import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import os
import argparse
import seaborn as sns

def plot_queues(df, plot_type, mode, kmax_val=None, kmin_val=None, output_dir=None):
    """
    通用绘图功能，可以按“每端口”或“每节点”模式为 Ingress 或 Egress 队列绘图。
    Y轴使用对数尺度。
    对于 Egress 图，可以额外绘制 Kmax 和 Kmin 水平参考线。
    """
    # --- 1. 参数校验和目录设置 ---
    if plot_type not in ['ingress', 'egress']:
        print(f"错误: 无效的 plot_type '{plot_type}'。请选择 'ingress' 或 'egress'。")
        return
    if mode not in ['per_port', 'per_node']:
        print(f"错误: 无效的 mode '{mode}'。请选择 'per_port' 或 'per_node'。")
        return

    if output_dir is None:
        output_dir = f'{plot_type}_plots_{mode}_log'
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建目录: {output_dir}")

    plt.style.use('seaborn-v0_8-whitegrid')

    # --- 2. 根据选择的模式进行分组和绘图 ---
    if mode == 'per_port':
        group_keys = ['node_id', 'port_id']
        for (node_id, port_id), group_df in df.groupby(group_keys):
            fig, ax = plt.subplots(figsize=(12, 7))
            
            if plot_type == 'ingress':
                ax.plot(group_df['timestamp'], group_df['ingress_qlen'] + 1, label='Ingress Queue Length',
                        marker='o', linestyle='-', markersize=4, color='royalblue')
                ax.plot(group_df['timestamp'], group_df['dynamic_threshold'] + 1, label='Dynamic Threshold',
                        linestyle='--', color='crimson')
                ax.set_title(f'Ingress Queue vs. Threshold for Node {node_id}, Port {port_id}', fontsize=16)
            else: # egress
                ax.plot(group_df['timestamp'], group_df['egress_qlen'] + 1, label='Egress Queue Length',
                        marker='o', linestyle='-', markersize=4, color='darkgreen')
                ax.plot(group_df['timestamp'], group_df['egress_threshold'] + 1, label='Egress Threshold (16x Ingress)',
                        linestyle='--', color='darkorange')
                ax.set_title(f'Egress Queue vs. Threshold for Node {node_id}, Port {port_id}', fontsize=16)

                # --- 新增：为 Egress 图绘制 Kmax 和 Kmin 参考线 ---
                if kmax_val is not None:
                    ax.axhline(y=kmax_val + 1, color='purple', linestyle=':', linewidth=2, label=f'Kmax ({kmax_val/1e3:.0f} KB)')
                if kmin_val is not None:
                    ax.axhline(y=kmin_val + 1, color='sienna', linestyle=':', linewidth=2, label=f'Kmin ({kmin_val/1e3:.0f} KB)')
            
            ax.set_yscale('log')
            ax.set_ylabel('Bytes + 1 (log scale)', fontsize=12)
            ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: f'{x/1e3:.1f} us'))
            ax.set_xlabel('Time', fontsize=12)
            ax.legend()
            plt.tight_layout()
            
            output_image = os.path.join(output_dir, f'{plot_type}_node_{node_id}_port_{port_id}.png')
            plt.savefig(output_image, dpi=300)
            plt.close(fig)

    elif mode == 'per_node':
        group_keys = ['node_id']
        for node_id, node_df in df.groupby(group_keys):
            fig, ax = plt.subplots(figsize=(14, 8))
            
            palette = sns.color_palette("husl", n_colors=node_df['port_id'].nunique())
            
            for i, (port_id, port_df) in enumerate(node_df.groupby('port_id')):
                color = palette[i]
                if plot_type == 'ingress':
                    ax.plot(port_df['timestamp'], port_df['ingress_qlen'] + 1, 
                            label=f'Port {port_id} Ingress Queue', marker='o', linestyle='-', markersize=3, color=color)
                    ax.plot(port_df['timestamp'], port_df['dynamic_threshold'] + 1, 
                            label=f'Port {port_id} Threshold', linestyle='--', color=color)
                else: # egress
                    ax.plot(port_df['timestamp'], port_df['egress_qlen'] + 1, 
                            label=f'Port {port_id} Egress Queue', marker='o', linestyle='-', markersize=3, color=color)
                    ax.plot(port_df['timestamp'], port_df['egress_threshold'] + 1, 
                            label=f'Port {port_id} Egress Threshold', linestyle='--', color=color)

            if plot_type == 'ingress':
                ax.set_title(f'Ingress Queues & Thresholds for Node {node_id}', fontsize=16)
            else: # egress
                ax.set_title(f'Egress Queues & Thresholds for Node {node_id}', fontsize=16)
                # --- 新增：为 Egress 图绘制 Kmax 和 Kmin 参考线 ---
                if kmax_val is not None:
                    ax.axhline(y=kmax_val + 1, color='purple', linestyle=':', linewidth=2, label=f'Kmax ({kmax_val/1e3:.0f} KB)')
                if kmin_val is not None:
                    ax.axhline(y=kmin_val + 1, color='sienna', linestyle=':', linewidth=2, label=f'Kmin ({kmin_val/1e3:.0f} KB)')

            ax.set_yscale('log')
            ax.set_ylabel('Bytes + 1 (log scale)', fontsize=12)
            ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: f'{x/1e3:.1f} us'))
            ax.set_xlabel('Time', fontsize=12)
            ax.legend(title='Legend', bbox_to_anchor=(1.02, 1), loc='upper left') # 图例标题改为通用
            plt.tight_layout(rect=[0, 0, 0.9, 1])
            
            output_image = os.path.join(output_dir, f'{plot_type}_node_{node_id}.png')
            plt.savefig(output_image, dpi=300)
            plt.close(fig)

    print(f"'{plot_type}' 队列图已在 '{mode}' 模式下全部生成完毕，保存在 '{output_dir}' 目录中。")


# --- 程序主入口 ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Plot qlen trace from simulation/mix/output/<ID>.')
    parser.add_argument('id', help='Simulation ID under mix/output')
    args = parser.parse_args()
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mix', 'output'))
    qlen_file = os.path.join(base_path, args.id, f'{args.id}_out_qlen.txt')

    column_names = [
        'timestamp', 'node_id', 'port_id', 'ingress_qlen', 
        'dynamic_threshold', 'egress_qlen'
    ]
    
    try:
        df = pd.read_csv(qlen_file, header=None, names=column_names)
        print(f"成功读取数据文件: {qlen_file}")
    except FileNotFoundError:
        print(f"错误：找不到文件 '{qlen_file}'。请确保文件名和路径正确。")
        exit()
    except Exception as e:
        print(f"读取或解析文件时发生错误: {e}")
        exit()

    df['egress_threshold'] = 16 * df['dynamic_threshold']
    print("已成功计算并添加 'egress_threshold' 列。")

    KMAX = 400 * 1000
    KMIN = 100 * 1000
    PLOT_MODE = 'per_node'

    plot_queues(df, plot_type='ingress', mode=PLOT_MODE)
    plot_queues(df, plot_type='egress', mode=PLOT_MODE, kmax_val=KMAX, kmin_val=KMIN)
