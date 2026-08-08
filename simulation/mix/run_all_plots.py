#!/usr/bin/env python3

import os
import glob
import subprocess
import argparse
from multiprocessing import Pool, cpu_count
from collections import defaultdict

def run_command_task(args):
    """通用任務執行函數"""
    task_num, total_tasks, command, group_name = args
    print(f"--- [{task_num}/{total_tasks}] 開始執行任務組: {group_name} ---")
    try:
        result = subprocess.run(
            command, shell=True, check=True, capture_output=True, text=True, encoding='utf-8'
        )
        print(f"--- [{task_num}/{total_tasks}] 成功完成任務組: {group_name} ---")
        return None
    except subprocess.CalledProcessError as e:
        error_message = (
            f"\n!!! [{task_num}/{total_tasks}] 處理 '{group_name}' 時發生錯誤 !!!\n"
            f"--- 命令 ---\n{command}\n"
            f"--- 腳本輸出 ---\n{e.stdout}\n"
            f"--- 腳本錯誤 ---\n{e.stderr}\n"
        )
        return error_message

def main():
    parser = argparse.ArgumentParser(description='自動化批次執行多種FCT/JCT繪圖腳本')
    
    parser.add_argument(
        '--plotter', 
        type=str, 
        default='fct', 
        choices=['fct', 'jct', 'recovery', 'error'],
        help="選擇要執行的繪圖腳本: 'fct', 'jct', 'recovery', 'error'。預設: fct"
    )
    # --- 过滤参数 ---
    parser.add_argument('--topo', nargs='+', help='要繪製的拓撲名稱')
    parser.add_argument('--load', nargs='+', help="要篩選的負載值(FCT模式)或Message Size(JCT模式)")
    parser.add_argument('--workload', nargs='+', help='要繪製的 workload 類型')
    parser.add_argument('--flowcontrol', nargs='+', choices=['lossless', 'lossy'], help="流控類型")
    parser.add_argument('--error', nargs='+', help="錯誤率代碼 (在 'error' 模式下會被忽略)")
    parser.add_argument('--window', nargs='+', help="窗口大小(KB)")
    parser.add_argument('--timeout', nargs='+', help="超時模式")
    parser.add_argument('--lb', type=str, help="當 --plotter=error 時，指定要分析的load balancing模式")
    parser.add_argument('--parallel', type=int, default=cpu_count(), help=f'並行處理的任務數量')
    args = parser.parse_args()

    if args.plotter == 'jct':
        allowed_workloads = {'Alltoall', 'RingAllreduce'}
        if not args.workload or not set(args.workload).issubset(allowed_workloads):
            print("錯誤: 使用 '--plotter jct' 時，必須透過 '--workload' 參數指定 'Alltoall' 或 'RingAllreduce'。")
            return
            
    # --- 路径计算 ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.join(script_dir, '..')
    analysis_dir = os.path.join(base_dir, 'analysis')
    mix_dir = os.path.join(base_dir, 'mix')
    
    plotter_scripts = {
        'fct': os.path.join(analysis_dir, 'plot_fct_echance_for_samesize.py'),
        'jct': os.path.join(analysis_dir, 'plot_jct_rank.py'),
        'recovery': os.path.join(analysis_dir, 'plot_recovery_comparison.py'),
        'error': os.path.join(analysis_dir, 'plot_error_comparison.py')
    }
    plotter_script = plotter_scripts.get(args.plotter)
    
    if not os.path.isdir(mix_dir): print(f"錯誤: 找不到 'mix' 資料夾 ('{mix_dir}')。"); return
    if not plotter_script or not os.path.exists(plotter_script): print(f"錯誤: 找不到繪圖腳本 '{plotter_script}'。"); return
    
    # --- 文件過濾 ---
    search_pattern = os.path.join(mix_dir, 'history_*', '*.txt')
    history_files = sorted(glob.glob(search_pattern))
    if not history_files: print(f"在 '{search_pattern}' 中沒有找到任何 history 檔案。"); return

    print("正在根據條件過濾文件...")
    # ... (此處省略與之前版本相同的過濾邏輯，它應該是完整的)
    filtered_files = [] 
    for file_path in history_files: 
        basename = os.path.basename(file_path) 
        basename_no_ext, _ = os.path.splitext(basename) 
        parts = basename_no_ext.split('_') 
        
        topo_match = not args.topo or any(t in file_path for t in args.topo) 
        load_match = not args.load or (len(parts) > 2 and parts[2] in args.load) 
        workload_match = not args.workload or any(w in basename for w in args.workload) 
        flowcontrol_match = not args.flowcontrol or any(fc in basename for fc in args.flowcontrol) 
        error_match = (args.plotter == 'error') or (not args.error or (len(parts) > 4 and parts[4] in args.error)) 
        timeout_match = not args.timeout or (len(parts) > 5 and any(f"slow{t}" == parts[5] for t in args.timeout)) 
        window_match = not args.window or (len(parts) > 7 and any(f"w{w}" == parts[7] for w in args.window)) 

        if all([topo_match, load_match, workload_match, flowcontrol_match, error_match, timeout_match, window_match]): 
            filtered_files.append(file_path)

    if not filtered_files: print("根據您的過濾條件，沒有找到任何匹配的檔案。"); return

    # --- 任務準備與執行 ---
    tasks = []
    
    if args.plotter in ['fct', 'recovery']:
        # ... (邏輯不變)
        print(f"\n共找到 {len(filtered_files)} 個匹配的檔案，準備開始繪圖...") 
        for i, file_path in enumerate(filtered_files): 
            basename = os.path.basename(file_path) 
            command = f"python3 \"{plotter_script}\" \"{file_path}\"" 
            tasks.append((i + 1, len(filtered_files), command, basename))

    elif args.plotter == 'jct':
        print(f"\n進入 'jct' 聚合模式...")
        file_groups = defaultdict(list)
        
        for file_path in filtered_files:
            basename_no_ext, _ = os.path.splitext(os.path.basename(file_path))
            parts = basename_no_ext.split('_')
            if len(parts) > 7:
                # 修正點: 分組的key應排除 load(message size)，即 parts[2]
                group_key = (parts[1], parts[3], parts[4], parts[5], parts[6], parts[7])
                file_groups[group_key].append(file_path)

        print(f"找到了 {len(file_groups)} 個配置組進行聚合繪圖。")
        
        task_num = 0
        for key, group_files in file_groups.items():
            task_num += 1
            quoted_files = [f"\"{f}\"" for f in group_files]
            command = f"python3 \"{plotter_script}\" {' '.join(quoted_files)}"
            group_name = "JCT_GROUP_" + "_".join(key)
            tasks.append((task_num, len(file_groups), command, group_name))

    elif args.plotter == 'error':
        # ... (邏輯不變)
        if not args.lb: print("錯誤: 使用 --plotter=error 模式時，必須透過 --lb <mode> 指定一個負載均衡模式。"); return 
        print(f"\n進入 'error' 比較模式，將為 LB={args.lb} 進行文件分組...") 
        file_groups = defaultdict(list) 
        
        for file_path in filtered_files: 
            basename_no_ext, _ = os.path.splitext(os.path.basename(file_path)) 
            parts = basename_no_ext.split('_') 
            if len(parts) > 5: 
                group_key = (parts[1], parts[2], parts[3], parts[5], parts[6], parts[7]) 
                file_groups[group_key].append(file_path) 
        
        print(f"找到了 {len(file_groups)} 個配置組進行錯誤率對比。")
        
        task_num = 0
        for key, group_files in file_groups.items():
            if len(group_files) > 1:
                task_num += 1
                quoted_files = [f"\"{f}\"" for f in group_files]
                command = f"python3 \"{plotter_script}\" --lb_mode {args.lb} {' '.join(quoted_files)}"
                group_name = "_".join(key)
                tasks.append((task_num, len(file_groups), command, group_name))

    if not tasks: print("\n沒有生成任何有效的繪圖任務。"); return
    # ... (後續執行邏輯不變)
    print(f"\n共生成 {len(tasks)} 個繪圖任務，準備執行...") 
    num_processes = min(args.parallel, len(tasks)) 
    if num_processes <= 0: num_processes = 1 
    if num_processes > 1: 
        print(f"將使用 {num_processes} 個進程並行處理...") 
        with Pool(processes=num_processes) as pool: 
            results = list(pool.imap_unordered(run_command_task, tasks)) 
    else: 
        print("將循序處理...") 
        results = [run_command_task(task) for task in tasks] 
    errors = [res for res in results if res is not None] 
    if errors: 
        print("\n" + "="*50) 
        print(f"!!! {len(errors)} 個任務執行時發生錯誤 !!!") 
        for error_message in errors: print(error_message) 
    print("\n所有繪圖任務已完成！")

if __name__ == "__main__":
    main()