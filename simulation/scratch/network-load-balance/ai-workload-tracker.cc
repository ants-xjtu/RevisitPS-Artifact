#include "ai-workload-tracker.h"
#include "ai-workload-scheduler.h" // 包含调度器头文件
#include "ns3/simulator.h"
#include "ns3/rdma-client-helper.h"
#include "ns3/settings.h"
#include <iostream>

WorkloadTracker& WorkloadTracker::GetInstance() {
    static WorkloadTracker instance;
    return instance;
}

WorkloadTracker::~WorkloadTracker() {
    if (m_jct_output) {
        fclose(m_jct_output);
        m_jct_output = nullptr;
    }
}

std::string WorkloadTypeToString(WorkloadType type) {
    switch(type) {
        case WorkloadType::AllToAll: return "AllToAll";
        case WorkloadType::RingAllReduce: return "RingAllReduce";
        case WorkloadType::AllToAllV: return "AllToAllV";
        case WorkloadType::TreeAllReduce: return "TreeAllReduce";
        default: return "Unknown";
    }
}

void WorkloadTracker::Initialize(WorkloadType type, uint32_t total_rounds, const std::vector<std::vector<uint32_t>>& groups, uint64_t msg_size) {
    // 输入验证
    if (groups.empty()) {
        std::cerr << "[ERROR] Empty groups in Initialize" << std::endl;
        return;
    }
    if (total_rounds == 0) {
        std::cerr << "[ERROR] Total rounds cannot be zero" << std::endl;
        return;
    }
    if (msg_size == 0) {
        std::cerr << "[ERROR] Message size cannot be zero" << std::endl;
        return;
    }

    // 验证所有组都非空
    for (size_t i = 0; i < groups.size(); ++i) {
        if (groups[i].empty()) {
            std::cerr << "[ERROR] Group " << i << " is empty" << std::endl;
            return;
        }
    }

    m_workload_type = type;
    m_total_rounds = total_rounds;
    m_groups = groups;
    m_message_size = msg_size;
    m_current_round = 0;
    m_completed_flows_this_round = 0;

    m_node_to_group_map.clear();
    for (size_t g = 0; g < groups.size(); ++g) {
        for (uint32_t node_id : groups[g]) {
            m_node_to_group_map[node_id] = g;
        }
    }
    

    if (m_workload_type == WorkloadType::RingAllReduce) {
        m_nodes_finished_in_group.resize(groups.size(), 0);
        m_node_states.clear();
        for (size_t g = 0; g < groups.size(); ++g) {
            for (size_t i = 0; i < groups[g].size(); ++i) {
                NodeState state;
                state.node_id = groups[g][i];
                state.group_id = g;
                state.ring_pos = i;
                state.num_nodes_in_ring = groups[g].size();
                state.message_size = m_message_size;
                m_node_states[state.node_id] = state;
            }
        }
        uint32_t nodes_in_ring = groups[0].size();
        m_total_flows_per_round = groups.size() * nodes_in_ring * (nodes_in_ring - 1) * 2;

    } else if (m_workload_type == WorkloadType::AllToAll) {
        m_completed_flows_in_group.resize(groups.size(), 0);
        m_total_flows_per_round = 0;
        uint32_t nodes_in_group = groups[0].size();
        m_total_flows_per_group.resize(groups.size(), nodes_in_group * (nodes_in_group - 1));
        m_total_flows_per_round = groups.size() * nodes_in_group * (nodes_in_group - 1);
    } else if (m_workload_type == WorkloadType::TreeAllReduce) {
        m_nodes_finished_in_group.resize(groups.size(), 0);
        m_tree_node_states.clear();

        // 为每个组构建二叉树结构
        for (size_t g = 0; g < groups.size(); ++g) {
            BuildBinaryTree(groups[g], g);
        }

        // 计算总流量：每个内部节点需要receive + send，叶子只send，根只receive然后broadcast
        // 简化：2*(N-1)个流每组 (N-1个reduce流 + N-1个broadcast流)
        uint32_t nodes_in_group = groups[0].size();
        m_total_flows_per_round = groups.size() * 2 * (nodes_in_group - 1);
    }
    
    m_initialized = true;
    std::cout << "[Tracker] Initialized for '" << WorkloadTypeToString(m_workload_type) << "'. Total Rounds: " << m_total_rounds
              << ", Flows per Round: " << m_total_flows_per_round << std::endl;
}

void WorkloadTracker::InitializeAllToAllV(uint32_t total_rounds, const std::vector<std::vector<uint32_t>>& groups,
                                          const std::vector<std::vector<uint64_t>>& message_sizes) {
    m_workload_type = WorkloadType::AllToAllV;
    m_total_rounds = total_rounds;
    m_groups = groups;
    m_variable_message_sizes = message_sizes;
    m_current_round = 0;
    m_completed_flows_this_round = 0;

    if (groups.empty()) return;

    m_node_to_group_map.clear();
    for (size_t g = 0; g < groups.size(); ++g) {
        for (uint32_t node_id : groups[g]) {
            m_node_to_group_map[node_id] = g;
        }
    }

    m_completed_flows_in_group.resize(groups.size(), 0);
    m_total_flows_per_round = 0;
    uint32_t nodes_in_group = groups[0].size();
    m_total_flows_per_group.resize(groups.size(), nodes_in_group * (nodes_in_group - 1));
    m_total_flows_per_round = groups.size() * nodes_in_group * (nodes_in_group - 1);

    m_initialized = true;
    std::cout << "[Tracker] Initialized AllToAllV. Total Rounds: " << m_total_rounds
              << ", Flows per Round: " << m_total_flows_per_round << std::endl;
}

void WorkloadTracker::InitializeTreeAllReduceChunked(uint32_t total_rounds, const std::vector<std::vector<uint32_t>>& groups,
                                                    uint64_t msg_size, uint32_t num_chunks) {
    m_workload_type = WorkloadType::TreeAllReduce;
    m_total_rounds = total_rounds;
    m_groups = groups;
    m_message_size = msg_size;
    m_tree_num_chunks = num_chunks;
    if (num_chunks == 0) {
        std::cerr << "[ERROR] Number of chunks cannot be zero" << std::endl;
        m_tree_num_chunks = 1;
        m_chunk_size = msg_size;
    } else {
        m_chunk_size = msg_size / num_chunks; // 平均分块
    }
    m_current_round = 0;
    m_completed_flows_this_round = 0;

    if (groups.empty()) return;

    m_node_to_group_map.clear();
    for (size_t g = 0; g < groups.size(); ++g) {
        for (uint32_t node_id : groups[g]) {
            m_node_to_group_map[node_id] = g;
        }
    }

    m_nodes_finished_in_group.resize(groups.size(), 0);
    m_tree_node_states.clear();

    // 为每个组构建二叉树结构
    for (size_t g = 0; g < groups.size(); ++g) {
        BuildBinaryTreeChunked(groups[g], g, num_chunks);
    }

    // 计算总流量：2*(N-1)*num_chunks个流每组 (每个chunk的reduce和broadcast)
    uint32_t nodes_in_group = groups[0].size();
    m_total_flows_per_round = groups.size() * 2 * (nodes_in_group - 1) * num_chunks;

    m_initialized = true;
    std::cout << "[Tracker] Initialized Chunked Tree AllReduce. Total Rounds: " << m_total_rounds
              << ", Chunks: " << num_chunks << ", Chunk Size: " << m_chunk_size
              << ", Flows per Round: " << m_total_flows_per_round << std::endl;
}

void WorkloadTracker::SetSimulationContext(
    const ns3::NodeContainer& all_nodes,
    const std::vector<ns3::Ipv4Address>& addresses,
    const std::unordered_map<uint32_t, uint16_t>& sport_map,
    const std::unordered_map<uint32_t, uint16_t>& dport_map,
    uint32_t win,
    uint64_t rtt)
{
    m_all_nodes = all_nodes;
    m_server_addresses = addresses;
    m_sport_map = sport_map;
    m_dport_map = dport_map;
    m_window = win;
    m_rtt = rtt;
}


void WorkloadTracker::StartFirstRound() {
    ScheduleNextRound();
}

void WorkloadTracker::Reset() {
    m_initialized = false;
    m_workload_type = WorkloadType::Unknown;
    m_current_round = 0;
    m_total_rounds = 0;
    m_message_size = 0;
    m_tree_num_chunks = 1;
    m_chunk_size = 0;
    m_completed_flows_this_round = 0;
    m_total_flows_per_round = 0;
    m_nodes_finished_round = 0;

    m_node_states.clear();
    m_tree_node_states.clear();
    m_groups.clear();
    m_variable_message_sizes.clear();
    m_node_to_group_map.clear();
    m_completed_flows_in_group.clear();
    m_total_flows_per_group.clear();
    m_nodes_finished_in_group.clear();
    // m_flow_chunk_counter.clear(); // 已移除，使用端口编码方式

    if (m_jct_output) {
        fclose(m_jct_output);
        m_jct_output = nullptr;
    }
    m_jct_output_file.clear();
}

void WorkloadTracker::ScheduleNextRound() {
    if (m_current_round >= m_total_rounds) {
        std::cout << "[Tracker] All rounds completed." << std::endl;
        return;
    }
    m_current_round++;
    m_completed_flows_this_round = 0;
    m_nodes_finished_round = 0; 

    m_round_start_time = ns3::Simulator::Now();

    if (m_workload_type == WorkloadType::AllToAll) {
        for (size_t i = 0; i < m_completed_flows_in_group.size(); ++i) {
            m_completed_flows_in_group[i] = 0;
        }
        ScheduleAllToAllRound(m_current_round, m_groups, m_message_size,
                      m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
    } else if (m_workload_type == WorkloadType::AllToAllV) {
        for (size_t i = 0; i < m_completed_flows_in_group.size(); ++i) {
            m_completed_flows_in_group[i] = 0;
        }
        ScheduleAllToAllVRound(m_current_round, m_groups, m_variable_message_sizes,
                      m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
    } else if (m_workload_type == WorkloadType::RingAllReduce) {
        for (size_t i = 0; i < m_nodes_finished_in_group.size(); ++i) {
            m_nodes_finished_in_group[i] = 0;
        }
        // 重置所有节点状态
        for(auto& pair : m_node_states) {
            pair.second.current_step = 0;
            pair.second.finished_steps = 0;
            pair.second.sending_current_step = false; // 初始状态设为 ready，以便开始第0步
            pair.second.need_to_send_datas = 1;
            pair.second.round_completed = false;
        }
        StartRingAllReduceRound(m_current_round, m_groups, m_message_size,
                        m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
    } else if (m_workload_type == WorkloadType::TreeAllReduce) {
        for (size_t i = 0; i < m_nodes_finished_in_group.size(); ++i) {
            m_nodes_finished_in_group[i] = 0;
        }
        // 重置所有节点状态
        for(auto& pair : m_tree_node_states) {
            TreeNodeState& state = pair.second;
            state.reduce_phase_complete = false;
            state.broadcast_phase_complete = false;

            if (m_tree_num_chunks > 1) {
                // 分块模式：重置所有chunk状态
                for (uint32_t i = 0; i < state.num_chunks; ++i) {
                    state.chunks_received_from_children[i] = 0;
                    state.chunks_sent_to_parent[i] = false;
                    state.chunks_received_from_parent[i] = false;
                    state.chunks_sent_to_children[i] = 0;
                }
            }
        }

        if (m_tree_num_chunks > 1) {
            StartTreeAllReduceChunkedRound(m_current_round, m_groups, m_chunk_size, m_tree_num_chunks,
                            m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
        } else {
            StartTreeAllReduceRound(m_current_round, m_groups, m_message_size,
                            m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
        }
    }
}

void WorkloadTracker::OnFlowComplete(ns3::Ptr<ns3::RdmaQueuePair> qp) {
    if (!m_initialized || m_current_round == 0) return;

    // 验证qp指针有效性
    if (!qp) {
        std::cerr << "[ERROR] Null qp in OnFlowComplete" << std::endl;
        return;
    }

    if (m_workload_type == WorkloadType::AllToAll || m_workload_type == WorkloadType::AllToAllV) {
        m_completed_flows_this_round++;
        uint32_t src_id = ns3::Settings::ip_to_node_id(qp->sip);
        auto it = m_node_to_group_map.find(src_id);
        if (it != m_node_to_group_map.end()) {
            uint32_t group_id = it->second;
            if (group_id < m_completed_flows_in_group.size()) {
                m_completed_flows_in_group[group_id]++;
                CheckGroupCompletionAndLogJct(group_id);
            } else {
                std::cerr << "[ERROR] Invalid group_id " << group_id
                          << " in OnFlowComplete AllToAll" << std::endl;
            }
        }
        if (m_completed_flows_this_round >= m_total_flows_per_round) {
            std::cout << "[Tracker] " << (m_workload_type == WorkloadType::AllToAllV ? "All-to-All-V" : "All-to-All")
                      << " Round " << m_current_round << " completed at "
                      << ns3::Simulator::Now().GetSeconds() << "s." << std::endl;
            ScheduleNextRound();
        }
    } else if (m_workload_type == WorkloadType::RingAllReduce) {
        uint32_t src_id = ns3::Settings::ip_to_node_id(qp->sip);
        uint32_t dst_id = ns3::Settings::ip_to_node_id(qp->dip);

        auto src_it = m_node_states.find(src_id);
        auto dst_it = m_node_states.find(dst_id);

        if (src_it == m_node_states.end() || dst_it == m_node_states.end()) {
            std::cerr << "[ERROR] Node states not found in OnFlowComplete RingAllReduce: "
                      << "src=" << src_id << " dst=" << dst_id << std::endl;
            return;
        }

        NodeState& src_state = src_it->second;
        NodeState& dst_state = dst_it->second;
        
        // 【第1步】更新狀態標記：只做最基本的事
        src_state.sending_current_step = false;
        dst_state.need_to_send_datas ++;
        src_state.finished_steps ++;

        if (!src_state.round_completed && src_state.finished_steps >= (src_state.num_nodes_in_ring - 1) * 2) {
            src_state.round_completed = true;
            m_nodes_finished_round++;

            uint32_t group_id = src_state.group_id;
            if (group_id < m_nodes_finished_in_group.size()) {
                m_nodes_finished_in_group[group_id]++;
                CheckGroupCompletionAndLogJct(group_id);
            } else {
                std::cerr << "[ERROR] Invalid group_id " << group_id
                          << " in Ring AllReduce completion" << std::endl;
            }
            // std::cout << "[Tracker] Node " << src_id 
            //           << " finished Ring-AllReduce round " << m_current_round 
            //           << " at " << ns3::Simulator::Now().GetSeconds() << "s."  
            //           << " current_step: " << src_state.current_step 
            //           << " finish_step: " << src_state.finished_steps  << std::endl;
        }
        
        // 【第2步】獨立檢查發送方（src）是否可以推進
        if (src_state.IsReadyForNextStep()) {
            TriggerNextStepForNode(src_id);
        }
        
        // 【第3步】獨立檢查接收方（dst）是否可以推進
        // 確保 src 和 dst 不是同一個節點，以防重複調用
        if (dst_state.IsReadyForNextStep()) {
            TriggerNextStepForNode(dst_id);
        }

        CheckRoundCompletion();
    } else if (m_workload_type == WorkloadType::TreeAllReduce) {
        uint32_t src_id = ns3::Settings::ip_to_node_id(qp->sip);
        uint32_t dst_id = ns3::Settings::ip_to_node_id(qp->dip);

        auto src_it = m_tree_node_states.find(src_id);
        auto dst_it = m_tree_node_states.find(dst_id);

        if (src_it == m_tree_node_states.end() || dst_it == m_tree_node_states.end()) {
            std::cerr << "[ERROR] Tree node states not found in OnFlowComplete: "
                      << "src=" << src_id << " dst=" << dst_id << std::endl;
            return;
        }

        TreeNodeState& src_state = src_it->second;
        TreeNodeState& dst_state = dst_it->second;

        if (m_tree_num_chunks > 1) {
            // 分块版本的流完成处理
            ProcessChunkedTreeAllReduceFlow(src_id, dst_id, qp, src_state, dst_state);
        } else {
            // 原版本的流完成处理
            ProcessSimpleTreeAllReduceFlow(src_id, dst_id, src_state, dst_state);
        }

        m_completed_flows_this_round++;
        CheckRoundCompletion();
    }
}

void WorkloadTracker::CheckRoundCompletion() {
    uint32_t total_nodes_in_workload = 0;
    for(const auto& group : m_groups) {
        total_nodes_in_workload += group.size();
    }

    if (m_nodes_finished_round >= total_nodes_in_workload) {
         std::cout << "[Tracker] Ring All-Reduce Round " << m_current_round << " completed at " 
                  << ns3::Simulator::Now().GetSeconds() << "s." << std::endl;
        ScheduleNextRound();
    }
}


// 新的輔助函數，當一個節點確認可以進入下一步時被調用
void WorkloadTracker::TriggerNextStepForNode(uint32_t node_id) {
    NodeState& state = m_node_states.at(node_id);
    uint32_t total_steps_in_round = (state.num_nodes_in_ring - 1) * 2;

    // 推進到下一步
    state.current_step++;
    
    // 如果本輪還有更多的步驟要走
    if (state.current_step < total_steps_in_round) {
        ScheduleRingNodeStep(node_id, state.group_id, state.current_step, state.message_size,
                     m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
    }
}

NodeState& WorkloadTracker::GetNodeState(uint32_t node_id) {
    auto it = m_node_states.find(node_id);
    if (it == m_node_states.end()) {
        std::cerr << "[ERROR] Node state not found for node " << node_id << std::endl;
        static NodeState dummy_state;  // 返回空状态避免崩溃
        return dummy_state;
    }
    return it->second;
}

uint32_t WorkloadTracker::GetNodeAt(uint32_t group_id, uint32_t ring_pos) const {
    if (group_id >= m_groups.size()) {
        std::cerr << "[ERROR] Invalid group_id " << group_id
                  << " (max: " << m_groups.size()-1 << ")" << std::endl;
        return 0; // 返回默认值
    }
    if (ring_pos >= m_groups[group_id].size()) {
        std::cerr << "[ERROR] Invalid ring_pos " << ring_pos
                  << " in group " << group_id
                  << " (max: " << m_groups[group_id].size()-1 << ")" << std::endl;
        return 0; // 返回默认值
    }
    return m_groups[group_id][ring_pos];
}

TreeNodeState& WorkloadTracker::GetTreeNodeState(uint32_t node_id) {
    auto it = m_tree_node_states.find(node_id);
    if (it == m_tree_node_states.end()) {
        std::cerr << "[ERROR] Tree node state not found for node " << node_id << std::endl;
        static TreeNodeState dummy_state;  // 返回空状态避免崩溃
        return dummy_state;
    }
    return it->second;
}

void WorkloadTracker::CheckGroupCompletionAndLogJct(uint32_t group_id)
{
    // 验证group_id有效性
    if (group_id >= m_groups.size()) {
        std::cerr << "[ERROR] Invalid group_id " << group_id
                  << " in CheckGroupCompletionAndLogJct" << std::endl;
        return;
    }

    bool is_group_complete = false;

    // 2. 根据当前的工作负载类型，使用不同的完成条件来判断
    switch (m_workload_type)
    {
        case WorkloadType::RingAllReduce:
            // 完成条件：组内所有节点都完成了它们的步骤
            if (group_id < m_nodes_finished_in_group.size() && group_id < m_groups.size()) {
                is_group_complete = (m_nodes_finished_in_group[group_id] == m_groups[group_id].size());
            } else {
                std::cerr << "[ERROR] Bounds check failed in RingAllReduce completion check" << std::endl;
            }
            break;

        case WorkloadType::AllToAll:
        case WorkloadType::AllToAllV:
            // 完成条件：组内的已完成流数量达到了该组所需的总流数
            if (group_id < m_completed_flows_in_group.size() && group_id < m_total_flows_per_group.size()) {
                is_group_complete = (m_completed_flows_in_group[group_id] == m_total_flows_per_group[group_id]);
            } else {
                std::cerr << "[ERROR] Bounds check failed in AllToAll completion check" << std::endl;
            }
            break;

        case WorkloadType::TreeAllReduce:
            // 完成条件：组内所有节点都完成了它们的阶段
            if (group_id < m_nodes_finished_in_group.size() && group_id < m_groups.size()) {
                is_group_complete = (m_nodes_finished_in_group[group_id] == m_groups[group_id].size());
            } else {
                std::cerr << "[ERROR] Bounds check failed in TreeAllReduce completion check" << std::endl;
            }
            break;

        default:
            // 对于未知类型，不执行任何操作
            break;
    }

    // 3. 如果组已完成，则记录JCT并更新标志位
    if (is_group_complete)
    {
        ns3::Time now = ns3::Simulator::Now();

        // 计算 round_start_time 与 JCT（单位：TimeStep）
        uint64_t round_start_time = m_round_start_time.GetTimeStep();
        uint64_t jct_time = (now - m_round_start_time).GetTimeStep();

        // 输出到JCT文件
        if (m_jct_output) {
            // 输出格式: round group round_start_time jct_time
            fprintf(m_jct_output, "%u %u %lu %lu\n",
                    m_current_round, group_id,
                    round_start_time, jct_time);

            fflush(m_jct_output); // 确保立即写入文件
        }

        // (可选) 输出到控制台
        // std::cout << "[Tracker] JCT LOGGED - Round: " << m_current_round
        //           << ", Group: " << group_id
        //           << ", StartTime: " << round_start_time
        //           << ", JCT(timestep): " << jct_time << std::endl;
    }
}

// Tree AllReduce 辅助函数实现
void WorkloadTracker::BuildBinaryTreeCommon(const std::vector<uint32_t>& group, uint32_t group_id, uint32_t num_chunks) {
    uint32_t n = group.size();
    if (n == 0) return;

    // 构建完全二叉树结构
    for (size_t i = 0; i < n; ++i) {
        TreeNodeState state;
        state.node_id = group[i];
        state.group_id = group_id;
        state.tree_index = i;
        state.message_size = m_message_size;

        // 计算父节点和子节点
        if (i == 0) {
            state.is_root = true;
            state.parent_id = group[i]; // 根节点的父节点是自己
        } else {
            state.is_root = false;
            uint32_t parent_index = (i - 1) / 2;
            state.parent_id = group[parent_index];
        }

        // 计算子节点
        uint32_t left_child_index = 2 * i + 1;
        uint32_t right_child_index = 2 * i + 2;

        if (left_child_index < n) {
            state.children_ids.push_back(group[left_child_index]);
        }
        if (right_child_index < n) {
            state.children_ids.push_back(group[right_child_index]);
        }

        // 计算树层级 (根为最高级)
        state.tree_level = 0;
        uint32_t temp_index = i;
        while (temp_index > 0) {
            temp_index = (temp_index - 1) / 2;
            state.tree_level++;
        }

        // 初始化分块状态 (如果需要)
        if (num_chunks > 1) {
            state.InitializeChunks(num_chunks);
        }

        m_tree_node_states[state.node_id] = state;
    }

    // 调试输出树结构
    std::cout << "[Tracker] Built binary tree for group " << group_id;
    if (num_chunks > 1) {
        std::cout << " with " << num_chunks << " chunks";
    }
    std::cout << ":" << std::endl;

    for (const auto& pair : m_tree_node_states) {
        if (pair.second.group_id == group_id) {
            const TreeNodeState& state = pair.second;
            std::cout << "  Node " << state.node_id
                      << " (level=" << state.tree_level
                      << ", parent=" << state.parent_id
                      << ", children=[";
            for (size_t i = 0; i < state.children_ids.size(); ++i) {
                if (i > 0) std::cout << ",";
                std::cout << state.children_ids[i];
            }
            std::cout << "], root=" << state.is_root << ")" << std::endl;
        }
    }
}

void WorkloadTracker::BuildBinaryTree(const std::vector<uint32_t>& group, uint32_t group_id) {
    BuildBinaryTreeCommon(group, group_id, 1);
}

void WorkloadTracker::TriggerTreeReduceForNode(uint32_t node_id) {
    TreeNodeState& state = m_tree_node_states.at(node_id);
    if (state.is_root || state.sent_to_parent) {
        return; // 根节点或已经发送过
    }

    ScheduleTreeNodeToParent(node_id, state.message_size,
                            m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
}

void WorkloadTracker::TriggerTreeBroadcastForNode(uint32_t node_id) {
    TreeNodeState& state = m_tree_node_states.at(node_id);
    if (state.children_ids.empty() || !state.received_from_parent) {
        return; // 叶子节点或还没从父节点接收到数据
    }

    for (uint32_t child_id : state.children_ids) {
        if (state.sent_to_children < state.children_ids.size()) {
            ScheduleTreeNodeToChild(node_id, child_id, state.message_size,
                                   m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
        }
    }
}

// 分块Tree AllReduce实现
void WorkloadTracker::BuildBinaryTreeChunked(const std::vector<uint32_t>& group, uint32_t group_id, uint32_t num_chunks) {
    BuildBinaryTreeCommon(group, group_id, num_chunks);
}

void WorkloadTracker::TriggerTreeChunkReduceForNode(uint32_t node_id, uint32_t chunk_id) {
    TreeNodeState& state = m_tree_node_states.at(node_id);
    if (chunk_id >= state.num_chunks) {
        std::cerr << "[ERROR] Invalid chunk_id " << chunk_id << " >= " << state.num_chunks << std::endl;
        return;
    }
    if (state.is_root || state.chunks_sent_to_parent[chunk_id]) {
        return; // 根节点或已经发送过这个chunk
    }

    ScheduleTreeChunkToParent(node_id, chunk_id, m_chunk_size,
                             m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
}

void WorkloadTracker::TriggerTreeChunkBroadcastForNode(uint32_t node_id, uint32_t chunk_id) {
    TreeNodeState& state = m_tree_node_states.at(node_id);
    if (chunk_id >= state.num_chunks) {
        std::cerr << "[ERROR] Invalid chunk_id " << chunk_id << " >= " << state.num_chunks << std::endl;
        return;
    }
    if (state.children_ids.empty() || !state.chunks_received_from_parent[chunk_id]) {
        return; // 叶子节点或还没从父节点接收到这个chunk
    }

    for (uint32_t child_id : state.children_ids) {
        if (state.chunks_sent_to_children[chunk_id] < state.children_ids.size()) {
            ScheduleTreeChunkToChild(node_id, child_id, chunk_id, m_chunk_size,
                                    m_all_nodes, m_server_addresses, m_sport_map, m_dport_map);
        }
    }
}

void WorkloadTracker::ProcessSimpleTreeAllReduceFlow(uint32_t src_id, uint32_t dst_id, TreeNodeState& src_state, TreeNodeState& dst_state) {
    // 判断这是reduce阶段还是broadcast阶段的流
    if (dst_state.parent_id == src_id) {
        // 这是child->parent的流 (reduce阶段)
        dst_state.received_from_children++;
        src_state.sent_to_parent = true;

        // 检查dst是否可以向其父节点发送
        if (dst_state.CanSendToParent()) {
            TriggerTreeReduceForNode(dst_id);
        }

        // 检查dst是否完成reduce阶段并且是根节点，如果是则开始broadcast
        if (dst_state.is_root && dst_state.received_from_children >= dst_state.children_ids.size()) {
            dst_state.reduce_phase_complete = true;
            dst_state.received_from_parent = true; // 根节点设为已从"父节点"接收

            // 如果根节点没有子节点（单节点组），直接标记为完成
            if (dst_state.children_ids.empty()) {
                dst_state.broadcast_phase_complete = true;
                uint32_t group_id = dst_state.group_id;
                if (group_id < m_nodes_finished_in_group.size()) {
                    m_nodes_finished_in_group[group_id]++;
                    CheckGroupCompletionAndLogJct(group_id);
                } else {
                    std::cerr << "[ERROR] Invalid group_id " << group_id
                              << " in Simple Tree AllReduce root completion" << std::endl;
                }
            } else {
                TriggerTreeBroadcastForNode(dst_id);
            }
        }
    } else if (src_state.parent_id == dst_id) {
        // 这是parent->child的流 (broadcast阶段)
        src_state.sent_to_children++;
        dst_state.received_from_parent = true;

        // 检查dst是否可以向其子节点发送
        if (dst_state.CanSendToChildren()) {
            TriggerTreeBroadcastForNode(dst_id);
        }

        // 检查dst是否完成broadcast阶段
        if (dst_state.sent_to_children >= dst_state.children_ids.size() && !dst_state.broadcast_phase_complete) {
            dst_state.broadcast_phase_complete = true;

            // 所有节点（包括叶子节点和内部节点）完成broadcast阶段后都标记为完成
            uint32_t group_id = dst_state.group_id;
            if (group_id < m_nodes_finished_in_group.size()) {
                m_nodes_finished_in_group[group_id]++;
                CheckGroupCompletionAndLogJct(group_id);
            } else {
                std::cerr << "[ERROR] Invalid group_id " << group_id
                          << " in Simple Tree AllReduce completion" << std::endl;
            }
        }
    }
}

void WorkloadTracker::ProcessChunkedTreeAllReduceFlow(uint32_t src_id, uint32_t dst_id, ns3::Ptr<ns3::RdmaQueuePair> qp, TreeNodeState& src_state, TreeNodeState& dst_state) {
    if (m_tree_num_chunks == 0) {
        std::cerr << "[ERROR] Tree num chunks is zero in ProcessChunkedTreeAllReduceFlow" << std::endl;
        return;
    }

    // 从端口解码chunk ID，避免乱序完成问题
    // 编码规则：encoded_port = base_port + chunk_id * 1000
    uint16_t sport = qp->sport;
    uint32_t chunk_id = 0;

    if (sport >= 1000) {
        // 解码：chunk_id = (port - base_port) / 1000
        // 简化版本：直接用 sport / 1000 来获取chunk_id（假设base_port < 1000）
        chunk_id = (sport / 1000) % m_tree_num_chunks;
    } else {
        chunk_id = 0;  // 兜底：如果没有编码信息，假设是chunk 0
    }

    std::cout << "[Debug] Decoded chunk_id " << chunk_id << " from sport " << sport
              << " for flow " << src_id << "->" << dst_id << std::endl;

    // 验证chunk_id有效性
    if (chunk_id >= dst_state.num_chunks || chunk_id >= src_state.num_chunks) {
        std::cerr << "[ERROR] Invalid chunk_id " << chunk_id
                  << " (max: " << dst_state.num_chunks-1 << ")" << std::endl;
        return;
    }

    // 判断这是reduce阶段还是broadcast阶段的流
    if (dst_state.parent_id == src_id) {
        // 这是child->parent的流 (reduce阶段)
        if (chunk_id < dst_state.chunks_received_from_children.size()) {
            dst_state.chunks_received_from_children[chunk_id]++;
        } else {
            std::cerr << "[ERROR] Chunk array bounds check failed for chunk_id " << chunk_id << std::endl;
            return;
        }

        // 检查是否可以发送下一个chunk
        for (uint32_t next_chunk = 0; next_chunk < m_tree_num_chunks; ++next_chunk) {
            if (dst_state.CanSendChunkToParent(next_chunk)) {
                TriggerTreeChunkReduceForNode(dst_id, next_chunk);
            }
        }

        // 检查dst是否是根节点且完成了某个chunk的reduce，如果是则开始该chunk的broadcast
        if (dst_state.is_root && dst_state.chunks_received_from_children[chunk_id] >= dst_state.children_ids.size()) {
            dst_state.chunks_received_from_parent[chunk_id] = true; // 根节点标记为已接收
            TriggerTreeChunkBroadcastForNode(dst_id, chunk_id);
        }

    } else if (src_state.parent_id == dst_id) {
        // 这是parent->child的流 (broadcast阶段)
        dst_state.chunks_received_from_parent[chunk_id] = true;

        // 检查是否可以发送这个chunk到子节点
        if (dst_state.CanSendChunkToChildren(chunk_id)) {
            TriggerTreeChunkBroadcastForNode(dst_id, chunk_id);
        }

        // 检查节点是否完成整个allreduce
        if (dst_state.IsBroadcastPhaseComplete() && !dst_state.broadcast_phase_complete) {
            dst_state.broadcast_phase_complete = true;  // 标记为已完成，避免重复计数
            uint32_t group_id = dst_state.group_id;
            if (group_id < m_nodes_finished_in_group.size()) {
                m_nodes_finished_in_group[group_id]++;
                CheckGroupCompletionAndLogJct(group_id);
            } else {
                std::cerr << "[ERROR] Invalid group_id " << group_id
                          << " in Tree AllReduce completion" << std::endl;
            }
        }
    }
}