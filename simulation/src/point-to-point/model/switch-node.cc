#include "switch-node.h"

#include "assert.h"
#include "ns3/boolean.h"
#include "ns3/conweave-routing.h"
#include "ns3/double.h"
#include "ns3/flow-id-tag.h"
#include "ns3/lane-id-tag.h"
#include "ns3/int-header.h"
#include "ns3/ipv4-header.h"
#include "ns3/ipv4.h"
#include "ns3/letflow-routing.h"
#include "ns3/packet.h"
#include "ns3/pause-header.h"
#include "ns3/settings.h"
#include "ns3/uinteger.h"
#include "ppp-header.h"
#include "qbb-net-device.h"

#include "ns3/packet.h"
#include "ns3/ppp-header.h"
#include "ns3/ipv4-header.h"
#include "ns3/tcp-header.h"
#include "ns3/udp-header.h"

#include <iostream>
#include <iomanip>
#include <algorithm>


namespace ns3 {

namespace {
struct SglbCandidate {
    uint32_t outPort;
    uint32_t score;
    double weight;
};
}  // namespace

TypeId SwitchNode::GetTypeId(void) {
    static TypeId tid =
        TypeId("ns3::SwitchNode")
            .SetParent<Node>()
            .AddConstructor<SwitchNode>()
            .AddAttribute("EcnEnabled", "Enable ECN marking.", BooleanValue(false),
                          MakeBooleanAccessor(&SwitchNode::m_ecnEnabled), MakeBooleanChecker())
            .AddAttribute("CcMode", "CC mode.", UintegerValue(0),
                          MakeUintegerAccessor(&SwitchNode::m_ccMode),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("AckHighPrio", "Set high priority for ACK/NACK or not", UintegerValue(0),
                          MakeUintegerAccessor(&SwitchNode::m_ackHighPrio),
                          MakeUintegerChecker<uint32_t>())
            /*modification begin*/
            .AddAttribute("PacketTrimming", "Enable packet trimming on congestion instead of dropping.", BooleanValue(false),
                          MakeBooleanAccessor(&SwitchNode::m_packetTrimming),
                          MakeBooleanChecker())
            .AddAttribute("IdealLossRecovery", "Enable switch to ideal notify the packet drop.", BooleanValue(false),
                          MakeBooleanAccessor(&SwitchNode::m_idealLossRecovery),
                          MakeBooleanChecker())
            /*modification end*/
            .AddTraceSource("SwitchDropPacket", "Trace source to indicate a packet is dropped by switch",
                        MakeTraceSourceAccessor(&SwitchNode::m_tracePacketDrop))
            .AddTraceSource("SwitchPfcPause", "Trace source to indicate a PFC pause is sent due to congestion",
                        MakeTraceSourceAccessor(&SwitchNode::m_tracePfcPause));
    return tid;
}

SwitchNode::SwitchNode() {
    m_ecmpSeed = m_id;
    m_isToR = false;
    m_node_type = 1;
    m_isToR = false;
    m_isSpine = false;
    m_isCore = false;
    m_drill_candidate = 2;
    m_mmu = CreateObject<SwitchMmu>();
    // Conga's Callback for switch functions
    m_mmu->m_congaRouting.SetSwitchSendCallback(MakeCallback(&SwitchNode::DoSwitchSend, this));
    m_mmu->m_congaRouting.SetSwitchSendToDevCallback(
        MakeCallback(&SwitchNode::SendToDevContinue, this));
    // ConWeave's Callback for switch functions
    m_mmu->m_conweaveRouting.SetSwitchSendCallback(MakeCallback(&SwitchNode::DoSwitchSend, this));
    m_mmu->m_conweaveRouting.SetSwitchSendToDevCallback(
        MakeCallback(&SwitchNode::SendToDevContinue, this));

    for (uint32_t i = 0; i < pCnt; i++) {
        m_txBytes[i] = 0;
    }

    m_isPfcEventPending = false;
    m_flushEvent = EventId();
    m_lbRandom = CreateObject<UniformRandomVariable>();
}

/**
 * @brief Load Balancing
 */
uint32_t SwitchNode::DoLbFlowECMP(Ptr<const Packet> p, const CustomHeader &ch,
                                  const std::vector<int> &nexthops) {
    // pick one next hop based on hash
    union {
        uint8_t u8[4 + 4 + 2 + 2];
        uint32_t u32[3];
    } buf;
    buf.u32[0] = ch.sip;
    buf.u32[1] = ch.dip;
    if (ch.l3Prot == 0x6)
        buf.u32[2] = ch.tcp.sport | ((uint32_t)ch.tcp.dport << 16);
    else if (ch.l3Prot == 0x11)  // XXX RDMA traffic on UDP
        buf.u32[2] = ch.udp.sport | ((uint32_t)ch.udp.dport << 16);
    else if (ch.l3Prot == 0xFC || ch.l3Prot == 0xFD)  // ACK or NACK
        buf.u32[2] = ch.ack.sport | ((uint32_t)ch.ack.dport << 16);
    else {
        std::cout << "[ERROR] Sw(" << m_id << ")," << PARSE_FIVE_TUPLE(ch)
                  << "Cannot support other protoocls than TCP/UDP (l3Prot:" << ch.l3Prot << ")"
                  << std::endl;
        assert(false && "Cannot support other protoocls than TCP/UDP");
    }

    uint32_t hashVal = EcmpHash(buf.u8, 12, m_ecmpSeed);
    uint32_t idx = hashVal % nexthops.size();
    return nexthops[idx];
}

/**
 * @brief Per-Lane ECMP for per-lane DCQCN mode
 *
 * This function uses lane ID instead of port numbers for ECMP hashing.
 * All flows in the same lane will follow the same path, while different
 * lanes can take different paths for load balancing.
 */
uint32_t SwitchNode::DoLbPerLaneECMP(Ptr<const Packet> p, const CustomHeader &ch,
                                      const std::vector<int> &nexthops) {
    // Try to read LaneIdTag from the packet
    LaneIdTag laneTag;
    bool hasLaneTag = p->PeekPacketTag(laneTag);

    union {
        uint8_t u8[4 + 4 + 4];  // sip + dip + lane_id
        uint32_t u32[3];
    } buf;

    buf.u32[0] = ch.sip;
    buf.u32[1] = ch.dip;

    if (hasLaneTag) {
        // Use lane_id for hashing (same lane -> same path)
        buf.u32[2] = laneTag.GetLaneId();
    } else {
        // Fallback to regular flow ECMP if no lane tag
        // This handles ACK/NACK and other control packets
        if (ch.l3Prot == 0x11)  // UDP
            buf.u32[2] = ch.udp.sport | ((uint32_t)ch.udp.dport << 16);
        else if (ch.l3Prot == 0xFC || ch.l3Prot == 0xFD)  // ACK or NACK
            buf.u32[2] = ch.ack.sport | ((uint32_t)ch.ack.dport << 16);
        else
            buf.u32[2] = 0;
    }

    uint32_t hashVal = EcmpHash(buf.u8, 12, m_ecmpSeed);
    uint32_t idx = hashVal % nexthops.size();

    // // Debug output with detailed information
    // std::cout << "[SwitchNode::DoLbPerLaneECMP] Switch: " << m_id
    //           << ", SIP: " << ch.sip << ", DIP: " << ch.dip
    //           << ", HasLaneTag: " << (hasLaneTag ? "Yes" : "No");
    // if (hasLaneTag) {
    //     std::cout << ", LaneID: " << laneTag.GetLaneId();
    // }
    // std::cout << ", HashVal: " << hashVal
    //           << ", NumNextHops: " << nexthops.size()
    //           << " -> NextHopIdx: " << idx << std::endl;

    return nexthops[idx];
}

/*-----------------CONGA-----------------*/
uint32_t SwitchNode::DoLbConga(Ptr<Packet> p, CustomHeader &ch, const std::vector<int> &nexthops) {
    return DoLbFlowECMP(p, ch, nexthops);  // flow ECMP (dummy)
}

/*-----------------Letflow-----------------*/
uint32_t SwitchNode::DoLbLetflow(Ptr<Packet> p, CustomHeader &ch,
                                 const std::vector<int> &nexthops) {
    if (m_isToR && nexthops.size() == 1) {
        if (m_isToR_hostIP.find(ch.sip) != m_isToR_hostIP.end() &&
            m_isToR_hostIP.find(ch.dip) != m_isToR_hostIP.end()) {
            return nexthops[0];  // intra-pod traffic
        }
    }

    /* ONLY called for inter-Pod traffic */
    uint32_t outPort = m_mmu->m_letflowRouting.RouteInput(p, ch);
    if (outPort == LETFLOW_NULL) {
        assert(nexthops.size() == 1);  // Receiver's TOR has only one interface to receiver-server
        outPort = nexthops[0];         // has only one option
    }
    assert(std::find(nexthops.begin(), nexthops.end(), outPort) !=
           nexthops.end());  // Result of Letflow cannot be found in nexthops
    return outPort;
}

/*-----------------DRILL-----------------*/
uint32_t SwitchNode::CalculateInterfaceLoad(uint32_t interface) {
    Ptr<QbbNetDevice> device = DynamicCast<QbbNetDevice>(m_devices[interface]);
    NS_ASSERT_MSG(!!device && !!device->GetQueue(),
                  "Error of getting a egress queue for calculating interface load");
    return device->GetQueue()->GetNBytesTotal();  // also used in HPCC
}

uint32_t SwitchNode::DoLbDrill(Ptr<const Packet> p, const CustomHeader &ch,
                               const std::vector<int> &nexthops) {
    return SelectDrillNextHop(nexthops, ch.dip, m_previousBestInterfaceMap);
}

/*--------------------Random packet spraying------------------------*/
uint32_t SwitchNode::DoLbRandomSpray(Ptr<const Packet> p, const CustomHeader &ch,
                                     const std::vector<int> &nexthops)
{
    // Precondition: Ensure the list of next hops is not empty.
    // In a real scenario (like ns-3), you might use an assertion: NS_ASSERT(!nexthops.empty());
    if (nexthops.empty())
    {
        // If there are no next hops, there's nowhere to send the packet.
        // Return a sentinel value (e.g., 0 or -1) to indicate an error.
        return 0;
    }

    return SelectRandomNextHop(nexthops);
}

uint32_t SwitchNode::SelectRandomNextHop(const std::vector<int> &nexthops) {
    if (nexthops.empty()) {
        return 0;
    }
    if (nexthops.size() == 1) {
        return nexthops[0];
    }

    uint32_t randomIndex = m_lbRandom->GetInteger(0, nexthops.size() - 1);
    return nexthops[randomIndex];
}

uint32_t SwitchNode::SelectDrillNextHop(const std::vector<int> &nexthops, uint64_t stateKey,
                                        std::map<uint64_t, uint32_t> &previousBestInterfaceMap) {
    if (nexthops.empty()) {
        return 0;
    }
    if (nexthops.size() == 1) {
        return nexthops[0];
    }

    uint32_t leastLoadInterface = 0;
    uint32_t leastLoad = std::numeric_limits<uint32_t>::max();
    std::vector<int> rand_nexthops = nexthops;
    std::random_shuffle(rand_nexthops.begin(), rand_nexthops.end());

    std::map<uint64_t, uint32_t>::iterator itr = previousBestInterfaceMap.find(stateKey);
    if (itr != previousBestInterfaceMap.end()) {
        leastLoadInterface = itr->second;
        leastLoad = CalculateInterfaceLoad(itr->second);
    }

    uint32_t sampleNum =
        m_drill_candidate < rand_nexthops.size() ? m_drill_candidate : rand_nexthops.size();
    for (uint32_t samplePort = 0; samplePort < sampleNum; samplePort++) {
        uint32_t sampleLoad = CalculateInterfaceLoad(rand_nexthops[samplePort]);
        if (sampleLoad < leastLoad) {
            leastLoad = sampleLoad;
            leastLoadInterface = rand_nexthops[samplePort];
        }
    }
    previousBestInterfaceMap[stateKey] = leastLoadInterface;
    return leastLoadInterface;
}

// uint32_t SwitchNode::DoLbWeightRandomSpray(Ptr<const Packet> p, const CustomHeader &ch,
//                                            const std::vector<int> &nexthops) {
//     // 检查是否为目标 Switch (128, 129, 130, 131)
//     bool isTargetSwitch = (m_id == 128 || m_id == 129 || m_id == 130 || m_id == 131);

//     // 只有是目标 Switch 且有多个路径可选时，才执行加权随机逻辑
//     if (isTargetSwitch && nexthops.size() > 1) {
        
//         // --- 调试输出：打印 nexthops 内容 ---
//         // std::cout << "[DEBUG] Switch(" << m_id << ") nexthops list: [ ";
//         // for (int nh : nexthops) {
//         //     std::cout << nh << " ";
//         // }
//         // std::cout << "]" << std::endl;
//         // ---------------------------------

//         const int targetPort = 9; // 需要降低权重的特定端口 ID
//         const int weightTarget = 1;
//         const int weightOthers = 4;

//         int totalWeight = 0;

//         // 1. 第一遍遍历：计算总权重
//         for (int nh : nexthops) {
//             if (nh == targetPort) {
//                 totalWeight += weightTarget;
//             } else {
//                 totalWeight += weightOthers;
//             }
//         }

//         // 生成 [0, totalWeight - 1] 范围内的随机数
//         int r = rand() % totalWeight;

//         // 2. 第二遍遍历：根据累积权重选择
//         int currentAccumulatedWeight = 0;
//         for (int nh : nexthops) {
//             int weight = (nh == targetPort) ? weightTarget : weightOthers;
//             currentAccumulatedWeight += weight;

//             // 如果随机数落在当前累积范围内，则选择该下一跳
//             if (r < currentAccumulatedWeight) {
//                 return nh;
//             }
//         }
        
//         // 理论上不应该运行到这里，作为兜底返回最后一个
//         return nexthops.back();
//     }

//     // 如果不是 Target Switch 或者只有一条路径，退化为 Adaptive Spray
//     return DoLbAdaptiveSpray(p, ch, nexthops);
// }

uint32_t SwitchNode::DoLbWeightRandomSpray(Ptr<const Packet> p, const CustomHeader &ch,
                                           const std::vector<int> &nexthops) {
    if (nexthops.size() > 1) {
        // --- 步骤 1: 确定这个包是要去哪个 ToR ---
        uint32_t dstSwitchId = 0;

        // 查找 DIP 对应的 ToR ID
        // 注意：这个 map 是在 main.cc 里初始化的，SwitchNode 可以直接读
        auto it = Settings::hostIp2SwitchId.find(ch.dip);
        if (it != Settings::hostIp2SwitchId.end()) {
            dstSwitchId = it->second;
        }

        // --- 步骤 2: 准备查找权重 ---
        // 只有当我们知道目标 ToR，且那个 ToR 不是我自己（非本地流量），且配置文件里加载了权重时
        bool usePortWeights = (dstSwitchId != m_id) &&
                               (Settings::portWeights.count(m_id)) &&
                               (Settings::portWeights[m_id].count(dstSwitchId));

        std::vector<double> current_weights;
        double totalWeight = 0.0;

        if(!usePortWeights) {
            return DoLbAdaptiveSpray(p, ch, nexthops);
        }

        // --- 步骤 3: 遍历所有出口，获取特定权重 ---
        for (int port : nexthops) {
            double weight = 1.0;  // 默认权重

            if (usePortWeights) {
                // 查表：[我是谁] -> [要去哪] -> [走哪个口]
                if (Settings::portWeights[m_id][dstSwitchId].count(port)) {
                    weight = Settings::portWeights[m_id][dstSwitchId][port];
                }
            }
            // 如果没查到特定权重，可以回退到物理带宽，或者默认 1.0

            // 保护机制
            if (weight < 0.001) weight = 0.001;

            current_weights.push_back(weight);
            totalWeight += weight;
        }

        // --- 步骤 4: 加权随机选择 (标准逻辑) ---
        if (totalWeight <= 0.0) return SelectRandomNextHop(nexthops);

        double r = m_lbRandom->GetValue(0.0, totalWeight);
        double currentAccumulatedWeight = 0.0;
        for (size_t i = 0; i < nexthops.size(); ++i) {
            currentAccumulatedWeight += current_weights[i];
            if (r < currentAccumulatedWeight) return nexthops[i];
        }
        return nexthops.back();
    }

    if (!nexthops.empty()) return nexthops[0];
    return 0;
}


/*---------------- DRILL-Style: flow-WCMP between groups + DRILL inside ----------------*/
// 数据源：Settings::drillGroups[m_id][dstSwitchId][gid] = { weight, ports[...] }
// 步骤：
//   1) 找到目的 ToR（根据 DIP 查 hostIp2SwitchId）
//   2) 把每个组的 ports 与当前 nexthops 取交集，得到"可达端口"
//      没有可达端口的组被剔除（例如链路 down 或者不在转发表里）
//   3) 组间：按 flow hash 做 WCMP，同一条 flow 固定映射到同一个组
//   4) 组内：对该组可达端口做 DRILL
// 若无法使用（本地流量 / 未配置 / 所有组都不可达）则退回 DoLbAdaptiveSpray。
uint32_t SwitchNode::DoLbDrillWeight(Ptr<const Packet> p, const CustomHeader &ch,
                                     const std::vector<int> &nexthops) {
    if (nexthops.empty()) return 0;
    if (nexthops.size() == 1) return nexthops[0];

    static uint32_t s_lb7SelectLogCount = 0;

    std::ostringstream nhStream;
    for (size_t i = 0; i < nexthops.size(); ++i) {
        if (i != 0) {
            nhStream << ",";
        }
        nhStream << nexthops[i];
    }

    // --- Step 1: 查目的 ToR ---
    uint32_t dstSwitchId = 0;
    auto it = Settings::hostIp2SwitchId.find(ch.dip);
    if (it != Settings::hostIp2SwitchId.end()) {
        dstSwitchId = it->second;
    } else {
        std::cout << "[LB7_FALLBACK] reason=missing-host-map sw=" << m_id << " dip="
                  << Ipv4Address(ch.dip) << " lb_mode=" << Settings::lb_mode
                  << " nexthops=[" << nhStream.str() << "]" << std::endl;
    }

    bool hasGroups = (dstSwitchId != m_id) &&
                     Settings::drillGroups.count(m_id) &&
                     Settings::drillGroups[m_id].count(dstSwitchId);
    if (!hasGroups) {
        std::cout << "[LB7_FALLBACK] reason=missing-group sw=" << m_id << " dip="
                  << Ipv4Address(ch.dip) << " dstSwitchId=" << dstSwitchId
                  << " lb_mode=" << Settings::lb_mode << " nexthops=[" << nhStream.str()
                  << "]" << std::endl;
        return DoLbAdaptiveSpray(p, ch, nexthops);
    }

    // --- Step 2: 过滤每个组的成员端口，只保留在 nexthops 里的 ---
    const auto &groups = Settings::drillGroups[m_id][dstSwitchId];
    std::vector<double> cand_weights;
    std::vector<uint32_t> cand_group_ids;
    std::vector<std::vector<int>> cand_ports;
    double totalWeight = 0.0;

    for (const auto &kv : groups) {
        uint32_t gid = kv.first;
        const Settings::DrillGroup &grp = kv.second;
        std::vector<int> reachable;
        for (uint32_t port : grp.ports) {
            for (int nh : nexthops) {
                if ((int)port == nh) {
                    reachable.push_back(nh);
                    break;
                }
            }
        }
        if (reachable.empty()) continue;  // 该组所有成员都不可达，跳过

        double w = grp.weight;
        if (w < 0.001) w = 0.001;  // 防御：weight 不能为 0
        cand_weights.push_back(w);
        cand_group_ids.push_back(gid);
        cand_ports.push_back(std::move(reachable));
        totalWeight += w;
    }

    if (cand_ports.empty() || totalWeight <= 0.0) {
        std::cout << "[LB7_FALLBACK] reason=no-reachable-group-port sw=" << m_id << " dip="
                  << Ipv4Address(ch.dip) << " dstSwitchId=" << dstSwitchId
                  << " groupCount=" << groups.size() << " lb_mode=" << Settings::lb_mode
                  << " nexthops=[" << nhStream.str() << "]" << std::endl;
        return DoLbAdaptiveSpray(p, ch, nexthops);
    }

    // --- Step 3: 组间 flow-level WCMP ---
    union {
        uint8_t u8[4 + 4 + 2 + 2];
        uint32_t u32[3];
    } buf;
    buf.u32[0] = ch.sip;
    buf.u32[1] = ch.dip;
    if (ch.l3Prot == 0x6) {
        buf.u32[2] = ch.tcp.sport | ((uint32_t) ch.tcp.dport << 16);
    } else if (ch.l3Prot == 0x11) {
        buf.u32[2] = ch.udp.sport | ((uint32_t) ch.udp.dport << 16);
    } else if (ch.l3Prot == 0xFC || ch.l3Prot == 0xFD) {
        buf.u32[2] = ch.ack.sport | ((uint32_t) ch.ack.dport << 16);
    } else {
        std::cout << "[LB7_FALLBACK] reason=unsupported-l3prot sw=" << m_id << " dip="
                  << Ipv4Address(ch.dip) << " l3Prot=0x" << std::hex
                  << static_cast<uint32_t>(ch.l3Prot) << std::dec << " dstSwitchId="
                  << dstSwitchId << " lb_mode=" << Settings::lb_mode << " nexthops=["
                  << nhStream.str() << "]" << std::endl;
        return DoLbAdaptiveSpray(p, ch, nexthops);
    }

    uint32_t hashVal = EcmpHash(buf.u8, 12, m_ecmpSeed);
    double hashRatio = static_cast<double>(hashVal) /
                       (static_cast<double>(std::numeric_limits<uint32_t>::max()) + 1.0);
    double r = hashRatio * totalWeight;
    double acc = 0.0;
    size_t chosen = cand_weights.size() - 1;  // 兜底
    for (size_t i = 0; i < cand_weights.size(); ++i) {
        acc += cand_weights[i];
        if (r < acc) { chosen = i; break; }
    }

    // --- Step 4: 组内 DRILL ---
    const std::vector<int> &chosen_ports = cand_ports[chosen];
    uint64_t groupedStateKey = (static_cast<uint64_t>(ch.dip) << 32) | cand_group_ids[chosen];
    if (s_lb7SelectLogCount < 20) {
        std::ostringstream chosenPortStream;
        for (size_t i = 0; i < chosen_ports.size(); ++i) {
            if (i != 0) {
                chosenPortStream << ",";
            }
            chosenPortStream << chosen_ports[i];
        }
        std::cout << "[LB7_SELECT] sw=" << m_id << " dip=" << Ipv4Address(ch.dip)
                  << " dstSwitchId=" << dstSwitchId << " gid=" << cand_group_ids[chosen]
                  << " groupPorts=[" << chosenPortStream.str() << "]"
                  << " totalGroups=" << cand_group_ids.size() << std::endl;
        ++s_lb7SelectLogCount;
    }
    return SelectDrillNextHop(chosen_ports, groupedStateKey, m_previousBestGroupedInterfaceMap);
}


/*------------------Adaptive Routing Packet Spraying ----------------*/
uint32_t SwitchNode::DoLbAdaptiveSpray(Ptr<const Packet> p, const CustomHeader &ch,
                                       const std::vector<int> &nexthops) {
    // 前提条件：确保下一跳列表不为空。
    if (nexthops.empty())
    {
        return 0; // 返回一个哨兵值，表示没有可用路径。
    }

    // 如果只有一个可用路径，则无需决策。
    if (nexthops.size() == 1)
    {
        return nexthops[0];
    }

    // --- 步骤 1: 在所有可能的下一跳中找到最小的队列负载。 ---
    uint32_t minLoad = std::numeric_limits<uint32_t>::max();
    for (int interface : nexthops)
    {
        uint32_t currentLoad = CalculateInterfaceLoad(interface);
        if (currentLoad < minLoad)
        {
            minLoad = currentLoad;
        }
    }

    // --- 步骤 2: 收集所有“足够好”的接口。 ---
    // 如果一个队列的负载与最小负载的差距在 3000 字节以内，我们认为它是“足够好”的。
    std::vector<int> candidateHops;
    const uint32_t threshold = 3000;
    for (int interface : nexthops)
    {
        if (CalculateInterfaceLoad(interface) <= minLoad + threshold)
        {
            candidateHops.push_back(interface);
        }
    }

    // --- 步骤 3: 在候选的下一跳中随机喷洒报文。 ---
    // candidateHops 列表保证至少包含一个元素（即负载最小的那个接口）。
    return SelectRandomNextHop(candidateHops);
}

uint32_t SwitchNode::DoLbSglb(Ptr<const Packet> p, const CustomHeader &ch,
                              const std::vector<int> &nexthops) {
    if (nexthops.empty()) {
        return 0;
    }
    if (nexthops.size() == 1) {
        return nexthops[0];
    }
    if (!m_isToR) {
        return DoLbAdaptiveSpray(p, ch, nexthops);
    }

    std::map<uint32_t, uint32_t>::const_iterator hostIt = Settings::hostIpToLeafId.find(ch.dip);
    if (hostIt == Settings::hostIpToLeafId.end()) {
        return DoLbAdaptiveSpray(p, ch, nexthops);
    }
    uint32_t dstLeafId = hostIt->second;
    if (dstLeafId == m_id) {
        return DoLbAdaptiveSpray(p, ch, nexthops);
    }

    std::vector<SglbCandidate> candidates;
    for (std::vector<int>::const_iterator it = nexthops.begin(); it != nexthops.end(); ++it) {
        uint32_t outPort = static_cast<uint32_t>(*it);
        std::map<uint32_t, std::map<uint32_t, uint32_t>>::const_iterator leafIt =
            Settings::leafPortToSpineId.find(m_id);
        if (leafIt == Settings::leafPortToSpineId.end()) {
            continue;
        }
        std::map<uint32_t, uint32_t>::const_iterator spineIt = leafIt->second.find(outPort);
        if (spineIt == leafIt->second.end()) {
            continue;
        }

        uint32_t spineId = spineIt->second;
        std::map<uint32_t, std::map<uint32_t, Settings::SglbRemoteState>>::const_iterator remoteBySpineIt =
            Settings::sglbRemoteStates.find(spineId);
        if (remoteBySpineIt == Settings::sglbRemoteStates.end()) {
            continue;
        }
        std::map<uint32_t, Settings::SglbRemoteState>::const_iterator remoteIt =
            remoteBySpineIt->second.find(dstLeafId);
        if (remoteIt == remoteBySpineIt->second.end()) {
            continue;
        }

        uint32_t localQueue = CalculateInterfaceLoad(outPort);
        uint32_t remoteQueue = remoteIt->second.remoteQueueBytes;
        double weight = 1.0;
        if (Settings::portWeights.count(m_id) &&
            Settings::portWeights[m_id].count(dstLeafId) &&
            Settings::portWeights[m_id][dstLeafId].count(outPort)) {
            weight = Settings::portWeights[m_id][dstLeafId][outPort];
        }
        if (weight < 0.001) {
            weight = 0.001;
        }

        SglbCandidate candidate;
        candidate.outPort = outPort;
        candidate.score = localQueue + remoteQueue;
        candidate.weight = weight;
        candidates.push_back(candidate);
    }

    if (candidates.empty()) {
        return DoLbAdaptiveSpray(p, ch, nexthops);
    }
    if (candidates.size() == 1) {
        return candidates[0].outPort;
    }

    std::sort(candidates.begin(), candidates.end(),
              [](const SglbCandidate &lhs, const SglbCandidate &rhs) {
                  if (lhs.score != rhs.score) {
                      return lhs.score < rhs.score;
                  }
                  return lhs.outPort < rhs.outPort;
              });

    const size_t topK = std::min<size_t>(8, candidates.size());
    double totalWeight = 0.0;
    for (size_t i = 0; i < topK; ++i) {
        totalWeight += candidates[i].weight;
    }
    if (totalWeight <= 0.0) {
        return candidates[0].outPort;
    }

    double r = m_lbRandom->GetValue(0.0, totalWeight);
    double cumulative = 0.0;
    for (size_t i = 0; i < topK; ++i) {
        cumulative += candidates[i].weight;
        if (r < cumulative) {
            return candidates[i].outPort;
        }
    }
    return candidates[topK - 1].outPort;
}

/*------------------ConWeave Dummy ----------------*/
uint32_t SwitchNode::DoLbConWeave(Ptr<const Packet> p, const CustomHeader &ch,
                                  const std::vector<int> &nexthops) {
    return DoLbFlowECMP(p, ch, nexthops);  // flow ECMP (dummy)
}
/*----------------------------------*/

// void SwitchNode::CheckAndSendPfc(uint32_t inDev, uint32_t qIndex) {
// 	Ptr<QbbNetDevice> device = DynamicCast<QbbNetDevice>(m_devices[inDev]);
// 	if (m_mmu->CheckShouldPause(inDev, qIndex)) {
// 		device->SendPfc(qIndex, 0);
// 		// std::cout << "sending PFC" << std::endl;
// 		m_mmu->SetPause(inDev, qIndex);
// 	}
// }

// void SwitchNode::CheckAndSendResume(uint32_t inDev, uint32_t qIndex) {
// 	Ptr<QbbNetDevice> device = DynamicCast<QbbNetDevice>(m_devices[inDev]);
// 	if (m_mmu->CheckShouldResume(inDev, qIndex)) {
// 		device->SendPfc(qIndex, 1);
// 		m_mmu->SetResume(inDev, qIndex);
// 	}
// }

void SwitchNode::FlushPfcTrace() {
    if (m_isPfcEventPending) {
        // 触发追蹤，发送我们记录到的峰值拥塞信息
        m_tracePfcPause(m_pendingPfcEvent);
        // 重置状态，准备好追踪下一个新的拥塞事件
        m_isPfcEventPending = false;
    }
}

void SwitchNode::AnalyzeAndTracePfcCongestion(uint32_t triggeringInDev)
{
    uint32_t currentCongestedEgDev = 0;
    uint32_t currentMaxLoad = 0;
    for (uint32_t i = 1; i < m_devices.size(); ++i) {
        if (m_devices[i]) { 
            uint32_t load = CalculateInterfaceLoad(i);
            if (load > currentMaxLoad) {
                currentMaxLoad = load;
                currentCongestedEgDev = i;
            }
        }
    }

    // m_flushEvent.Cancel();

    if (!m_isPfcEventPending) {
        m_isPfcEventPending = true;
        
        m_pendingPfcEvent.nodeId = m_id;
        m_pendingPfcEvent.triggeringInDev = triggeringInDev;
        m_pendingPfcEvent.congestedEgDev = currentCongestedEgDev;
        m_pendingPfcEvent.maxQueueLength = currentMaxLoad;

        if (m_isToR) m_pendingPfcEvent.switchType = 1;
        else if (m_isSpine) m_pendingPfcEvent.switchType = 2;
        else if (m_isCore) m_pendingPfcEvent.switchType = 3;
        else m_pendingPfcEvent.switchType = 0;

        if (m_egressFlowStats.count(currentCongestedEgDev)) {
            m_pendingPfcEvent.incastFlowCount = m_egressFlowStats.at(currentCongestedEgDev).size();
            m_pendingPfcEvent.uniqueSrcIpCount = m_egressSrcIpStats.at(currentCongestedEgDev).size();
        } else {
            m_pendingPfcEvent.incastFlowCount = 0;
            m_pendingPfcEvent.uniqueSrcIpCount = 0;
        }

    } else {
        if (m_pendingPfcEvent.congestedEgDev != currentCongestedEgDev) {
            // FlushPfcTrace();

            m_isPfcEventPending = true;
            m_pendingPfcEvent.nodeId = m_id;
            m_pendingPfcEvent.triggeringInDev = triggeringInDev;
            m_pendingPfcEvent.congestedEgDev = currentCongestedEgDev;
            m_pendingPfcEvent.maxQueueLength = currentMaxLoad;
            
            if (m_isToR) m_pendingPfcEvent.switchType = 1;
            else if (m_isSpine) m_pendingPfcEvent.switchType = 2;
            else if (m_isCore) m_pendingPfcEvent.switchType = 3;
            else m_pendingPfcEvent.switchType = 0;

            if (m_egressFlowStats.count(currentCongestedEgDev)) {
                m_pendingPfcEvent.incastFlowCount = m_egressFlowStats.at(currentCongestedEgDev).size();
                m_pendingPfcEvent.uniqueSrcIpCount = m_egressSrcIpStats.at(currentCongestedEgDev).size();
            } else {
                 m_pendingPfcEvent.incastFlowCount = 0;
                 m_pendingPfcEvent.uniqueSrcIpCount = 0;
            }

        } else {
            size_t currentIncastFlowCount = 0;
            size_t currentUniqueSrcIpCount = 0;
            if (m_egressFlowStats.count(currentCongestedEgDev)) {
                currentIncastFlowCount = m_egressFlowStats.at(currentCongestedEgDev).size();
                currentUniqueSrcIpCount = m_egressSrcIpStats.at(currentCongestedEgDev).size();
            }
            if (currentMaxLoad > m_pendingPfcEvent.maxQueueLength) {
                m_pendingPfcEvent.maxQueueLength = currentMaxLoad;
            }
            if (currentIncastFlowCount > m_pendingPfcEvent.incastFlowCount) {
                m_pendingPfcEvent.incastFlowCount = currentIncastFlowCount;
            }
            if (currentUniqueSrcIpCount > m_pendingPfcEvent.uniqueSrcIpCount) {
                m_pendingPfcEvent.uniqueSrcIpCount = currentUniqueSrcIpCount;
            }
        }
    }
    FlushPfcTrace();

    // m_flushEvent = Simulator::Schedule(MicroSeconds(1), &SwitchNode::FlushPfcTrace, this);
}

void SwitchNode::CheckAndSendPfc(uint32_t inDev, uint32_t qIndex) {
    Ptr<QbbNetDevice> device = DynamicCast<QbbNetDevice>(m_devices[inDev]);
    bool pClasses[qCnt] = {0};
    m_mmu->GetPauseClasses(inDev, qIndex, pClasses);

    bool shouldTrace = false;
    for (int j = 0; j < qCnt; j++) {
        if (pClasses[j]) {
            uint32_t paused_time = device->SendPfc(j, 0);
            m_mmu->SetPause(inDev, j, paused_time);
            m_mmu->m_pause_remote[inDev][j] = true;
            shouldTrace = true;
            /** PAUSE SEND COUNT ++ */
        }
    }

    if (m_isToR && shouldTrace) {
        AnalyzeAndTracePfcCongestion(inDev);
    }

    for (int j = 0; j < qCnt; j++) {
        if (!m_mmu->m_pause_remote[inDev][j]) continue;

        if (m_mmu->GetResumeClasses(inDev, j)) {
            device->SendPfc(j, 1);
            m_mmu->SetResume(inDev, j);
            m_mmu->m_pause_remote[inDev][j] = false;
        }
    }
}
void SwitchNode::CheckAndSendResume(uint32_t inDev, uint32_t qIndex) {
    Ptr<QbbNetDevice> device = DynamicCast<QbbNetDevice>(m_devices[inDev]);
    if (m_mmu->GetResumeClasses(inDev, qIndex)) {
        device->SendPfc(qIndex, 1);
        m_mmu->SetResume(inDev, qIndex);
    }
}

/********************************************
 *              MAIN LOGICS                 *
 *******************************************/

// This function can only be called in switch mode
bool SwitchNode::SwitchReceiveFromDevice(Ptr<NetDevice> device, Ptr<Packet> packet,
                                         CustomHeader &ch) {
    SendToDev(packet, ch);
    return true;
}

void SwitchNode::SendToDev(Ptr<Packet> p, CustomHeader &ch) {
    /** HIJACK: hijack the packet and run DoSwitchSend internally for Conga and ConWeave.
     * Note that DoLbConWeave() and DoLbConga() are flow-ECMP function for control packets
     * or intra-ToR traffic.
     */

    // Conga
    if (Settings::lb_mode == 3) {
        m_mmu->m_congaRouting.RouteInput(p, ch);
        return;
    }

    // ConWeave
    if (Settings::lb_mode == 9) {
        m_mmu->m_conweaveRouting.RouteInput(p, ch);
        return;
    }

    // Others
    SendToDevContinue(p, ch);
}

void SwitchNode::SendToDevContinue(Ptr<Packet> p, CustomHeader &ch) {
    int idx = GetOutDev(p, ch);
    if (idx >= 0) {
        NS_ASSERT_MSG(m_devices[idx]->IsLinkUp(),
                      "The routing table look up should return link that is up");

        // determine the qIndex
        uint32_t qIndex;
        if (ch.l3Prot == 0xFF || ch.l3Prot == 0xFE ||
            (m_ackHighPrio &&
             (ch.l3Prot == 0xFD ||
              ch.l3Prot == 0xFC))) {  // QCN or PFC or ACK/NACK, go highest priority
            qIndex = 0;               // high priority
        } else {
            qIndex = (ch.l3Prot == 0x06 ? 1 : ch.udp.pg);  // if TCP, put to queue 1. Otherwise, it
                                                           // would be 3 (refer to trafficgen)
        }

        DoSwitchSend(p, ch, idx, qIndex);  // m_devices[idx]->SwitchSend(qIndex, p, ch);
        return;
    }
    std::cout << "WARNING - Drop occurs in SendToDevContinue()" << std::endl;
    return;  // Drop otherwise
}

int SwitchNode::GetOutDev(Ptr<Packet> p, CustomHeader &ch) {
    // look up entries
    auto entry = m_rtTable.find(ch.dip);

    // no matching entry
    if (entry == m_rtTable.end()) {
        std::cout << "[ERROR] Sw(" << m_id << ")," << PARSE_FIVE_TUPLE(ch)
                  << "No matching entry, so drop this packet at SwitchNode (l3Prot:" << ch.l3Prot
                  << ")" << std::endl;
        assert(false);
    }

    // entry found
    const auto &nexthops = entry->second;
    bool control_pkt =
        (ch.l3Prot == 0xFF || ch.l3Prot == 0xFE || ch.l3Prot == 0xFD || ch.l3Prot == 0xFC);

    if (Settings::lb_mode == 0 || control_pkt) {  // control packet (ACK, NACK, PFC, QCN)
        // Check if packet has LaneIdTag (for per-lane DCQCN mode)
        // If yes, use per-lane ECMP regardless of lb_mode
        LaneIdTag laneTag;
        if (p->PeekPacketTag(laneTag)) {
            return DoLbPerLaneECMP(p, ch, nexthops);
        }
        return DoLbFlowECMP(p, ch, nexthops);     // ECMP routing path decision (4-tuple)
    }

    switch (Settings::lb_mode) {
        case 1:  // RPS
            return DoLbRandomSpray(p, ch, nexthops);  // RPS, just return the first one
        case 2:
            return DoLbDrill(p, ch, nexthops);
        case 3:
            return DoLbConga(p, ch, nexthops); /** DUMMY: Do ECMP */
        case 4:
            return DoLbAdaptiveSpray(p, ch, nexthops);  // Adaptive Routing
        case 5:
            return DoLbWeightRandomSpray(p, ch, nexthops);  // Weighted Random Spraying
        case 6:
            return DoLbLetflow(p, ch, nexthops);
        case 7:
            return DoLbDrillWeight(p, ch, nexthops);  // DRILL: WCMP across groups + spray within
        case 9:
            return DoLbConWeave(p, ch, nexthops); /** DUMMY: Do ECMP */
        case 10:
            return DoLbSglb(p, ch, nexthops);
        default:
            std::cout << "Unknown lb_mode(" << Settings::lb_mode << ")" << std::endl;
            assert(false);
    }
}

/**
 * @brief Safely calculates the total size of L2, L3, and L4 headers.
 * * This function works on a temporary copy of the packet and does not
 * modify the original packet. It assumes a PPP -> IPv4 -> TCP/UDP stack.
 * * @param packet The packet to inspect.
 * @return The total size of the headers in bytes.
 */
uint32_t SwitchNode::GetTotalHeaderSize(Ptr<const Packet> packet) const
{
    // Create a temporary copy to perform header removal without affecting the original packet.
    Ptr<Packet> copy = packet->Copy();

    uint32_t totalHeaderSize = 0;

    // 1. L2 Header (PPP)
    PppHeader ppp;
    totalHeaderSize += copy->RemoveHeader(ppp);

    // 2. L3 Header (IPv4)
    Ipv4Header ip;
    totalHeaderSize += copy->RemoveHeader(ip);

    // 3. L4 Header (Transport Layer)
    // Check the protocol number from the IP header we just removed.
    uint8_t protocol = ip.GetProtocol();

    if (protocol == 6) { // TCP
        TcpHeader tcp;
        totalHeaderSize += copy->RemoveHeader(tcp);
    } else if (protocol == 17 || protocol == 0xFC || protocol == 0xFD) { // UDP or custom protocols
        // Assuming UDP and custom headers are a fixed 8 bytes.
        // A more robust way for unknown headers would be to peek, 
        // but for this context, RemoveHeader on a known size is fine.
        UdpHeader udp; // Use UdpHeader as a placeholder for 8-byte headers
        totalHeaderSize += copy->RemoveHeader(udp);
    }
    
    // If the protocol is unknown, we just return the size of L2+L3.
    return totalHeaderSize;
}

/****************************************************************
 * Incast Statistics Functions                     *
 ***************************************************************/

FlowIdentifier SwitchNode::GetFlowId(const CustomHeader& ch) const {
    FlowIdentifier id = {ch.sip, ch.dip, 0, 0, static_cast<uint8_t>(ch.l3Prot)};
    if (ch.l3Prot == 0x6) { // TCP
        id.srcPort = ch.tcp.sport;
        id.dstPort = ch.tcp.dport;
    } else if (ch.l3Prot == 0x11) { // UDP
        id.srcPort = ch.udp.sport;
        id.dstPort = ch.udp.dport;
    } else if (ch.l3Prot == 0xFC || ch.l3Prot == 0xFD) { // ACK or NACK
        id.srcPort = ch.ack.sport;
        id.dstPort = ch.ack.dport;
    }
    return id;
}

void SwitchNode::UpdateQueueStatsOnEnqueue(uint32_t inDev, uint32_t outDev, const CustomHeader& ch) {
    FlowIdentifier flowId = GetFlowId(ch);
    uint32_t srcIp = ch.sip;

    // Increment ingress stats
    m_ingressFlowStats[inDev][flowId]++;
    m_ingressSrcIpStats[inDev][srcIp]++;

    // Increment egress stats
    m_egressFlowStats[outDev][flowId]++;
    m_egressSrcIpStats[outDev][srcIp]++;

    Ipv4Address srcAddr(ch.sip);
    Ipv4Address dstAddr(ch.dip);
}

void SwitchNode::UpdateQueueStatsOnDequeue(uint32_t inDev, uint32_t outDev, const CustomHeader& ch) {
    FlowIdentifier flowId = GetFlowId(ch);
    uint32_t srcIp = ch.sip;

    // Ipv4Address srcAddr(ch.sip);
    // Ipv4Address dstAddr(ch.dip);

    // Decrement ingress stats
    if (m_ingressFlowStats.count(inDev) && m_ingressFlowStats[inDev].count(flowId)) {
        // uint32_t count_before = m_ingressFlowStats[inDev][flowId];
        if (--m_ingressFlowStats[inDev][flowId] == 0) {
            m_ingressFlowStats[inDev].erase(flowId);
            // std::cout << "    -> Ingress Flow: " << count_before << " -> 0. Entry ERASED." << std::endl;
        } else {
            // std::cout << "    -> Ingress Flow: " << count_before << " -> " << m_ingressFlowStats[inDev][flowId] << "." << std::endl;
        }
    } 
    if (m_ingressSrcIpStats.count(inDev) && m_ingressSrcIpStats[inDev].count(srcIp)) {
        // uint32_t count_before = m_ingressSrcIpStats[inDev][srcIp];
        if (--m_ingressSrcIpStats[inDev][srcIp] == 0) {
            m_ingressSrcIpStats[inDev].erase(srcIp);
            // std::cout << "    -> Ingress SrcIP: " << count_before << " -> 0. Entry ERASED." << std::endl;
        } else {
            // std::cout << "    -> Ingress SrcIP: " << count_before << " -> " << m_ingressSrcIpStats[inDev][srcIp] << "." << std::endl;
        }
    }

    // Decrement egress stats
    if (m_egressFlowStats.count(outDev) && m_egressFlowStats[outDev].count(flowId)) {
        // uint32_t count_before = m_egressFlowStats[outDev][flowId];
        if (--m_egressFlowStats[outDev][flowId] == 0) {
            m_egressFlowStats[outDev].erase(flowId);
            // std::cout << "    -> Egress Flow: " << count_before << " -> 0. Entry ERASED." << std::endl;
        } else {
            // std::cout << "    -> Egress Flow: " << count_before << " -> " << m_egressFlowStats[outDev][flowId] << "." << std::endl;
        }
    }
    if (m_egressSrcIpStats.count(outDev) && m_egressSrcIpStats[outDev].count(srcIp)) {
        // uint32_t count_before = m_egressSrcIpStats[outDev][srcIp];
        if (--m_egressSrcIpStats[outDev][srcIp] == 0) {
            m_egressSrcIpStats[outDev].erase(srcIp);
            // std::cout << "    -> Egress SrcIP: " << count_before << " -> 0. Entry ERASED." << std::endl;
        } else {
            // std::cout << "    -> Egress SrcIP: " << count_before << " -> " << m_egressSrcIpStats[outDev][srcIp] << "." << std::endl;
        }
    }
}

void SwitchNode::LogCongestionStateOnDrop(uint32_t inDev, uint32_t outDev, bool isIngressDrop, const CustomHeader& ch) {
    // std::cout << std::fixed << std::setprecision(6)
    //           << "Time " << Simulator::Now().GetSeconds() << "s - Switch " << m_id
    //           << ": PACKET DROP. Reason: " << (isIngressDrop ? "Ingress" : "Egress") << " buffer full." << std::endl;
    // std::cout << "  - Dropped Pkt Info: " << PARSE_FIVE_TUPLE(ch) << std::endl;
    
    // if (isIngressDrop) {
    //     if (m_ingressFlowStats.count(inDev)) {
    //         auto& flowStats = m_ingressFlowStats.at(inDev);
    //         auto& srcIpStats = m_ingressSrcIpStats.at(inDev);
    //         std::cout << "  - Congestion at Ingress Port [" << inDev << "]:" << std::endl;
    //         std::cout << "    - Total active flows: " << flowStats.size() << std::endl;
    //         std::cout << "    - Total unique source IPs: " << srcIpStats.size() << std::endl;
    //         // 可以在此处添加更详细的循环打印，展示每个流和IP的包数
    //     } else {
    //         std::cout << "  - No stats available for Ingress Port [" << inDev << "]." << std::endl;
    //     }
    // } else { // Egress Drop
    //     if (m_egressFlowStats.count(outDev)) {
    //         auto& flowStats = m_egressFlowStats.at(outDev);
    //         auto& srcIpStats = m_egressSrcIpStats.at(outDev);
    //         std::cout << "  - Congestion at Egress Port [" << outDev << "]:" << std::endl;
    //         std::cout << "    - Total active flows: " << flowStats.size() << std::endl;
    //         std::cout << "    - Total unique source IPs: " << srcIpStats.size() << std::endl;
            
    //         // 打印出所有源IP及其数据包计数
    //         std::cout << "    - Packets per Source IP: { ";
    //         for(auto const& [ip, count] : srcIpStats) {
    //              Ipv4Address addr(ip);
    //              std::cout << addr << ": " << count << "; ";
    //         }
    //         std::cout << "}" << std::endl;

    //     } else {
    //         std::cout << "  - No stats available for Egress Port [" << outDev << "]." << std::endl;
    //     }
    // }
    // std::cout << "--------------------------------------------------------" << std::endl;
}

DropEventInfo SwitchNode::CreateDropEventInfo(const CustomHeader& ch, bool isIngressAdmitted, uint32_t inDev, uint32_t outDev) const
{
    // 1. 創建並填充 DropEventInfo 結構體
    DropEventInfo eventInfo;
    eventInfo.nodeId = m_id;
    eventInfo.droppedPacketHeader = ch;
    eventInfo.isIngressDrop = !isIngressAdmitted; // 如果 Ingress 不允許，則為 Ingress 丟包

    // 【新增】根據交換機的 bool 標記設定 switchType
    if (m_isToR) {
        eventInfo.switchType = 1;
    } else if (m_isSpine) {
        eventInfo.switchType = 2;
    } else if (m_isCore) {
        eventInfo.switchType = 3;
    } else {
        eventInfo.switchType = 0;
    }

    if (eventInfo.isIngressDrop) {
        // 如果是 Ingress 丟包，統計 Ingress 佇列的資訊
        eventInfo.deviceId = inDev;
        if (m_ingressFlowStats.count(inDev)) {
            eventInfo.incastFlowCount = m_ingressFlowStats.at(inDev).size();
            eventInfo.uniqueSrcIpCount = m_ingressSrcIpStats.at(inDev).size();
        } else {
            eventInfo.incastFlowCount = 0; // 佇列中還沒有統計資料
            eventInfo.uniqueSrcIpCount = 0;
        }
    } else {
        // 如果是 Egress 丟包，統計 Egress 佇列的資訊
        eventInfo.deviceId = outDev;
        if (m_egressFlowStats.count(outDev)) {
            eventInfo.incastFlowCount = m_egressFlowStats.at(outDev).size();
            eventInfo.uniqueSrcIpCount = m_egressSrcIpStats.at(outDev).size();
        } else {
            eventInfo.incastFlowCount = 0;
            eventInfo.uniqueSrcIpCount = 0;
        }
    }
    
    return eventInfo;
}



/*
 * The (possible) callback point when conweave dequeues packets from buffer
 */
void SwitchNode::DoSwitchSend(Ptr<Packet> p, CustomHeader &ch, uint32_t outDev, uint32_t qIndex) {
    // admission control
    FlowIdTag t;
    p->PeekPacketTag(t);
    uint32_t inDev = t.GetFlowId();

    /** NOTE:
     * ConWeave control packets have the high priority as ACK/NACK/PFC/etc with qIndex = 0.
     */
    if (inDev == Settings::CONWEAVE_CTRL_DUMMY_INDEV) { // sanity check
        // ConWeave reply is on ACK protocol with high priority, so qIndex should be 0
        assert(qIndex == 0 && m_ackHighPrio == 1 && "ConWeave's reply packet follows ACK, so its qIndex should be 0");
    }

    if (qIndex != 0) {  // not highest priority
        bool isEgressAdmitted = m_mmu->CheckEgressAdmission(outDev, qIndex, p->GetSize());
        bool isIngressAdmitted = m_mmu->CheckIngressAdmission(inDev, qIndex, p->GetSize());

        if (isEgressAdmitted && isIngressAdmitted) {
            m_mmu->UpdateIngressAdmission(inDev, qIndex, p->GetSize());
            m_mmu->UpdateEgressAdmission(outDev, qIndex, p->GetSize());
        } else {
            // *** PACKET DROP: Log statistics here ***
            // LogCongestionStateOnDrop(inDev, outDev, !isIngressAdmitted, ch);
            DropEventInfo eventInfo = CreateDropEventInfo(ch, isIngressAdmitted, inDev, outDev);
            m_tracePacketDrop(eventInfo);

            if(!isIngressAdmitted) {
                Settings::RecordPacketDropIngress(m_id, outDev, m_isToR, m_isSpine, m_isCore);
            } else {
                Settings::RecordPacketDropEgress(m_id, outDev, m_isToR, m_isSpine, m_isCore);
            }

            uint32_t senderNodeId = Settings::ip_to_node_id(Ipv4Address(ch.sip));
            auto it = Settings::NodeIdToRdmaHwMap.find(senderNodeId);
            if (it != Settings::NodeIdToRdmaHwMap.end()) {
                Ptr<RdmaHw> senderHw = it->second;
                if (senderHw) {
                    uint32_t payloadSize = p->GetSize() - ch.GetSerializedSize();
                    senderHw->NotifyPacketDrop(ch.dip, ch.udp.sport, ch.udp.dport, ch.udp.pg, ch.udp.seq, payloadSize);
                }
            }

            if (m_idealLossRecovery) {
                Settings::ideal_drop_pkt_count++;
            }

            if (m_packetTrimming) {
                // Settings::trimmed_pkt_count++;
                 // --- Trimming is ON ---
                uint32_t sizeBefore = p->GetSize();
                // uint32_t totalHeaderSize = GetTotalHeaderSize(p);
                uint32_t totalHeaderSize = ch.GetSerializedSize();

                // --- Debug输出: 裁剪前 ---
                // std::cout << "Time " << Simulator::Now().GetSeconds() << "s - Switch " << m_id
                //           << ": [Trimming Pkt] seq=" << ch.udp.seq
                //           << ", size_before=" << sizeBefore
                //           << ", header_size=" << totalHeaderSize << "." << std::endl;

                if (sizeBefore > totalHeaderSize) {
                    Settings::trimmed_pkt_count++;
                    // 2. Trim the payload
                    p->RemoveAtEnd(sizeBefore - totalHeaderSize);

                    // 3. Correctly update the IP header's length field
                    Ipv4Header ip;
                    PppHeader ppp;
                    
                    p->RemoveHeader(ppp);
                    p->RemoveHeader(ip);

                    ip.SetPayloadSize(p->GetSize()); // Update length
                    
                    p->AddHeader(ip);
                    p->AddHeader(ppp);

                    // --- Debug输出: 裁剪后 ---
                    // std::cout << "Time " << Simulator::Now().GetSeconds() << "s - Switch " << m_id
                    //           << ": [Trimming Pkt] seq=" << ch.udp.seq
                    //           << ", size_after=" << p->GetSize()
                    //           << ". IP header updated." << std::endl;
                }

                // As discussed, we let the trimmed packet occupy buffer space
                m_mmu->UpdateIngressAdmission(inDev, qIndex, p->GetSize());
                m_mmu->UpdateEgressAdmission(outDev, qIndex, p->GetSize());

            } else {
                // --- Trimming is OFF: Drop the packet ---
                return;
            }
        }
        CheckAndSendPfc(inDev, qIndex);
    }

    // *** ENQUEUE: Update statistics here ***
    if(qIndex != 0) UpdateQueueStatsOnEnqueue(inDev, outDev, ch);
    m_devices[outDev]->SwitchSend(qIndex, p, ch);
}

void SwitchNode::SwitchNotifyDequeue(uint32_t ifIndex, uint32_t qIndex, Ptr<Packet> p) {
    FlowIdTag t;
    p->PeekPacketTag(t);
    if (qIndex != 0) {
        uint32_t inDev = t.GetFlowId();

        // *** DEQUEUE: Update statistics here ***
        CustomHeader ch(CustomHeader::L2_Header | CustomHeader::L3_Header | CustomHeader::L4_Header);
        p->PeekHeader(ch);
        UpdateQueueStatsOnDequeue(inDev, ifIndex, ch);

        if (inDev != Settings::CONWEAVE_CTRL_DUMMY_INDEV) {
            // NOTE: ConWeave's probe/reply does not need to pass inDev interface,
            // so skip for conweave's queued packets
            m_mmu->RemoveFromIngressAdmission(inDev, qIndex, p->GetSize());
        }
        m_mmu->RemoveFromEgressAdmission(ifIndex, qIndex, p->GetSize());
        if (m_ecnEnabled) {
            bool egressCongested = m_mmu->ShouldSendCN(ifIndex, qIndex);
            if (egressCongested) {
                PppHeader ppp;
                Ipv4Header h;
                p->RemoveHeader(ppp);
                p->RemoveHeader(h);
                h.SetEcn((Ipv4Header::EcnType)0x03);
                p->AddHeader(h);
                p->AddHeader(ppp);
            }
        }
        // NOTE: ConWeave's probe/reply does not need to pass inDev interface
        if (inDev != Settings::CONWEAVE_CTRL_DUMMY_INDEV) {
            CheckAndSendResume(inDev, qIndex);
        }
    }

    // HPCC's INT
    if (1) {
        uint8_t *buf = p->GetBuffer();
        if (buf[PppHeader::GetStaticSize() + 9] == 0x11) {  // udp packet
            IntHeader *ih = (IntHeader *)&buf[PppHeader::GetStaticSize() + 20 + 8 +
                                              6];  // ppp, ip, udp, SeqTs, INT
            Ptr<QbbNetDevice> dev = DynamicCast<QbbNetDevice>(m_devices[ifIndex]);
            if (m_ccMode == 3) {  // HPCC
                ih->PushHop(Simulator::Now().GetTimeStep(), m_txBytes[ifIndex],
                            dev->GetQueue()->GetNBytesTotal(), dev->GetDataRate().GetBitRate());
            }
        }
    }
    m_txBytes[ifIndex] += p->GetSize();
}

uint32_t SwitchNode::EcmpHash(const uint8_t *key, size_t len, uint32_t seed) {
    uint32_t h = seed;
    if (len > 3) {
        const uint32_t *key_x4 = (const uint32_t *)key;
        size_t i = len >> 2;
        do {
            uint32_t k = *key_x4++;
            k *= 0xcc9e2d51;
            k = (k << 15) | (k >> 17);
            k *= 0x1b873593;
            h ^= k;
            h = (h << 13) | (h >> 19);
            h += (h << 2) + 0xe6546b64;
        } while (--i);
        key = (const uint8_t *)key_x4;
    }
    if (len & 3) {
        size_t i = len & 3;
        uint32_t k = 0;
        key = &key[i - 1];
        do {
            k <<= 8;
            k |= *key--;
        } while (--i);
        k *= 0xcc9e2d51;
        k = (k << 15) | (k >> 17);
        k *= 0x1b873593;
        h ^= k;
    }
    h ^= len;
    h ^= h >> 16;
    h *= 0x85ebca6b;
    h ^= h >> 13;
    h *= 0xc2b2ae35;
    h ^= h >> 16;
    return h;
}

void SwitchNode::SetEcmpSeed(uint32_t seed) { m_ecmpSeed = seed; }

void SwitchNode::AddTableEntry(Ipv4Address &dstAddr, uint32_t intf_idx) {
    uint32_t dip = dstAddr.Get();
    m_rtTable[dip].push_back(intf_idx);
}

void SwitchNode::ClearTable() { m_rtTable.clear(); }

uint64_t SwitchNode::GetTxBytesOutDev(uint32_t outdev) {
    assert(outdev < pCnt);
    return m_txBytes[outdev];
}

} /* namespace ns3 */
