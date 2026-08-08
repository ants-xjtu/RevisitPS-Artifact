#ifndef AI_WORKLOAD_TRACKER_H
#define AI_WORKLOAD_TRACKER_H

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/rdma-queue-pair.h"
#include <string>
#include <vector>
#include <map>
#include <unordered_map>
#include <cstdio>

// Hash function for std::pair
namespace std {
    template<>
    struct hash<std::pair<uint32_t, uint32_t>> {
        size_t operator()(const std::pair<uint32_t, uint32_t>& p) const {
            return std::hash<uint32_t>()(p.first) ^ (std::hash<uint32_t>()(p.second) << 1);
        }
    };
}

enum class WorkloadType {
    RingAllReduce,
    AllToAll,
    AllToAllV,
    TreeAllReduce,
    TreeAllReduceChunked,
    Unknown
};

// 拓扑到其固有配置的映射
struct TopoConfig {
    uint32_t num_groups;
    uint32_t servers_per_leaf;
};

// 追踪单个节点在 Ring All-Reduce 中的状态
struct NodeState {
    uint32_t node_id;
    uint32_t group_id;
    uint32_t ring_pos; // 在环中的位置 (0, 1, 2...)
    uint32_t num_nodes_in_ring;
    uint64_t message_size;

    uint32_t current_step; // 当前正在执行的步骤 (0 to N-2)
    uint32_t finished_steps;
    bool sending_current_step;
    uint32_t need_to_send_datas;
    bool round_completed;

    NodeState() : current_step(0), finished_steps(0), sending_current_step(false), need_to_send_datas(0){}

    bool IsReadyForNextStep() const {
        return !sending_current_step && (need_to_send_datas > 0);
    }
};

// 追踪单个节点在 Tree All-Reduce 中的状态
struct TreeNodeState {
    uint32_t node_id;
    uint32_t group_id;
    uint32_t tree_level; // 在树中的层级 (0=叶子, max=根)
    uint32_t tree_index; // 在当前层级中的索引
    uint32_t parent_id;  // 父节点ID (根节点为自身)
    std::vector<uint32_t> children_ids; // 子节点ID列表
    uint64_t message_size;
    uint32_t num_chunks; // 总chunk数量

    bool is_root;
    bool reduce_phase_complete;    // reduce阶段完成 (叶子->根)
    bool broadcast_phase_complete; // broadcast阶段完成 (根->叶子)

    // Simple Tree AllReduce状态 (非分块模式)
    uint32_t received_from_children; // 从子节点接收到的消息数量
    bool sent_to_parent;            // 是否已发送给父节点
    bool received_from_parent;      // 是否从父节点接收到消息
    uint32_t sent_to_children;      // 发送给子节点的消息数量

    // Chunked pipeline状态
    std::vector<uint32_t> chunks_received_from_children; // 每个chunk从多少子节点收到
    std::vector<bool> chunks_sent_to_parent;            // 每个chunk是否已发送给父节点
    std::vector<bool> chunks_received_from_parent;      // 每个chunk是否从父节点收到
    std::vector<uint32_t> chunks_sent_to_children;      // 每个chunk发送给多少子节点

    TreeNodeState() : tree_level(0), tree_index(0), parent_id(0), is_root(false),
                     reduce_phase_complete(false), broadcast_phase_complete(false),
                     received_from_children(0), sent_to_parent(false),
                     received_from_parent(false), sent_to_children(0),
                     num_chunks(1) {}

    void InitializeChunks(uint32_t chunk_count) {
        num_chunks = chunk_count;
        chunks_received_from_children.resize(chunk_count, 0);
        chunks_sent_to_parent.resize(chunk_count, false);
        chunks_received_from_parent.resize(chunk_count, false);
        chunks_sent_to_children.resize(chunk_count, 0);
    }

    bool CanSendChunkToParent(uint32_t chunk_id) const {
        return !is_root && !chunks_sent_to_parent[chunk_id] &&
               (chunks_received_from_children[chunk_id] >= children_ids.size());
    }

    bool CanSendChunkToChildren(uint32_t chunk_id) const {
        return chunks_received_from_parent[chunk_id] &&
               (chunks_sent_to_children[chunk_id] < children_ids.size());
    }

    // Simple Tree AllReduce helper methods
    bool CanSendToParent() const {
        return !is_root && !sent_to_parent && (received_from_children >= children_ids.size());
    }

    bool CanSendToChildren() const {
        return received_from_parent && (sent_to_children < children_ids.size());
    }

    bool IsReducePhaseComplete() const {
        for (uint32_t i = 0; i < num_chunks; ++i) {
            if (is_root) {
                if (chunks_received_from_children[i] < children_ids.size()) return false;
            } else {
                if (!chunks_sent_to_parent[i]) return false;
            }
        }
        return true;
    }

    bool IsBroadcastPhaseComplete() const {
        for (uint32_t i = 0; i < num_chunks; ++i) {
            if (children_ids.empty()) {
                if (!chunks_received_from_parent[i]) return false;
            } else {
                if (chunks_sent_to_children[i] < children_ids.size()) return false;
            }
        }
        return true;
    }
};

class WorkloadTracker {
public:
    // 获取单例实例
    static WorkloadTracker& GetInstance();

    // 禁止拷贝和赋值
    WorkloadTracker(const WorkloadTracker&) = delete;
    void operator=(const WorkloadTracker&) = delete;

    // 析构函数 - 清理资源
    ~WorkloadTracker();

    void SetSimulationContext(
        const ns3::NodeContainer& all_nodes,
        const std::vector<ns3::Ipv4Address>& addresses,
        const std::unordered_map<uint32_t, uint16_t>& sport_map,
        const std::unordered_map<uint32_t, uint16_t>& dport_map,
        uint32_t win,
        uint64_t rtt);

    // 初始化
    void Initialize(WorkloadType type, uint32_t total_rounds, const std::vector<std::vector<uint32_t>>& groups, uint64_t msg_size);

    // 初始化AllToAllV (支持变长消息)
    void InitializeAllToAllV(uint32_t total_rounds, const std::vector<std::vector<uint32_t>>& groups,
                            const std::vector<std::vector<uint64_t>>& message_sizes);

    // 初始化分块Tree AllReduce
    void InitializeTreeAllReduceChunked(uint32_t total_rounds, const std::vector<std::vector<uint32_t>>& groups,
                                       uint64_t msg_size, uint32_t num_chunks);

    // 启动第一轮
    void StartFirstRound();

    // 重置tracker状态，用于新的实验
    void Reset();

    // 从 qp_finish 调用
    void OnFlowComplete(ns3::Ptr<ns3::RdmaQueuePair> qp);
    
    // 公共的 getter 函数，供调度器使用
    NodeState& GetNodeState(uint32_t node_id);
    TreeNodeState& GetTreeNodeState(uint32_t node_id);
    uint32_t GetNodeAt(uint32_t group_id, uint32_t ring_pos) const;
    const std::vector<std::vector<uint32_t>>& GetGroups() const { return m_groups; }

    uint32_t GetWindow(){ return m_window; }
    uint32_t GetRtt(){ return m_rtt; }

    void SetJctOutputFile(const std::string& filename) {
        if (m_jct_output) {
            fclose(m_jct_output);
        }
        m_jct_output_file = filename;
        m_jct_output = fopen(m_jct_output_file.c_str(), "w");
        if (!m_jct_output) {
            NS_LOG_ERROR("无法打开 JCT 输出文件: " << m_jct_output_file);
        }
    }

    FILE* GetJctOutputHandle() const { return m_jct_output; }
    void CheckGroupCompletionAndLogJct(uint32_t group_id);

private:
    // 私有构造函数
    WorkloadTracker() : m_initialized(false), m_current_round(0) {}

    void ScheduleNextRound();
    void TriggerNextStepForNode(uint32_t node_id);
    void CheckRoundCompletion();

    // Tree AllReduce 辅助函数
    void BuildBinaryTree(const std::vector<uint32_t>& group, uint32_t group_id);
    void BuildBinaryTreeChunked(const std::vector<uint32_t>& group, uint32_t group_id, uint32_t num_chunks);

private:
    // 公共的二叉树构建逻辑
    void BuildBinaryTreeCommon(const std::vector<uint32_t>& group, uint32_t group_id, uint32_t num_chunks);

public:
    void TriggerTreeReduceForNode(uint32_t node_id);
    void TriggerTreeBroadcastForNode(uint32_t node_id);
    void TriggerTreeChunkReduceForNode(uint32_t node_id, uint32_t chunk_id);
    void TriggerTreeChunkBroadcastForNode(uint32_t node_id, uint32_t chunk_id);
    void ProcessSimpleTreeAllReduceFlow(uint32_t src_id, uint32_t dst_id, TreeNodeState& src_state, TreeNodeState& dst_state);
    void ProcessChunkedTreeAllReduceFlow(uint32_t src_id, uint32_t dst_id, ns3::Ptr<ns3::RdmaQueuePair> qp, TreeNodeState& src_state, TreeNodeState& dst_state);

    // 成员变量
    bool m_initialized;
    WorkloadType m_workload_type = WorkloadType::Unknown;
    uint32_t m_current_round;
    uint32_t m_total_rounds;
    uint64_t m_message_size; // 用于All-to-All或Ring All-Reduce的切片大小
    std::vector<std::vector<uint64_t>> m_variable_message_sizes; // AllToAllV的变长消息大小矩阵
    uint32_t m_tree_num_chunks; // Tree AllReduce的分块数量
    uint64_t m_chunk_size; // 每个chunk的大小

    std::unordered_map<uint32_t, NodeState> m_node_states;
    std::unordered_map<uint32_t, TreeNodeState> m_tree_node_states;
    std::vector<std::vector<uint32_t>> m_groups;

    // 追踪变量
    uint32_t m_completed_flows_this_round;
    uint32_t m_total_flows_per_round;
    uint32_t m_nodes_finished_round;

     // 存储对象而非指针
    ns3::NodeContainer m_all_nodes;
    std::vector<ns3::Ipv4Address> m_server_addresses;
    std::unordered_map<uint32_t, uint16_t> m_sport_map;
    std::unordered_map<uint32_t, uint16_t> m_dport_map;
    uint32_t m_window;
    uint64_t m_rtt;

    std::unordered_map<uint32_t, uint32_t> m_node_to_group_map;     // 节点ID到组ID的映射
    std::vector<uint32_t> m_completed_flows_in_group; // [AllToAll] 按组追踪完成的流数量
    std::vector<uint32_t> m_total_flows_per_group;    // [AllToAll] 每组AllToAll所需的总流数
    
    ns3::Time m_round_start_time; // 记录每轮的开始时间
    std::vector<uint32_t> m_nodes_finished_in_group; // 按组追踪完成的节点数
    std::string m_jct_output_file;
    FILE* m_jct_output;

    // 注：chunk ID现在从端口编码中解码，不再需要流计数器
};

#endif // AI_WORKLOAD_TRACKER_H