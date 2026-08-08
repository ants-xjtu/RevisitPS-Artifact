#!/bin/bash

# --- 配置 ---
# 包含目录ID的日志文件名。请根据你的实际文件名修改。
LOG_FILE="history_cleanup.txt"

# 存放这些ID目录的基础路径。
# 已根据你提供的信息更新。
# 重要：运行前请务必确认此路径是正确的！
BASE_PATH="${BASE_PATH:-$(cd "$(dirname "$0")" && pwd)/output}"

# --- 主脚本 ---

# 检查日志文件是否存在
if [ ! -f "$LOG_FILE" ]; then
    echo "错误：在 '$LOG_FILE' 未找到日志文件"
    exit 1
fi

echo "🔍 正在从 '$LOG_FILE' 文件中读取ID..."

# 1. grep: 查找所有以日期格式 (例如 08/05/25) 开头的行。
# 2. cut: 使用逗号作为分隔符，提取第二个字段（也就是ID）。
# 3. sort -u: 对ID进行排序并移除重复项，得到唯一的ID列表。
UNIQUE_IDS=$(grep '^[0-9]\{2\}/[0-9]\{2\}/[0-9]\{2\}' "$LOG_FILE" | cut -d, -f2 | sort -u)

if [ -z "$UNIQUE_IDS" ]; then
    echo "在日志文件中未找到有效的目录ID。"
    exit 0
fi

echo "------------------------------------------------------------"
echo "❗️ 以下目录将被删除："
echo "------------------------------------------------------------"

# 循环显示每个待删除目录的完整路径，供用户二次确认
for id in $UNIQUE_IDS; do
    # 确保ID不为空
    if [ -n "$id" ]; then
        echo "$BASE_PATH/$id"
    fi
done

echo "------------------------------------------------------------"

# 在执行删除操作前，请求用户确认
read -p "🚨 您确定要永久删除这些目录吗？ (y/n) " -n 1 -r
echo "" # 等待用户输入后换行

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "✅ 好的，正在执行删除操作..."
    for id in $UNIQUE_IDS; do
        if [ -n "$id" ]; then
            TARGET_DIR="$BASE_PATH/$id"
            if [ -d "$TARGET_DIR" ]; then
                echo "正在删除 $TARGET_DIR..."
                # 使用 sudo 来确保有权限删除
                sudo rm -rf "$TARGET_DIR"
            else
                echo "跳过 $TARGET_DIR (目录未找到)。"
            fi
        fi
    done
    echo "✨ 删除完成。"
else
    echo "❌ 用户已取消删除操作。"
fi