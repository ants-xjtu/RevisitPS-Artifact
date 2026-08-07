for host in dc20; do
  for eth in enp153s0f0np0 enp153s0f1np1 enp174s0f0np0 enp174s0f1np1; do
    ssh $host "echo 0 | sudo tee /sys/class/net/$eth/ecn/roce_rp/enable/0 && echo 0 | sudo tee /sys/class/net/$eth/ecn/roce_np/enable/0"
  done
done

for host in dc21 dc22 dc23; do
  for eth in enp10s0f0np0 enp10s0f1np1 enp173s0f0np0 enp173s0f1np1; do
    ssh $host "echo 0 | sudo tee /sys/class/net/$eth/ecn/roce_rp/enable/0 && echo 0 | sudo tee /sys/class/net/$eth/ecn/roce_np/enable/0"
  done
done