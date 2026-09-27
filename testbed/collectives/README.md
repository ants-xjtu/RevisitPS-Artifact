# Collective experiments

Ring Allreduce、Alltoall、Alltoallv 的编译、运行和结果汇总。

## 文件

- `src/`: 三种流量的源码及必要依赖。
- `scripts/`: 编译、三个运行入口、结果汇总；`engines/` 为入口使用的运行实现。
- `configs/`: 主机、NIC、GID、rankfile 和 150MiB 实验参数。
- `reference-results/`: 历史原始结果及 `summary.csv`，重复实验分别保留。
- `results/`: 新运行的 CSV、日志、命令和配置副本，按实验/run-id 保存。
- `build/`: 编译产物；与 `results/` 一起被 Git 忽略。

## 环境准备

需要 Bash、Python 3、C++ 编译器、OpenMPI、libibverbs 和 librdmacm 开发库。
确保本地 `mpicxx`、`mpirun` 使用同一套 MPI，远端安装对应运行库并配置 SSH 免密访问。
运行前核对 `configs/sites/dc20-dc23.json` 和 `configs/rankfiles/` 中的主机、网卡、GID、CPU 绑定。
默认从 dc20 启动，以便结果 CSV 写在启动机器上。更换站点需同步修改配置和 rankfile。

```bash
ip -br address
ip link show
ibv_devinfo -v
show_gids
lscpu -e
ip neigh show
```

需要静态 ARP 时，按实际源接口及目标 IP/MAC 逐项配置；先记录旧条目以便恢复。

```bash
ip -j neigh show > neighbors.before.json
sudo ip neigh replace <目标IPv4> lladdr <目标MAC> dev <源Linux接口> nud permanent
```

`neighbors.before.json` 是检查记录，不能直接导入恢复。回退时逐项恢复旧条目，仅删除本次新增项。
交换机、PFC、DCQCN 等准备沿用 [testbed README](../README.md)，在实验 JSON 中记录所用网络配置。
运行入口不会修改 ARP 或交换机配置。

## 编译与运行

进入目录后直接编译。本机无需先手动把 MPI 加入 PATH：

```bash
cd /home/jcma/RevisitPS-Artifact/testbed/collectives
bash scripts/build.sh
```

脚本依次使用 `MPICXX`、`MPI_HOME/bin/mpicxx`、PATH 中的 `mpicxx`、`$HOME/ompi/bin/mpicxx`。
显式指定的路径无效时直接报错。本机自动找到 `/home/jcma/ompi/bin/mpicxx`。
编译成功后在 `build/` 生成 `mpi_verbs_global_alltoall`、`mpi_verbs_p2p_ring4`、`mpi_verbs_global_alltoallv`。

其他安装位置可统一指定 MPI，后续编译和运行均使用该设置：

```bash
export MPI_HOME=/path/to/openmpi
bash scripts/build.sh
# 或者使用 export MPICXX=/path/to/openmpi/bin/mpicxx
```

运行入口使用编译器同目录的 `mpirun`。远端仍需安装兼容的 MPI/RDMA 运行库。
离线预览无需安装 MPI：

```bash
# 离线预览，不连接 testbed、不启动 MPI。
bash scripts/run_ring_allreduce.sh --run-id preview --dry-run
bash scripts/run_alltoall.sh --run-id preview --dry-run
bash scripts/run_alltoallv.sh --run-id preview --dry-run
```

Testbed 准备好后，从 dc20 执行。三个入口会自动编译和分发二进制，也可以提前单独 build：

```bash
bash scripts/run_ring_allreduce.sh --run-id trial1
bash scripts/run_alltoall.sh --run-id trial1
bash scripts/run_alltoallv.sh --run-id trial1
```

支持 `--site /path/site.json --experiment /path/experiment.json`；默认使用 `configs/` 下的配置。
站点 JSON 中相对 rankfile 路径以本目录为基准。同一种实验每次使用新的 run-id，避免覆盖。
结果位于 `results/<实验>/<run-id>/`；失败时查看 `build.log`、`launcher.log` 和程序日志。

## 整理结果

```bash
python3 scripts/summarize.py results/alltoall/trial1 > results/alltoall/trial1/summary.csv
python3 scripts/summarize.py reference-results > /tmp/reference-summary.csv
```

输出每份 CSV 的样本数、mean、median、p99、min、max，时间单位为微秒；各组及各次重复分别统计。
`reference-results/` 保留原历史文件名；本次整理未重新运行真实 testbed 实验。
