#ifndef SWITCH_NODE_H
#define SWITCH_NODE_H

#include <ns3/node.h>
#include <ns3/random-variable-stream.h>

#include <unordered_map>
#include <unordered_set>
#include <map>
#include <tuple>

#include "qbb-net-device.h"
#include "switch-mmu.h"

namespace ns3 {

class Packet;

struct PfcPauseEventInfo {
    uint32_t nodeId;                    // 發生 PFC Pause 的交換機節點 ID
    uint32_t switchType;                // 交換機類型 (ToR=1, Spine=2, Core=3)
    uint32_t triggeringInDev;           // 觸發 PFC 的 Ingress Port ID
    uint32_t congestedEgDev;            // 當前最擁塞的 Egress Port ID
    size_t incastFlowCount;             // 最擁塞 Egress 佇列中的總 Flow 數量
    size_t uniqueSrcIpCount;            // 最擁塞 Egress 佇列中獨立的 Source IP 數量
    uint32_t maxQueueLength;            // 最擁塞 Egress 佇列的長度 (Bytes)
};

struct DropEventInfo {
    uint32_t nodeId;                    // 發生丟包的交換機節點 ID
    uint32_t deviceId;                  // 發生擁塞的埠 ID (Ingress 或 Egress)
    uint32_t switchType;
    bool isIngressDrop;                 // 標記是 Ingress 丟包 (true) 還是 Egress 丟包 (false)
    size_t incastFlowCount;             // 擁塞佇列中的總 Flow 數量
    size_t uniqueSrcIpCount;            // 擁塞佇列中獨立的 Source IP 數量
    CustomHeader droppedPacketHeader;   // 被丟棄封包的頭部資訊
};


struct FlowIdentifier {
    uint32_t srcIp;
    uint32_t dstIp;
    uint16_t srcPort;
    uint16_t dstPort;
    uint8_t protocol;

    // 为了能作为 std::map 的键，需要重载 operator<
    bool operator<(const FlowIdentifier& other) const {
        return std::tie(srcIp, dstIp, srcPort, dstPort, protocol) <
               std::tie(other.srcIp, other.dstIp, other.srcPort, other.dstPort, other.protocol);
    }
};


class SwitchNode : public Node {
    static const unsigned qCnt = 8;    // Number of queues/priorities used
    static const unsigned pCnt = 129;  // port 0 is not used so + 1	// Number of ports used
    uint32_t m_ecmpSeed;
    std::unordered_map<uint32_t, std::vector<int> >
        m_rtTable;  // map from ip address (u32) to possible ECMP port (index of dev)

    // monitor uplinks
    uint64_t m_txBytes[pCnt];  // counter of tx bytes, for HPCC

   protected:
    bool m_ecnEnabled;
    uint32_t m_ccMode;
    uint32_t m_ackHighPrio;  // set high priority for ACK/NACK

   private:
    int GetOutDev(Ptr<Packet>, CustomHeader &ch);
    void SendToDev(Ptr<Packet> p, CustomHeader &ch);
    void SendToDevContinue(Ptr<Packet> p, CustomHeader &ch);
    static uint32_t EcmpHash(const uint8_t *key, size_t len, uint32_t seed);
    void CheckAndSendPfc(uint32_t inDev, uint32_t qIndex);
    void CheckAndSendResume(uint32_t inDev, uint32_t qIndex);

    /* Sending packet to Egress port */
    void DoSwitchSend(Ptr<Packet> p, CustomHeader &ch, uint32_t outDev, uint32_t qIndex);

    /*----- Load balancer -----*/
    // Flow ECMP (lb_mode = 0)
    uint32_t DoLbFlowECMP(Ptr<const Packet> p, const CustomHeader &ch,
                          const std::vector<int> &nexthops);
    // Per-Lane ECMP (for per-lane DCQCN mode)
    uint32_t DoLbPerLaneECMP(Ptr<const Packet> p, const CustomHeader &ch,
                             const std::vector<int> &nexthops);
    // DRILL (lb_mode = 2)
    uint32_t DoLbDrill(Ptr<const Packet> p, const CustomHeader &ch,
                       const std::vector<int> &nexthops);     // choose egress port
    uint32_t m_drill_candidate;                               // always 2 (power of two)
    std::map<uint64_t, uint32_t> m_previousBestInterfaceMap;  // <stateKey, previousBestInterface>
    std::map<uint64_t, uint32_t> m_previousBestGroupedInterfaceMap;  // <(dip,group), previousBestInterface>
    uint32_t CalculateInterfaceLoad(uint32_t interface);      // Get the load of a interface
    // Conga (lb_mode = 3)
    uint32_t DoLbConga(Ptr<Packet> p, CustomHeader &ch, const std::vector<int> &nexthops);
    // Conga (lb_mode = 6)
    uint32_t DoLbLetflow(Ptr<Packet> p, CustomHeader &ch, const std::vector<int> &nexthops);
    // ConWeave (lb_mode = 9)
    uint32_t DoLbConWeave(Ptr<const Packet> p, const CustomHeader &ch,
                           const std::vector<int> &nexthops);  // dummy
    // Random Packet Spraying (lb_mode = 1)
    uint32_t DoLbRandomSpray(Ptr<const Packet> p, const CustomHeader &ch,
                               const std::vector<int> &nexthops);

    // Adaptive Routing Packet Spraying (lb_mode = ?)
    uint32_t DoLbAdaptiveSpray(Ptr<const Packet> p, const CustomHeader &ch,
                                               const std::vector<int> &nexthops);
    
    uint32_t DoLbWeightRandomSpray(Ptr<const Packet> p, const CustomHeader &ch,
                                               const std::vector<int> &nexthops);

    uint32_t DoLbSglb(Ptr<const Packet> p, const CustomHeader &ch,
                      const std::vector<int> &nexthops);

    // DRILL-style: WCMP between groups + packet spraying within the chosen group
    uint32_t DoLbDrillWeight(Ptr<const Packet> p, const CustomHeader &ch,
                                               const std::vector<int> &nexthops);
    uint32_t SelectRandomNextHop(const std::vector<int> &nexthops);
    uint32_t SelectDrillNextHop(const std::vector<int> &nexthops, uint64_t stateKey,
                                std::map<uint64_t, uint32_t> &previousBestInterfaceMap);

    /*-----------Packet Trimming--------------*/
    uint32_t GetTotalHeaderSize(Ptr<const Packet> packet) const;

    /*----------- Incast Statistics --------------*/
    // Ingress port stats: <inPort, <FlowID, packet_count>>
    std::map<uint32_t, std::map<FlowIdentifier, uint32_t>> m_ingressFlowStats;
    // Ingress port stats: <inPort, <SrcIP, packet_count>>
    std::map<uint32_t, std::map<uint32_t, uint32_t>> m_ingressSrcIpStats;

    // Egress port stats: <outPort, <FlowID, packet_count>>
    std::map<uint32_t, std::map<FlowIdentifier, uint32_t>> m_egressFlowStats;
    // Egress port stats: <outPort, <SrcIP, packet_count>>
    std::map<uint32_t, std::map<uint32_t, uint32_t>> m_egressSrcIpStats;

    // 从 CustomHeader 创建 FlowIdentifier 的辅助函数
    FlowIdentifier GetFlowId(const CustomHeader& ch) const;
    // 入队时更新统计数据
    void UpdateQueueStatsOnEnqueue(uint32_t inDev, uint32_t outDev, const CustomHeader& ch);
    // 出队时更新统计数据
    void UpdateQueueStatsOnDequeue(uint32_t inDev, uint32_t outDev, const CustomHeader& ch);
    // 丢包时记录拥塞状态
    void LogCongestionStateOnDrop(uint32_t inDev, uint32_t outDev, bool isIngressDrop, const CustomHeader& ch);

    DropEventInfo CreateDropEventInfo(const CustomHeader& ch, bool isIngressAdmitted, uint32_t inDev, uint32_t outDev) const;

    PfcPauseEventInfo m_pendingPfcEvent; // 儲存正在追蹤的事件的峰值狀態
    bool m_isPfcEventPending;            // 標記當前是否有正在追蹤的事件
    EventId m_flushEvent;                // 用於管理和取消計劃中的刷新事件
    Ptr<UniformRandomVariable> m_lbRandom;
    void FlushPfcTrace(); 
    void AnalyzeAndTracePfcCongestion(uint32_t triggeringInDev);

   public:
    // Ptr<BroadcomNode> m_broadcom;
    Ptr<SwitchMmu> m_mmu;
    bool m_isToR;                                 // true if ToR switch
    bool m_isSpine;                               // true if Spine switch
    bool m_isCore;                                // true if Core switch
    std::unordered_set<uint32_t> m_isToR_hostIP;  // host's IP connected to this ToR

    static TypeId GetTypeId(void);
    SwitchNode();
    void SetEcmpSeed(uint32_t seed);
    void AddTableEntry(Ipv4Address &dstAddr, uint32_t intf_idx);
    void ClearTable();
    bool SwitchReceiveFromDevice(Ptr<NetDevice> device, Ptr<Packet> packet, CustomHeader &ch);
    void SwitchNotifyDequeue(uint32_t ifIndex, uint32_t qIndex, Ptr<Packet> p);
    uint64_t GetTxBytesOutDev(uint32_t outdev);

    // packet trimming
    bool m_packetTrimming;

    // ideal drop notify
    bool m_idealLossRecovery; 

    // trace
    TracedCallback<const DropEventInfo &> m_tracePacketDrop;  // trace source for packet drop

    TracedCallback<const PfcPauseEventInfo &> m_tracePfcPause;  // trace source for PFC pause event
};

} /* namespace ns3 */

#endif /* SWITCH_NODE_H */
