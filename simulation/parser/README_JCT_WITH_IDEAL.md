# JCT Analysis with Ideal Baselines

这套工具可以从history文件解析JCT结果，自动计算ideal JCT基线，并生成包含对比分析的图表。

## 工具说明

### 1. `parse_jct_with_ideal.py` - 解析脚本
从history文件读取实验配置，解析JCT结果，并集成optimal JCT计算。

**功能特点：**
- 自动识别AlltoallV流量模式（uniform/zipfian/moe）
- 支持Tree AllReduce和Ring AllReduce工作负载
- 为每个message size计算动态ideal JCT基线
- 输出包含实验结果和ideal JCT的JSON文件

**使用方法：**
```bash
# 基本用法
python3 praser/parse_jct_with_ideal.py your_history_file.log

# 指定参数
python3 praser/parse_jct_with_ideal.py your_history_file.log \
  --group_size 8 \
  --topology leaf_spine_L8_S16_100G_OS1 \
  -sT 0 -fT 10000000000000000000
```

**参数说明：**
- `history_file`: History文件路径
- `--group_size`: GPU组大小 (默认: 8)
- `--topology`: 网络拓扑名称 (默认: fat_k8_100G_OS1)
- `-sT`: 开始时间过滤 (默认: 0)
- `-fT`: 结束时间过滤 (默认: 很大的数)

### 2. `plot_jct_with_ideal.py` - 绘图脚本
生成包含ideal JCT基线的JCT vs Rank图表。

**功能特点：**
- 绘制不同算法的JCT曲线
- 添加动态ideal JCT参考线
- 显示性能分析（AR算法与ideal对比）
- 支持线性刻度显示

**使用方法：**
```bash
# 处理整个目录
python3 praser/plot_jct_with_ideal.py praser/json-data-jct-with-ideal/

# 处理单个JSON文件
python3 praser/plot_jct_with_ideal.py path/to/specific_file.json
```

## 工作流程

### 完整分析流程：
```bash
# 1. 解析history文件并计算ideal JCT
python3 praser/parse_jct_with_ideal.py analysis/History_leaf_spine_L8_S16_100G_OS1_AlltoallV_uniform_0.0_0_100_50.log \
  --group_size 8 --topology leaf_spine_L8_S16_100G_OS1

# 2. 生成包含ideal基线的图表
python3 praser/plot_jct_with_ideal.py praser/json-data-jct-with-ideal/

# 3. 查看生成的PDF图表
ls praser/json-data-jct-with-ideal/*.pdf
```

## 输出文件

### JSON文件格式
```json
{
  "metadata": {
    "topology": "leaf_spine_L8_S16_100G_OS1",
    "load_type": "AlltoallV",
    "workload_pattern": "uniform",
    ...
  },
  "data_series": [
    {
      "load_balancing_mode": "ConWeave",
      "message_size_bytes": 32768000,
      "ranks": [0, 1, 2, ...],
      "avg_jct_us": [1234.5, 2345.6, ...]
    }
  ],
  "ideal_jct_data": {
    "32768000": {
      "ideal_jct_us": 18350.08,
      "workload": "AlltoallV",
      "pattern": "uniform"
    }
  }
}
```

### 生成的图表
- **文件名格式**: `JCT_WITH_IDEAL_TOPO_xxx_TYPE_xxx_MSG_xxx.pdf`
- **内容**: JCT vs Rank曲线 + Ideal JCT参考线
- **分析**: AR算法与ideal基线的详细对比数据

## History文件格式支持

支持标准的history文件格式：
```
日期,实验ID,CC模式,LB模式,AR模式,窗口,缓存,分组,窗口,超时,RTT,PFC,IRN,MTU,缓存大小,拓扑,负载,工作负载,消息大小,错误率,仿真时间,超时模式,其他参数...
01/19/26,705210107,1,9,0,300,4,16,16,200,0,1,1,0,512000,leaf_spine_L8_S16_100G_OS1,100,AlltoallV,32768000,0.0,0.05,0,320,100
```

## 支持的工作负载

1. **AlltoallV**: 支持uniform/zipfian/moe流量模式
2. **Alltoall**: 传统的全对全通信（uniform模式）
3. **RingAllreduce**: 环形AllReduce
4. **TreeAllreduce**: 树形AllReduce

## 注意事项

1. 确保`optimal_jct_analyzer.py`在`analysis/`目录中
2. JCT数据文件需要存在于`mix/output/{实验ID}/{实验ID}_out_jct.txt`
3. 如果找不到拓扑文件，将使用默认参数计算ideal JCT
4. 脚本会自动从config ID中提取流量模式（uniform/zipfian/moe）

## 示例输出

```
Processing history file: analysis/History_xxx.log
Calculated ideal JCT for AlltoallV (uniform): 18350.08 μs
Saving data with ideal JCT to: praser/json-data-jct-with-ideal/JCT_WITH_IDEAL_xxx.json
  Group summary: AlltoallV (uniform)
    Message size 32768000: Ideal JCT = 18350.08 μs

--- Processing JCT_WITH_IDEAL_xxx.json ---
  -> Generating plot for message size: 31MB
  📊 Performance Analysis: AR(RTO+GBN) vs Ideal (AlltoallV)
    Rank 0: AR=25.123 ms, Ideal=18.350 ms, 差值=6.773 ms (36.91%)
    ...
  ✅ JCT plot with ideal baseline saved to: xxx_MSG_32768000.pdf
```