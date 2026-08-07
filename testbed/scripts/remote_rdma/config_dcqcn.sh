for host in dc20 dc21 dc22 dc23; do
  for dev in mlx5_0 mlx5_1 mlx5_2 mlx5_3; do
    ssh $host "sudo mlxconfig -y -d $dev s \
      DCE_TCP_G_P1=1019 DCE_TCP_G_P2=1019\
      DCE_TCP_RTT_P1=10 DCE_TCP_RTT_P2=10 \
      INITIAL_ALPHA_VALUE_P1=1023 INITIAL_ALPHA_VALUE_P2=1023 \
      RATE_REDUCE_MONITOR_PERIOD_P1=4 RATE_REDUCE_MONITOR_PERIOD_P2=4 \
      CLAMP_TGT_RATE_P1=0 CLAMP_TGT_RATE_P2=0 \
      RPG_TIME_RESET_P1=300 RPG_TIME_RESET_P2=300 \
      RPG_AI_RATE_P1=40 RPG_AI_RATE_P2=40\
      RPG_HAI_RATE_P1=100 RPG_HAI_RATE_P2=100 \
      RPG_MIN_RATE_P1=100 RPG_MIN_RATE_P2=100"
  done
done

for host in dc20 dc21 dc22 dc23; do
  ssh $host "sudo reboot"
done
