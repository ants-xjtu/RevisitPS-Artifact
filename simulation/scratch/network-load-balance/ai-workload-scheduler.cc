#include "ai-workload-scheduler.h"
#include "ai-workload-tracker.h" // 调度器需要与追踪器交互
#include "ns3/rdma-client-helper.h"
#include "ns3/application-container.h"
#include "ns3/core-module.h"
#include "ns3/settings.h" // for ns3::Settings
#include <iostream>
#include <cassert>

void ScheduleAllToAllRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups, uint64_t message_size,
                           ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                           std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {
    std::cout << "[Scheduler] Scheduling All-to-All Round " << round_num << " at " << ns3::Simulator::Now().GetSeconds() << "s." << std::endl;
    ns3::Time startTime = ns3::Simulator::Now();

    for (uint32_t g = 0; g < groups.size(); ++g) {
        for (const auto& src_id : groups[g]) {
            for (const auto& dst_id : groups[g]) {
                if (src_id == dst_id) continue;
                // *** DEBUG OUTPUT FOR EACH FLOW ***
                uint32_t window_arg = WorkloadTracker::GetInstance().GetWindow();
                uint64_t rtt_arg = WorkloadTracker::GetInstance().GetRtt();

                // std::cout << "[Flow] All-to-All Round " << round_num << ", Group " << g
                //           << ": " << src_id << " -> " << dst_id
                //           << " | sport: " <<  sport_map[src_id]
                //           << " | dport: " <<  dport_map[dst_id]
                //           << " | Start: " << startTime.GetSeconds() << "s"
                //           << " | Message: " << message_size << " bytes"
                //           << " | Window: " << window_arg
                //           << " | RTT: " << rtt_arg
                //           << std::endl;
                ns3::RdmaClientHelper clientHelper(3, addresses[src_id], addresses[dst_id],
                                                 sport_map[src_id]++, dport_map[dst_id]++,
                                                 message_size, window_arg, rtt_arg);
                // clientHelper.SetFlowMetadata(g, round_num); // step_id for alltoall can be the round_num
                ns3::ApplicationContainer app = clientHelper.Install(all_nodes.Get(src_id));
                app.Start(ns3::Time(0));
                app.Stop(ns3::Seconds(1000.0));
            }
        }
    }
}

void ScheduleAllToAllVRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups,
                           const std::vector<std::vector<uint64_t>>& message_sizes,
                           ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                           std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {
    std::cout << "[Scheduler] Scheduling All-to-All-V Round " << round_num << " at " << ns3::Simulator::Now().GetSeconds() << "s." << std::endl;
    ns3::Time startTime = ns3::Simulator::Now();

    for (uint32_t g = 0; g < groups.size(); ++g) {
        const auto& group = groups[g];
        const auto& group_message_sizes = message_sizes[g];

        for (size_t src_idx = 0; src_idx < group.size(); ++src_idx) {
            uint32_t src_id = group[src_idx];

            for (size_t dst_idx = 0; dst_idx < group.size(); ++dst_idx) {
                uint32_t dst_id = group[dst_idx];

                if (src_id == dst_id) continue;

                // 计算消息大小矩阵索引 (src_idx * group_size + dst_idx)
                size_t msg_idx = src_idx * group.size() + dst_idx;
                uint64_t msg_size = (msg_idx < group_message_sizes.size()) ? group_message_sizes[msg_idx] : 0;

                if (msg_size == 0) {
                    std::cerr << "Warning: Message size is 0 for flow " << src_id << " -> " << dst_id << std::endl;
                    continue;
                }

                uint32_t window_arg = WorkloadTracker::GetInstance().GetWindow();
                uint64_t rtt_arg = WorkloadTracker::GetInstance().GetRtt();

                std::cout << "[Flow] All-to-All-V Round " << round_num << ", Group " << g
                          << ": " << src_id << " -> " << dst_id
                          << " | sport: " << sport_map[src_id]
                          << " | dport: " << dport_map[dst_id]
                          << " | Start: " << startTime.GetSeconds() << "s"
                          << " | Message: " << msg_size << " bytes"
                          << " | Window: " << window_arg
                          << " | RTT: " << rtt_arg
                          << std::endl;

                ns3::RdmaClientHelper clientHelper(3, addresses[src_id], addresses[dst_id],
                                                 sport_map[src_id]++, dport_map[dst_id]++,
                                                 msg_size, window_arg, rtt_arg);

                ns3::ApplicationContainer app = clientHelper.Install(all_nodes.Get(src_id));
                app.Start(ns3::Time(0));
                app.Stop(ns3::Seconds(1000.0));
            }
        }
    }
}

void ScheduleRingNodeStep(uint32_t node_id, uint32_t group_id, uint32_t step, uint64_t message_size,
                         ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                         std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {

    // 验证node_id有效性
    if (node_id >= all_nodes.GetN()) {
        std::cerr << "[ERROR] Invalid node_id " << node_id
                  << " in ScheduleRingNodeStep (max: " << all_nodes.GetN()-1 << ")" << std::endl;
        return;
    }

    NodeState& src_state = WorkloadTracker::GetInstance().GetNodeState(node_id);
    uint32_t next_pos = (src_state.ring_pos + 1) % src_state.num_nodes_in_ring;
    uint32_t dst_id = WorkloadTracker::GetInstance().GetNodeAt(group_id, next_pos);

    // 验证dst_id有效性
    if (dst_id >= all_nodes.GetN()) {
        std::cerr << "[ERROR] Invalid dst_id " << dst_id
                  << " in ScheduleRingNodeStep (max: " << all_nodes.GetN()-1 << ")" << std::endl;
        return;
    }

    NodeState& dst_state = WorkloadTracker::GetInstance().GetNodeState(dst_id);
    src_state.sending_current_step = true;
    if(src_state.need_to_send_datas > 0) {
        src_state.need_to_send_datas--;
    } else {
        std::cerr << "[ERROR] Ring AllReduce: node " << node_id
                  << " has no data to send in step " << step << std::endl;
        return; // 优雅退出而不是崩溃
    }

    if(node_id == dst_id) {
        std::cerr << "[ERROR] Ring AllReduce: node " << node_id
                  << " trying to send to itself" << std::endl;
        return; // 优雅退出而不是崩溃
    }
    ns3::Time startTime = ns3::Simulator::Now();
    // *** DEBUG OUTPUT FOR EACH FLOW ***
    uint32_t window_arg = WorkloadTracker::GetInstance().GetWindow();
    uint64_t rtt_arg = WorkloadTracker::GetInstance().GetRtt();
    // std::cout << "[Flow] Ring All-Reduce Step " << step << ", Group " << group_id
    //           << ": " << node_id << " -> " << dst_id
    //           << " | sport: " <<  sport_map[node_id]
    //           << " | dport: " <<  dport_map[dst_id]
    //           << " | Start: " << startTime.GetSeconds() << "s"
    //           << " | Message: " << message_size << " bytes"
    //           << " | Window: " << window_arg
    //           << " | RTT: " << rtt_arg
    //           << std::endl;

    ns3::RdmaClientHelper clientHelper(3, addresses[node_id], addresses[dst_id],
                                     sport_map[node_id]++, dport_map[dst_id]++,
                                     message_size, window_arg, rtt_arg);
    // clientHelper.SetFlowMetadata(group_id, step);

    ns3::ApplicationContainer app = clientHelper.Install(all_nodes.Get(node_id));
    app.Start(ns3::Time(0));
    app.Stop(ns3::Seconds(1000.0));
}

void StartRingAllReduceRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups, uint64_t message_size,
                            ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                            std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {
    std::cout << "[Scheduler] Starting Ring All-Reduce Round " << round_num << " at " << ns3::Simulator::Now().GetSeconds() << "s." << std::endl;

    for (uint32_t g = 0; g < groups.size(); ++g) {
        for (const auto& node_id : groups[g]) {
            // 所有节点同时开始第0步
            ScheduleRingNodeStep(node_id, g, 0, message_size, all_nodes, addresses, sport_map, dport_map);
        }
    }
}

void StartTreeAllReduceRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups, uint64_t message_size,
                            ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                            std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {
    std::cout << "[Scheduler] Starting Tree All-Reduce Round " << round_num << " at " << ns3::Simulator::Now().GetSeconds() << "s." << std::endl;

    // 启动所有叶子节点的reduce阶段
    for (uint32_t g = 0; g < groups.size(); ++g) {
        for (const auto& node_id : groups[g]) {
            TreeNodeState& state = WorkloadTracker::GetInstance().GetTreeNodeState(node_id);

            // 如果这是叶子节点，立即开始向父节点发送
            if (state.children_ids.empty() && !state.is_root) {
                ScheduleTreeNodeToParent(node_id, message_size, all_nodes, addresses, sport_map, dport_map);
            }
        }
    }
}

void ScheduleTreeNodeToParent(uint32_t node_id, uint64_t message_size,
                             ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                             std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {

    // 验证node_id有效性
    if (node_id >= all_nodes.GetN()) {
        std::cerr << "[ERROR] Invalid node_id " << node_id
                  << " in ScheduleTreeNodeToParent (max: " << all_nodes.GetN()-1 << ")" << std::endl;
        return;
    }

    TreeNodeState& state = WorkloadTracker::GetInstance().GetTreeNodeState(node_id);
    uint32_t parent_id = state.parent_id;

    // 验证parent_id有效性
    if (parent_id >= all_nodes.GetN()) {
        std::cerr << "[ERROR] Invalid parent_id " << parent_id
                  << " in ScheduleTreeNodeToParent (max: " << all_nodes.GetN()-1 << ")" << std::endl;
        return;
    }

    if (state.is_root || parent_id == node_id) {
        std::cerr << "Error: Trying to send to parent from root node " << node_id << std::endl;
        return;
    }

    uint32_t window_arg = WorkloadTracker::GetInstance().GetWindow();
    uint64_t rtt_arg = WorkloadTracker::GetInstance().GetRtt();

    std::cout << "[Flow] Tree All-Reduce Reduce Phase: " << node_id << " -> " << parent_id
              << " | Start: " << ns3::Simulator::Now().GetSeconds() << "s"
              << " | Message: " << message_size << " bytes" << std::endl;

    ns3::RdmaClientHelper clientHelper(3, addresses[node_id], addresses[parent_id],
                                     sport_map[node_id]++, dport_map[parent_id]++,
                                     message_size, window_arg, rtt_arg);

    ns3::ApplicationContainer app = clientHelper.Install(all_nodes.Get(node_id));
    app.Start(ns3::Time(0));
    app.Stop(ns3::Seconds(1000.0));
}

void ScheduleTreeNodeToChild(uint32_t node_id, uint32_t child_id, uint64_t message_size,
                            ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                            std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {

    uint32_t window_arg = WorkloadTracker::GetInstance().GetWindow();
    uint64_t rtt_arg = WorkloadTracker::GetInstance().GetRtt();

    std::cout << "[Flow] Tree All-Reduce Broadcast Phase: " << node_id << " -> " << child_id
              << " | Start: " << ns3::Simulator::Now().GetSeconds() << "s"
              << " | Message: " << message_size << " bytes" << std::endl;

    ns3::RdmaClientHelper clientHelper(3, addresses[node_id], addresses[child_id],
                                     sport_map[node_id]++, dport_map[child_id]++,
                                     message_size, window_arg, rtt_arg);

    ns3::ApplicationContainer app = clientHelper.Install(all_nodes.Get(node_id));
    app.Start(ns3::Time(0));
    app.Stop(ns3::Seconds(1000.0));
}

// 分块Tree AllReduce调度函数实现
void StartTreeAllReduceChunkedRound(uint32_t round_num, const std::vector<std::vector<uint32_t>>& groups,
                                   uint64_t chunk_size, uint32_t num_chunks,
                                   ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                                   std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {
    std::cout << "[Scheduler] Starting Chunked Tree All-Reduce Round " << round_num
              << " with " << num_chunks << " chunks at " << ns3::Simulator::Now().GetSeconds() << "s." << std::endl;

    // 启动所有叶子节点的第一个chunk reduce阶段
    for (uint32_t g = 0; g < groups.size(); ++g) {
        for (const auto& node_id : groups[g]) {
            TreeNodeState& state = WorkloadTracker::GetInstance().GetTreeNodeState(node_id);

            // 如果这是叶子节点，立即开始发送第一个chunk
            if (state.children_ids.empty() && !state.is_root) {
                ScheduleTreeChunkToParent(node_id, 0, chunk_size, all_nodes, addresses, sport_map, dport_map);
            }
        }
    }
}

void ScheduleTreeChunkToParent(uint32_t node_id, uint32_t chunk_id, uint64_t chunk_size,
                              ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                              std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {

    TreeNodeState& state = WorkloadTracker::GetInstance().GetTreeNodeState(node_id);
    uint32_t parent_id = state.parent_id;

    if (state.is_root || parent_id == node_id) {
        std::cerr << "Error: Trying to send chunk to parent from root node " << node_id << std::endl;
        return;
    }

    // 标记chunk已发送
    state.chunks_sent_to_parent[chunk_id] = true;

    uint32_t window_arg = WorkloadTracker::GetInstance().GetWindow();
    uint64_t rtt_arg = WorkloadTracker::GetInstance().GetRtt();

    std::cout << "[Flow] Tree All-Reduce Chunk " << chunk_id << " Reduce: " << node_id << " -> " << parent_id
              << " | Start: " << ns3::Simulator::Now().GetSeconds() << "s"
              << " | Chunk Size: " << chunk_size << " bytes" << std::endl;

    // 使用chunk_id编码端口，避免乱序完成时的chunk ID推断错误
    uint16_t encoded_sport = sport_map[node_id] + chunk_id * 1000;  // 基础端口 + chunk_id * 1000
    uint16_t encoded_dport = dport_map[parent_id] + chunk_id * 1000;
    sport_map[node_id] = std::max(sport_map[node_id], static_cast<uint16_t>(encoded_sport + 1));  // 更新基础端口
    dport_map[parent_id] = std::max(dport_map[parent_id], static_cast<uint16_t>(encoded_dport + 1));

    ns3::RdmaClientHelper clientHelper(3, addresses[node_id], addresses[parent_id],
                                     encoded_sport, encoded_dport,
                                     chunk_size, window_arg, rtt_arg);

    ns3::ApplicationContainer app = clientHelper.Install(all_nodes.Get(node_id));
    app.Start(ns3::Time(0));
    app.Stop(ns3::Seconds(1000.0));
}

void ScheduleTreeChunkToChild(uint32_t node_id, uint32_t child_id, uint32_t chunk_id, uint64_t chunk_size,
                             ns3::NodeContainer& all_nodes, std::vector<ns3::Ipv4Address>& addresses,
                             std::unordered_map<uint32_t, uint16_t>& sport_map, std::unordered_map<uint32_t, uint16_t>& dport_map) {

    TreeNodeState& state = WorkloadTracker::GetInstance().GetTreeNodeState(node_id);
    state.chunks_sent_to_children[chunk_id]++;

    uint32_t window_arg = WorkloadTracker::GetInstance().GetWindow();
    uint64_t rtt_arg = WorkloadTracker::GetInstance().GetRtt();

    std::cout << "[Flow] Tree All-Reduce Chunk " << chunk_id << " Broadcast: " << node_id << " -> " << child_id
              << " | Start: " << ns3::Simulator::Now().GetSeconds() << "s"
              << " | Chunk Size: " << chunk_size << " bytes" << std::endl;

    // 使用chunk_id编码端口，避免乱序完成时的chunk ID推断错误
    uint16_t encoded_sport = sport_map[node_id] + chunk_id * 1000;  // 基础端口 + chunk_id * 1000
    uint16_t encoded_dport = dport_map[child_id] + chunk_id * 1000;
    sport_map[node_id] = std::max(sport_map[node_id], static_cast<uint16_t>(encoded_sport + 1));  // 更新基础端口
    dport_map[child_id] = std::max(dport_map[child_id], static_cast<uint16_t>(encoded_dport + 1));

    ns3::RdmaClientHelper clientHelper(3, addresses[node_id], addresses[child_id],
                                     encoded_sport, encoded_dport,
                                     chunk_size, window_arg, rtt_arg);

    ns3::ApplicationContainer app = clientHelper.Install(all_nodes.Get(node_id));
    app.Start(ns3::Time(0));
    app.Stop(ns3::Seconds(1000.0));
}