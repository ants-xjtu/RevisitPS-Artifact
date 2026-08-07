#!/bin/bash

# 主机列表
HOSTS=("dc2" "dc3" "dc4" "dc5" "dc8" "dc9" "dc10" "dc11" "dc12" "dc13" "dc14" "dc15" "dc20")

# mlxconfig 参数（直接写在脚本里）
PARAMS="DCE_TCP_RTT_P1=10 RPG_TIME_RESET_P1=20 RPG_AI_RATE_P1=1000 RPG_HAI_RATE_P1=10000 INITIAL_ALPHA_VALUE_P1=512 RPG_BYTE_RESET_P1=1000 RATE_TO_SET_ON_FIRST_CNP_P1=0 DCE_TCP_RTT_P2=10 RPG_TIME_RESET_P2=20 RPG_AI_RATE_P2=1000 RPG_HAI_RATE_P2=10000 INITIAL_ALPHA_VALUE_P2=512 RPG_BYTE_RESET_P2=1000 RATE_TO_SET_ON_FIRST_CNP_P2=0"

# 遍历主机执行命令
for host in "${HOSTS[@]}"; do
    echo ">>> 连接到 $host"

    ssh "$host" bash -c "'
        echo \">>> 执行 sudo mst start\"
        sudo mst start

        echo \">>> 查找 /dev/mst 下的设备\"
        devices=\$(ls /dev/mst/ | grep pci)

        for dev in \$devices; do
            echo \">>> 在设备 \$dev 上执行 mlxconfig\"
            sudo mlxconfig -d /dev/mst/\$dev -y set $PARAMS
        done

        sudo reboot
    '"
done
