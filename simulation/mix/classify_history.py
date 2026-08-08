#!/usr/bin/env python3
import os
import re

# --- 配置 ---
HISTORY_FILE_PATH = './history_check.txt'
BASE_OUTPUT_DIR = './'
# --- 配置结束 ---


# --- 輔助函數 (保持不變) ---
def get_topo_info(topo_str):
    if "leaf_spine_128_100G_OS2" in topo_str: return "history_21ls", "21ls"
    elif "leaf_spine_L8_S16_100G_OS1" in topo_str: return "history_11ls", "11ls"
    elif "fat_k8_100G_OS2" in topo_str: return "history_21ft", "21ft"
    elif "fat_k8_100G_OS1" in topo_str: return "history_11ft", "11ft"
    else: return "history_unknown", "unknown"

def get_cdf_short_name(cdf_str):
    if "AliStorage" in cdf_str: return "Ali"
    elif "Meta" in cdf_str: return "Meta"
    elif "Solar" in cdf_str: return "Solar"
    elif "Alltoall" in cdf_str: return "Alltoall"
    elif "RingAllreduce" in cdf_str: return "RingAllreduce"
    match = re.match(r"([A-Za-z]+)", cdf_str)
    if match:
        return match.group(1)
    return cdf_str

def get_error_rate_code(error_rate_str):
    try:
        rate = float(error_rate_str)
        if rate == 0.0: return "0"
        elif rate == 0.001: return "3"
        elif rate == 0.0001: return "4"
        elif rate == 1e-05: return "5"
        elif rate == 1e-06: return "6"
        elif rate == 1e-07: return "7"
        elif rate == 1e-08: return "8"
        return error_rate_str.replace('.', 'p')
    except ValueError: return "err"

def main():
    print(f"开始处理文件: {HISTORY_FILE_PATH}")

    if not os.path.exists(HISTORY_FILE_PATH):
        print(f"錯誤: 找不到檔案 '{HISTORY_FILE_PATH}'。")
        return
        
    with open(HISTORY_FILE_PATH, 'r') as f:
        lines = f.readlines()

    processed_entries = 0
    skipped_entries = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        param_line = line.strip()
        if not param_line or ',' not in param_line:
            i += 1
            continue
        
        entry_end_index = i + 1
        while entry_end_index < len(lines) and ',' not in lines[entry_end_index]:
            entry_end_index += 1
        
        full_entry_lines = lines[i:entry_end_index]
        
        original_params = param_line.split(',')
        if len(original_params) < 22:
            i = entry_end_index
            continue

        try:
            # --- 1. (新) 解析所有日誌欄位 ---
            # 根據您提供的權威格式，將所有欄位讀入變數
            simulday                 = original_params[0]
            config_ID                = original_params[1]
            cc_mode                  = original_params[2]
            lb_mode                  = original_params[3]
            ar_mode                  = original_params[4]
            cwh_tx_expiry_time       = original_params[5]
            cwh_extra_reply_deadline = original_params[6]
            cwh_path_pause_time      = original_params[7]
            cwh_extra_voq_flush_time = original_params[8]
            cwh_default_voq_waiting_time = original_params[9]
            pfc                      = original_params[10]
            irn                      = original_params[11]
            has_win                  = original_params[12]
            var_win                  = original_params[13]
            window_size              = original_params[14]
            topo                     = original_params[15]
            bw                       = original_params[16]
            cdf                      = original_params[17]
            load                     = original_params[18]
            error_rate               = original_params[19]
            simul_time               = original_params[20]
            timeout_slowstart_mode   = original_params[21]
            
            # --- 2. 根據部分解析出的參數產生檔名 ---
            output_dir_name, topo_prefix = get_topo_info(topo)
            load_part = load
            cdf_part = get_cdf_short_name(cdf)
            error_part = get_error_rate_code(error_rate)
            slow_part = f"slow{timeout_slowstart_mode}" # 使用正確的 timeout 欄位
            loss_part = "lossless" if pfc == '1' else "lossy"
            try:
                win_val_kb = int(window_size) // 1000
            except ValueError:
                win_val_kb = 0
            win_part = f"w{win_val_kb}"
            
            filename = f"history_{topo_prefix}_{load_part}_{cdf_part}_{error_part}_{slow_part}_{loss_part}_{win_part}.txt"
            
            full_dir_path = os.path.join(BASE_OUTPUT_DIR, output_dir_name)
            os.makedirs(full_dir_path, exist_ok=True)
            full_file_path = os.path.join(full_dir_path, filename)
            
            # --- 3. (新) 檢查重複，決定是否寫入 ---
            should_write = True
            if os.path.exists(full_file_path):
                with open(full_file_path, 'r') as f_read:
                    # 檢查 config_ID 是否已存在於檔案內容中
                    if config_ID in f_read.read():
                        should_write = False
            
            if should_write:
                print(f"\n--- 正在处理条目 {i+1} (ID: {config_ID}) ---")
                print(f"将被分类到文件: {full_file_path}")
                # 使用 'a' (append) 模式來附加內容
                with open(full_file_path, 'a') as out_f:
                    out_f.writelines(full_entry_lines)
                processed_entries += 1
            else:
                # 如果已存在，則打印提示訊息並跳過
                print(f"--- 条目 {i+1} (ID: {config_ID}) 已存在于目标文件中，跳过。 ---")
                skipped_entries += 1

        except Exception as e:
            print(f"处理行时发生错误: {param_line} | 错误: {e}")
            
        i = entry_end_index
        
    print(f"\n分类完成！新增了 {processed_entries} 条记录，跳过了 {skipped_entries} 条重复记录。")

if __name__ == "__main__":
    main()