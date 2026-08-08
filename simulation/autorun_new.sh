#!/bin/bash

# ==============================================================================
# 							高級並發實驗運行與管理腳本 (全參數遍歷版)
# ==============================================================================
#
# 功能:
#   - [新] 支援對擁塞控制 (CC)、網絡拓撲 (TOPOLOGY)、網絡負載 (NETLOAD)、
#     錯誤率 (ERROR_RATE) 以及 CDF 進行全組合實驗。
#   - [新] 根據拓撲類型（fat-tree 或 leaf-spine）自動設定 win_size 參數。
#   - [新] 將每一次 python 執行的輸出重導向到一個帶有詳細參數的日誌檔案中，
#     存放在 logs/ 目錄下。
#   - 透過監控系統級的特定進程模式，實現全局並發任務數量控制，避免服務器過載。
#   - 提供彩色的、清晰的日誌輸出，方便跟蹤實驗進度。
#   - 腳本結構化，易於擴展和維護。
#
# ==============================================================================


# -------------------- 輔助函數 --------------------

# 彩色輸出函數，用於美化和區分不同類型的日誌信息
# 用法: cecho "COLOR" "Message"
# 例如: cecho "GREEN" "Success!"
cecho() {
    RED="\033[0;31m"
    GREEN="\033[0;32m"
    YELLOW="\033[0;33m"
    BLUE="\033[0;34m"
    NC="\033[0m" # No Color
    printf "${!1}${2}${NC}\n"
}


# -------------------- 全局配置 --------------------

# ⭐ 全局最大並發任務數 (整個服務器上同時運行的 run.py 進程總數)
MAX_JOBS=60

# ⭐ 【關鍵配置】需要進行全局並發控制的進程模式
#     這個模式將用於 pgrep 命令，來檢查整個服務器上匹配此模式的進程數量
PROCESS_PATTERN_TO_MONITOR="build/scratch/network-load-balance"

# ⭐ 【實驗參數配置】在這裡定義所有可變的實驗參數
# 腳本會自動對以下所有數組進行全組合測試
TOPOLOGIES=(
    # "leaf_spine_L2_S4_100G_OS1"
    # "leaf_spine_L2_S8_100G_OS1"
    # "bigswitch_H16_100G_OS1"
    "leaf_spine_L8_S16_100G_OS1"
    # "leaf_spine_128_100G_OS2"
    # "leafspine_L8_S8_100G_Asym10pct_Ratio0.5_OS2"
    # "leafspine_L8_S8_100G_Asym10pct_Ratio0.2_OS2"
    # "leafspine_L8_S8_100G_Asym20pct_Ratio0.5_OS2"
    # "leafspine_L8_S8_100G_Asym20pct_Ratio0.2_OS2"
    # "leafspine_L8_S16_100G_Asym10pct_Ratio0.5_OS1"
    # "leafspine_L8_S16_100G_Asym10pct_Ratio0.2_OS1"
    # "leafspine_L8_S16_100G_Asym20pct_Ratio0.5_OS1"
    # "leafspine_L8_S16_100G_Asym20pct_Ratio0.2_OS1"
    # "fat_k8_100G_OS2"
    "fat_k8_100G_OS1"
    # "three_layer_p4_tor4_l19_l28_s8_faill1_OS1"
    # "three_layer_p4_tor4_l19_l28_s8_faill2_OS1"
    # "three_layer_p4_tor4_l19_l28_s8_nofail_OS1"
    # "three_layer_p4_tor4_l19_l28_s8_faill12_OS1"
    # "three_layer_p4_tor4_l19_l24_s8_faill23_OS1"
    # "three_layer_p4_tor4_l19_l28_s8_failhalf_OS1"
)
NETLOADS=(
    # "50"
    "80"
    # "10"
    # "100"
)
ERROR_RATES=(
    "0.000"
    # "0.001"
    # "0.0001"
    # "0.00001"
    # "0.000001"
    # "0.0000001"
    # "0.00000001"
)
CDFS=(
    "AliStorage2019"
    # "WebSearch"
    # "DataMining"
    # "FbHdp2015"
    # "Solar2022"
    # "GoogleRPC2008"
)

# ⭐ [NEW] Congestion Control Algorithms
CCS=(
    "dcqcn"
    # "dcqcn_lane"
    # "dcqcn_dst"
    # "none"
)


# 固定實驗參數
RUNTIME="0.05"  # 模擬運行時間 (秒)
# RUNTIME="0.00000001"  # 模擬運行時間 (秒)
# RUNTIME="0.02"  # 模擬運行時間 (秒)
# RUNTIME="0.2"  # 模擬運行時間 (秒)
FLOWGEN="src"
# FLOWGEN="inter_leaf"
# FLOWGEN="dst"

# ⭐ [NEW] NIC Bandwidth (Gbps) - 应该与拓扑文件匹配
NIC_BW="100"  # 对于 *_100G_* 拓扑文件使用 100，*_400G_* 使用 400

# ⭐ [NEW] Buffer Sizes (MB) - 支持多个 buffer size 配置
BUFFER_SIZES=(
    # "16"
    "0"
    # "14"
    # "113"  # TH4: 128MB total buffer
    # "64"   # TH3: 64MB total buffer
    # "32"   # TH2: 32MB total buffer
)


# -------------------- 核心並發控制函數 --------------------

# 運行任務函數（基於系統級進程數量進行限流）
# 這個函數會一直等待，直到系統中有空閒的“槽位”，然後才在後台執行命令
# [修改]：第一個參數現在是日誌檔案路徑，其餘參數是要執行的命令
run_if_slot_free() {
    local log_file=$1
    shift # 移除第一個參數（日誌檔案），剩下的 $@ 就是要執行的命令

    # 使用 pgrep 檢查整個系統中匹配模式的進程總數
    while [ "$(pgrep -fc -- "$PROCESS_PATTERN_TO_MONITOR")" -ge "$MAX_JOBS" ]; do
        local current_system_procs=$(pgrep -fc -- "$PROCESS_PATTERN_TO_MONITOR")
        printf "\r$(cecho "YELLOW" "系統當前進程數 (${current_system_procs}) 已達上限 ${MAX_JOBS}，等待資源釋放...")"
        sleep 1
    done
    printf "%-100s\r" " "

    # 有空位後，在後台執行實際的命令，並將輸出和錯誤重導向到指定的日誌檔案
    "$@" > "$log_file" 2>&1 &
    sleep 1
}


# -------------------- 實驗組提交函數 --------------------

# 運行一組實驗
run_experiment_group() {
    local topology=$1
    local netload=$2
    local error_rate=$3
    local cdf=$4
    local cc=$5
    local pfc=$6
    local irn=$7
    local armode=$8
    local timeout_mode=$9
    local win_size=${10}
    local rto_high=${11}
    local rto_low=${12}
    local buffer_size=${13}  # <--- 新增：buffer size 参数
    shift 13  # <--- 修改：移除了13个参数
    local lbs=("$@")

    cecho "GREEN" "   -> 提交實驗組: CC=$cc PFC=$pfc IRN=$irn ARMODE=$armode TIMEOUT=${timeout_mode} WIN_SIZE=${win_size} RTO_HIGH=${rto_high} RTO_LOW=${rto_low} BUFFER=${buffer_size}MB LBs=${lbs[*]}"
    for lb in "${lbs[@]}"; do
        local log_filename="logs/topo=${topology}_load=${netload}_err=${error_rate}_cdf=${cdf}_cc=${cc}_pfc=${pfc}_irn=${irn}_armode=${armode}_timeout=${timeout_mode}_win=${win_size}_rtoh=${rto_high}_rtol=${rto_low}_buf=${buffer_size}_lb=${lb}.log"

        run_if_slot_free "$log_filename" python3 run.py \
            --cc "$cc" --lb "$lb" --pfc "$pfc" --irn "$irn" --armode "$armode" \
            --simul_time "$RUNTIME" --netload "$netload" --topo "$topology" \
            --cdf "$cdf" --error_rate "$error_rate" --flowgen_mode "$FLOWGEN" \
            --timeout_slowstart_mode "$timeout_mode" \
            --windowSize "$win_size" \
            --rto_high "$rto_high" --rto_low "$rto_low" \
            --buffer "$buffer_size" \
            --bw "$NIC_BW"
    done
}


# ==============================================================================
# 								腳本主執行邏輯
# ==============================================================================

cecho "BLUE" "=================================================="
cecho "BLUE" "        開始提交所有實驗任務組合"
cecho "BLUE" "=================================================="
cecho "YELLOW" "全局並發上限 (MAX_JOBS): ${MAX_JOBS}"
cecho "YELLOW" "監控進程模式: '${PROCESS_PATTERN_TO_MONITOR}'"
cecho "YELLOW" "NIC 帶寬: ${NIC_BW}Gbps"

# [新功能] 建立日誌目錄
cecho "YELLOW" "檢查並建立日誌目錄: logs/"
mkdir -p logs
cecho "YELLOW" "----------------------------------"

# <--- 核心修改：使用六层嵌套循環遍歷所有參數組合（增加 buffer_size 循環）
for topo in "${TOPOLOGIES[@]}"; do

    # ==================== [新增邏輯] 根據拓撲自動設定窗口大小 ====================
    # 根據拓撲名稱判斷並設定默認的 win_size
    # 如果需要在 run_experiment_group 中使用固定的 0，則直接傳入 0 即可
    default_win_size=104000
    if [[ "$topo" == *"fat"* ]]; then
        default_win_size=156000
    elif [[ "$topo" == *"leaf_spine"* ]] || [[ "$topo" == *"leafspine"* ]]; then
        default_win_size=104000
    elif [[ "$topo" == *"three_layer"* ]]; then
        default_win_size=156000
    fi
    cecho "YELLOW" "檢測到拓撲 '${topo}'，設定默認 win_size 為 ${default_win_size}"
    # =============================================================================

    for load in "${NETLOADS[@]}"; do
        for err_rate in "${ERROR_RATES[@]}"; do
            for cdf in "${CDFS[@]}"; do
                for cc in "${CCS[@]}"; do
                    for buffer_size in "${BUFFER_SIZES[@]}"; do  # <--- 新增：buffer size 循環

                        cecho "BLUE" "=====>> 處理組合: TOPO=[${topo}], LOAD=[${load}], ERR=[${err_rate}], CDF=[${cdf}], CC=[${cc}], BUFFER=[${buffer_size}MB] <<====="

                        # -------------------- 在此組合下需要執行的實驗 --------------------
                        # 說明：
                        # run_experiment_group 參數順序現在是:
                        # 1:topo, 2:load, 3:err_rate, 4:cdf, 5:cc, 6:pfc, 7:irn, 8:armode,
                        # 9:timeout, 10:winsize, 11:rto_high, 12:rto_low, 13:buffer_size, 後面跟著所有 lb 模式

                        # big switch test
                        # #Lossy
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 noar 0 "$default_win_size" 320 100 "$buffer_size"  fecmp letflow conga conweave
                        run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 0 "$default_win_size" 320 100  "$buffer_size" adaptive
                        run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 1 "$default_win_size" 320 100  "$buffer_size" adaptive
                        run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 2 "$default_win_size" 320 100  "$buffer_size" adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   2 "$default_win_size" 320 100 "$buffer_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   8 "$default_win_size" 320 100 "$buffer_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   32 "$default_win_size" 320 100 "$buffer_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   128 "$default_win_size" 320 100 "$buffer_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size" 320 100 "$buffer_size" rps drill adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   0 "$default_win_size" 320 100 "$buffer_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   1 "$default_win_size" 320 100 "$buffer_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 noar 0 "$default_win_size" "$buffer_size" 320 100  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   2 "$default_win_size"  "$buffer_size" 320 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"  "$buffer_size" 320 100 adaptive

                        # # #Lossless
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 noar 0 "$default_win_size" 4000 4000 "$buffer_size"  fecmp
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 noar 0 "$default_win_size" 4000 4000 "$buffer_size"  letflow conga conweave
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 ar   0 "$default_win_size" 4000 4000 "$buffer_size"  rps drill adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 noar 0 "$default_win_size" 3000 3000 "$buffer_size" fecmp letflow conga conweave
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 ar   0 "$default_win_size" 3000 3000 "$buffer_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 ar   2 "$default_win_size"   3000 3000 "$buffer_size" adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 ar   1 "$default_win_size"   3000 3000 "$buffer_size" adaptive
                        
                        # --- 實驗場景 1: DCP RDMA (pfc=0, irn=2) ---
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 noar   2 0   320 100 adaptive 
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   2 "$default_win_size"   320 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   2 0   320 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   2 200000   320 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   2 150000   320 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   2 250000   320 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   2 300000   320 100 adaptive
                        #--- 實驗場景 1: Ideal-Packet-Trimming RDMA (pfc=0, irn=2) ---
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar 0 "$default_win_size"  3000 3000 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar 1 "$default_win_size"  3000 3000 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 0 "$default_win_size"  3000 3000 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 1 "$default_win_size"  3000 3000 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 0 "$default_win_size"  3000 3000 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 1 "$default_win_size"  3000 3000 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 2 "$default_win_size"  3000 3000 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 2 "$default_win_size"  320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 1 "$default_win_size"  320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar 0 "$default_win_size"  320 100 weightadaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 noar 2 "$default_win_size"  320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 noar 1 "$default_win_size"  320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 noar 0 "$default_win_size"  320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 noar 2 "$default_win_size"  3000 3000 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 noar 1 "$default_win_size"  3000 3000 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 noar 0 "$default_win_size"  3000 3000 weightadaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 4 noar 2 "$default_win_size"  320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 4 noar 1 "$default_win_size"  320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 4 noar 0 "$default_win_size"  320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 4 noar 2 "$default_win_size"  3000 3000 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 4 noar 1 "$default_win_size"  3000 3000 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 4 noar 0 "$default_win_size"  3000 3000 weightadaptive
                        # --- 實驗場景 1: IRN RDMA (pfc=0, irn=1) ---
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   500 500 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   400 400 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   300 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   300 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   2 "$default_win_size"   320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   320 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   500 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   400 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   3000 3000 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   320 320 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   2 "$default_win_size"   320 320 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 200 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   150 150 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   100 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   90 90 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   80 80 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   70 70 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   60 60 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   50 50 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   40 40 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   30 30 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   20 20 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   10 10 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 200 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 90 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 80 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 70 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 60 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 50 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 40 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 30 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 20 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   200 10 adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   4 "$default_win_size"   500 500 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   4 "$default_win_size"   400 400 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   4 "$default_win_size"   300 300 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   4 "$default_win_size"   200 200 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   4 "$default_win_size"   100 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   4 "$default_win_size"   90 90 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   80 80 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   70 70 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   60 60 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   50 50 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   40 40 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   30 30 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   20 20 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   10 10 adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 noar 0 0   fecmp letflow conga conweave
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   0 0   rps drill adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 noar 0 "$default_win_size"   fecmp
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 noar 0 "$default_win_size"   letflow conga conweave
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   380 100 weightadaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 "$default_win_size"   380 100 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   0 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   2 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   4 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   8 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   16 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   32 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 noar 2 0   fecmp letflow conga conweave
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   2 "$default_win_size"   rps drill adaptive
                        
                        # --- 實驗場景 2: Lossless RDMA (pfc=1, irn=0) ---
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 noar 0 0                   fecmp letflow conga conweave
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 ar   0 0                   rps drill adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 noar 0 "$default_win_size" fecmp
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 noar 0 "$default_win_size" letflow conga conweave
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 ar   0 "$default_win_size" rps adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 noar 0 512000              fecmp letflow conga conweave
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 1 0 ar   0 512000              rps drill adaptive

                        # --- 實驗場景 1: E-DCP RDMA (pfc=0, irn=2) --- 156000
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar  0 0 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar  0 0 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar  0 0                   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar  0 0                   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar  0 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar  0 "$default_win_size"   adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   1 0                   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   1 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   1 "$default_win_size"   adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   2 0                   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   2 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   2 "$default_win_size"   adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   4 0                   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   4 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   4 "$default_win_size"   adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   8 0                   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   8 "$default_win_size"   adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   8 "$default_win_size"   adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   16 0                  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   16 "$default_win_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   16 "$default_win_size"  adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   32 0                  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   32 "$default_win_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   32 "$default_win_size"  adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   64 0                  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   64 "$default_win_size"  adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   64 "$default_win_size"  adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   128 0                 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   128 "$default_win_size" adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   128 "$default_win_size" adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   256 0                 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   256 "$default_win_size" adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   256 "$default_win_size" adaptive

                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 1 ar   512 0                 adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 2 ar   512 "$default_win_size" adaptive
                        # run_experiment_group "$topo" "$load" "$err_rate" "$cdf" "$cc" 0 3 ar   512 "$default_win_size" adaptive

                    done  # <--- 新增：buffer_size 循環結束
                done
            done
        done
    done
done

cecho "GREEN" "=================================================="
cecho "GREEN" "所有任務組合均已提交到後台。"
cecho "GREEN" "腳本將在此處等待所有由它啟動的後台任務全部完成..."
cecho "GREEN" "=================================================="

# 關鍵步驟: 等待所有由*本腳本*啟動的後台任務完成。
wait

cecho "BLUE" "=================================================="
cecho "BLUE" "        所有後台任務執行完畢！"
cecho "BLUE" "=================================================="
