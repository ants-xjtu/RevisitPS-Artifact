#ifndef AI_WORKLOAD_SCHEDULER_H
#define AI_WORKLOAD_SCHEDULER_H

#include <vector>
#include <string>
#include <unordered_map>
#include "ns3/node-container.h"
#include "ns3/ipv4-address.h"

// 调度 All-to-All 的一轮
void ScheduleAllToAllRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups, uint64_t message_size,
                           ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                           std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

// 调度 All-to-All-V 的一轮 (变长消息)
void ScheduleAllToAllVRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups,
                           const std::vector<std::vector<uint64_t>>& message_sizes,
                           ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                           std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

// 启动 Ring All-Reduce 的一轮 (调度所有节点的第0步)
void StartRingAllReduceRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups, uint64_t message_size,
                            ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses, 
                            std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

// 调度 Ring All-Reduce 中单个节点的单步操作
void ScheduleRingNodeStep(uint32_t node_id, uint32_t group_id, uint32_t step, uint64_t message_size,
                         ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                         std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

// 启动 Tree All-Reduce 的一轮 (调度所有叶子节点开始reduce阶段)
void StartTreeAllReduceRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups, uint64_t message_size,
                            ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                            std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

// 调度 Tree All-Reduce 中单个节点向父节点发送 (reduce阶段)
void ScheduleTreeNodeToParent(uint32_t node_id, uint64_t message_size,
                             ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                             std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

// 调度 Tree All-Reduce 中单个节点向子节点发送 (broadcast阶段)
void ScheduleTreeNodeToChild(uint32_t node_id, uint32_t child_id, uint64_t message_size,
                            ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                            std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

// 分块Tree AllReduce调度函数
void StartTreeAllReduceChunkedRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups,
                                   uint64_t chunk_size, uint32_t num_chunks,
                                   ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                                   std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

void ScheduleTreeChunkToParent(uint32_t node_id, uint32_t chunk_id, uint64_t chunk_size,
                              ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                              std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

void ScheduleTreeChunkToChild(uint32_t node_id, uint32_t child_id, uint32_t chunk_id, uint64_t chunk_size,
                             ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                             std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map);

#endif // AI_WORKLOAD_SCHEDULER_H