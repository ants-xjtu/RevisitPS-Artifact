for host in dc20 dc21 dc22 dc23; do
  for dev in mlx5_0 mlx5_1 mlx5_2 mlx5_3; do
    ssh $host "sudo mlxconfig -y -d $dev r"
  done
done
