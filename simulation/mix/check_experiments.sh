#!/bin/bash

# ==============================================================================
# 实验完成状态检查脚本
# ==============================================================================
#
# 功能:
#   - 读取 history_check.txt 文件，提取所有实验的 config_id
#   - 检查每个 config_id 对应的进程是否还在运行
#   - 生成详细的状态报告
#   - 统计运行中/已完成的实验数量
#
# 用法:
#   ./check_experiments.sh [history_file]
#
# 参数:
#   history_file - 可选，默认为 history_check.txt
#
# ==============================================================================

# -------------------- 配置参数 --------------------

# 历史文件路径（默认为当前目录下的 history_check.txt）
HISTORY_FILE="${1:-history_check.txt}"

# 输出目录路径
OUTPUT_DIR="output"

# -------------------- 颜色输出函数 --------------------

RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
BLUE="\033[0;34m"
CYAN="\033[0;36m"
NC="\033[0m" # No Color

cecho() {
    local color=$1
    shift
    echo -e "${!color}$@${NC}"
}

# -------------------- 主程序 --------------------

# 检查历史文件是否存在
if [ ! -f "$HISTORY_FILE" ]; then
    cecho "RED" "错误: 历史文件 '$HISTORY_FILE' 不存在！"
    exit 1
fi

cecho "BLUE" "=================================================="
cecho "BLUE" "         实验运行状态检查"
cecho "BLUE" "=================================================="
cecho "CYAN" "历史文件: $HISTORY_FILE"
cecho "CYAN" "输出目录: $OUTPUT_DIR"
echo ""

# 提取所有 config_id（每3行的第2个字段）
config_ids=()
line_num=0
while IFS=',' read -r date config_id rest; do
    # 跳过空行
    if [ -z "$date" ]; then
        continue
    fi

    line_num=$((line_num + 1))
    # 每3行的第1行包含配置信息
    if [ $((line_num % 3)) -eq 1 ]; then
        # 确保 config_id 不为空
        if [ -n "$config_id" ]; then
            config_ids+=("$config_id")
        fi
    fi
done < "$HISTORY_FILE"

total_experiments=${#config_ids[@]}
cecho "YELLOW" "总共需要检查 ${total_experiments} 个实验"
echo ""

# 统计变量
running=0
completed=0
missing_dir=0

# 详细结果数组
running_list=()
completed_list=()
missing_dir_list=()

cecho "CYAN" "开始检查实验状态..."
echo ""

# 检查每个实验
for config_id in "${config_ids[@]}"; do
    exp_dir="${OUTPUT_DIR}/${config_id}"

    # 检查进程是否在运行（检查是否有进程包含这个config_id）
    if pgrep -f "output/${config_id}" > /dev/null 2>&1; then
        cecho "YELLOW" "⏳ [$config_id] 运行中..."
        running=$((running + 1))
        running_list+=("$config_id")
    else
        # 进程不在运行，检查输出目录是否存在
        if [ -d "$exp_dir" ]; then
            cecho "GREEN" "✓ [$config_id] 已完成"
            completed=$((completed + 1))
            completed_list+=("$config_id")
        else
            cecho "RED" "✗ [$config_id] 未运行（目录不存在）"
            missing_dir=$((missing_dir + 1))
            missing_dir_list+=("$config_id")
        fi
    fi
done

echo ""
cecho "BLUE" "=================================================="
cecho "BLUE" "         检查完成 - 统计结果"
cecho "BLUE" "=================================================="
echo ""

cecho "CYAN" "总实验数:     $total_experiments"
cecho "GREEN" "已完成:       $completed ($(awk "BEGIN {printf \"%.1f\", $completed*100/$total_experiments}")%)"
cecho "YELLOW" "运行中:       $running ($(awk "BEGIN {printf \"%.1f\", $running*100/$total_experiments}")%)"
cecho "RED" "未运行:       $missing_dir ($(awk "BEGIN {printf \"%.1f\", $missing_dir*100/$total_experiments}")%)"

echo ""

# 如果有运行中的实验，输出详细列表
if [ $running -gt 0 ]; then
    cecho "YELLOW" "运行中的实验列表 (共 $running 个):"
    for id in "${running_list[@]}"; do
        echo "  - $id"
    done
    echo ""
fi

# 如果有未运行的实验，输出详细列表
if [ $missing_dir -gt 0 ]; then
    cecho "RED" "未运行的实验列表 (共 $missing_dir 个):"
    for id in "${missing_dir_list[@]}"; do
        echo "  - $id"
    done
    echo ""
fi

# 生成详细报告文件
REPORT_FILE="experiment_status_report_$(date +%Y%m%d_%H%M%S).txt"
{
    echo "========================================"
    echo "实验运行状态报告"
    echo "生成时间: $(date)"
    echo "========================================"
    echo ""
    echo "总实验数: $total_experiments"
    echo "已完成: $completed"
    echo "运行中: $running"
    echo "未运行: $missing_dir"
    echo ""

    if [ $completed -gt 0 ]; then
        echo "========================================"
        echo "已完成的实验 ($completed):"
        echo "========================================"
        for id in "${completed_list[@]}"; do
            echo "$id"
        done
        echo ""
    fi

    if [ $running -gt 0 ]; then
        echo "========================================"
        echo "运行中的实验 ($running):"
        echo "========================================"
        for id in "${running_list[@]}"; do
            echo "$id"
        done
        echo ""
    fi

    if [ $missing_dir -gt 0 ]; then
        echo "========================================"
        echo "未运行的实验 ($missing_dir):"
        echo "========================================"
        for id in "${missing_dir_list[@]}"; do
            echo "$id"
        done
        echo ""
    fi
} > "$REPORT_FILE"

cecho "CYAN" "详细报告已保存到: $REPORT_FILE"
echo ""

# 返回状态码
if [ $missing_dir -gt 0 ]; then
    cecho "YELLOW" "有 $missing_dir 个实验未运行！"
    exit 1
elif [ $running -gt 0 ]; then
    cecho "YELLOW" "有 $running 个实验正在运行中..."
    exit 2
else
    cecho "GREEN" "所有实验均已完成！"
    exit 0
fi
