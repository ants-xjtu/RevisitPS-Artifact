#ifndef __SETINGS_H__
#define __SETINGS_H__

#include <stdbool.h>
#include <stdint.h>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <list>
#include <map>
#include <numeric>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "ns3/callback.h"
#include "ns3/custom-header.h"
#include "ns3/double.h"
#include "ns3/ipv4-address.h"
#include "ns3/net-device.h"
#include "ns3/nstime.h"
#include "ns3/object.h"
#include "ns3/packet.h"
#include "ns3/ptr.h"
#include "ns3/string.h"
#include "ns3/tag.h"
#include "ns3/uinteger.h"
#include "ns3/rdma-hw.h"

namespace ns3 {

#define SLB_DEBUG (false)

#define PARSE_FIVE_TUPLE(ch)                                                    \
    DEPARSE_FIVE_TUPLE(std::to_string(Settings::hostIp2IdMap[ch.sip]),          \
                       std::to_string(ch.udp.sport),                            \
                       std::to_string(Settings::hostIp2IdMap[ch.dip]),          \
                       std::to_string(ch.udp.dport), std::to_string(ch.l3Prot), \
                       std::to_string(ch.udp.seq), std::to_string(ch.GetIpv4EcnBits()))
#define PARSE_REVERSE_FIVE_TUPLE(ch)                                            \
    DEPARSE_FIVE_TUPLE(std::to_string(Settings::hostIp2IdMap[ch.dip]),          \
                       std::to_string(ch.udp.dport),                            \
                       std::to_string(Settings::hostIp2IdMap[ch.sip]),          \
                       std::to_string(ch.udp.sport), std::to_string(ch.l3Prot), \
                       std::to_string(ch.udp.seq), std::to_string(ch.GetIpv4EcnBits()))
#define DEPARSE_FIVE_TUPLE(sip, sport, dip, dport, protocol, seq, ecn)                        \
    sip << "(" << sport << ")," << dip << "(" << dport << ")[" << protocol << "],SEQ:" << seq \
        << ",ECN:" << ecn << ","

#if (SLB_DEBUG == true)
#define SLB_LOG(msg) \
    std::cout << __FILE__ << "(" << __LINE__ << "):" << Simulator::Now() << "," << msg << std::endl
#else
#define SLB_LOG(msg) \
    do {             \
    } while (0)
#endif

/**
 * @brief For flowlet-routing
 */
struct Flowlet {
    Time _activeTime;     // to check creating a new flowlet
    Time _activatedTime;  // start time of new flowlet
    uint32_t _PathId;     // current pathId
    uint32_t _nPackets;   // for debugging
};

/**
 * @brief Tag for monitoring last data sending time per flow
 */
class LastSendTimeTag : public Tag {
   public:
    LastSendTimeTag() : Tag() {}
    static TypeId GetTypeId(void) {
        static TypeId tid =
            TypeId("ns3::LastSendTimeTag").SetParent<Tag>().AddConstructor<LastSendTimeTag>();
        return tid;
    }
    virtual TypeId GetInstanceTypeId(void) const { return GetTypeId(); }
    virtual void Print(std::ostream &os) const {}
    virtual uint32_t GetSerializedSize(void) const { return sizeof(m_pktType); }
    virtual void Serialize(TagBuffer i) const { i.WriteU8(m_pktType); }
    virtual void Deserialize(TagBuffer i) { m_pktType = i.ReadU8(); }
    void SetPktType(uint8_t type) { m_pktType = type; }
    uint8_t GetPktType() { return m_pktType; }

    enum pktType {
        PACKET_NULL = 0,
        PACKET_FIRST = 1,
        PACKET_LAST = 2,
        PACKET_SINGLE = 3,
    };

   private:
    uint8_t m_pktType;
};

/**
 * @brief Global setting parameters
 */

class Settings {
   public:
    Settings() {}
    virtual ~Settings() {}

    /* helper function */
    static Ipv4Address node_id_to_ip(uint32_t id);  // node_id -> ip
    static uint32_t ip_to_node_id(Ipv4Address ip);  // ip -> node_id

    /* conweave params */
    static const uint32_t CONWEAVE_CTRL_DUMMY_INDEV = 88888888;  // just arbitrary

    /* load balancer */
    // 0: flow ECMP, 1:RPS, 2: DRILL, 3: Conga, 4: ConWeave
    static uint32_t lb_mode;

    /*adaptive routing*/
    // 0: no AR, 1: AR, 2: ARSP (adaptive routing with selective repeat)
    static uint32_t ar_mode;

    // for common setting
    static uint32_t packet_payload;

    // for statistic
    static uint32_t node_num;
    static uint32_t host_num;
    static uint32_t switch_num;
    static uint64_t cnt_finished_flows;  // number of finished flows (in qp_finish())

    /* The map between hosts' IP and ID, initial when build topology */
    static std::map<uint32_t, Ptr<RdmaHw>> NodeIdToRdmaHwMap;
    static std::map<uint32_t, uint32_t> hostIp2IdMap;
    static std::map<uint32_t, uint32_t> hostId2IpMap;
    static std::map<uint32_t, uint32_t> hostIp2SwitchId;  // host's IP -> connected Switch's Id
    static std::map<uint32_t, std::map<uint32_t, bool>> ToRId2UporDownMap;  // ToR's Id -> {portId, up/down} True if up, false if down
    static std::map<uint32_t, std::map<uint32_t, bool>> SpineId2UporDownMap; // Spine's Id -> {portId, up/down}
    static std::map<uint32_t, std::map<uint32_t, bool>> CoreId2UporDownMap;  // Core's Id -> {portId, up/down}

    static uint32_t dropped_pkt_sw_ingress;
    static uint32_t dropped_pkt_sw_egress;
    // Drop statistics for ingress and egress at different switch types
    static uint32_t dropped_pkt_tor_up_ingress;      // ToR ingress - uplink port
    static uint32_t dropped_pkt_tor_down_ingress;    // ToR ingress - downlink port
    static uint32_t dropped_pkt_tor_up_egress;       // ToR egress - uplink port
    static uint32_t dropped_pkt_tor_down_egress;     // ToR egress - downlink port
     // ADD these new, more detailed spine counters
    static uint32_t dropped_pkt_spine_up_ingress;      // Spine ingress - uplink port
    static uint32_t dropped_pkt_spine_down_ingress;    // Spine ingress - downlink port
    static uint32_t dropped_pkt_spine_up_egress;       // Spine egress - uplink port
    static uint32_t dropped_pkt_spine_down_egress;     // Spine egress - downlink port
    static uint32_t dropped_pkt_core_ingress;      // Core switch ingress
    static uint32_t dropped_pkt_core_egress;       // Core switch egress
    static uint32_t dropped_pkt_error;  // Error packets
    static uint32_t trimmed_pkt_count;
    static uint32_t ideal_drop_pkt_count;
    static uint64_t ar_retransmissions_with_drop;
    static uint64_t ar_spurious_retransmissions;

    //OOO trace
    static uint64_t total_rx_pkt_count; // 接收到的總數據封包數量
    static uint64_t ooo_pkt_count;      // 亂序封包的總數量
    static std::map<uint32_t, uint64_t> reordering_distance_counts;
    static std::map<uint32_t, uint64_t> ooo_burst_size_counts;

    //Load balancing weight
    static std::map<uint32_t, std::map<uint32_t, std::map<uint32_t, double>>> portWeights;

    struct SglbRemoteState {
        uint32_t remoteQueueBytes;
        uint64_t lastUpdateNs;

        SglbRemoteState() : remoteQueueBytes(0), lastUpdateNs(0) {}
    };

    static std::map<uint32_t, std::map<uint32_t, SglbRemoteState>> sglbRemoteStates;
    static std::map<uint32_t, std::map<uint32_t, uint32_t>> leafPortToSpineId;
    static std::map<uint32_t, uint32_t> hostIpToLeafId;
    static std::map<uint32_t, std::map<uint32_t, uint32_t>> spineToLeafOutPort;

    // DRILL-style 分组：对每个 (src_switch, dst_switch)，给若干个 group (gid)，
    // 每个 group 记录 (weight, 成员端口列表)。
    // 转发时先按 weight 做 WCMP 选组，再在组内做 Packet Spraying。
    struct DrillGroup {
        double weight;
        std::vector<uint32_t> ports;
    };
    static std::map<uint32_t, std::map<uint32_t, std::map<uint32_t, DrillGroup>>> drillGroups;

    // drop recording functions
    // UPDATE THE FUNCTION SIGNATURES
    static void RecordPacketDropIngress(uint32_t swId, uint32_t outDev, bool isToR, bool isSpine, bool isCore);
    static void RecordPacketDropEgress(uint32_t swId, uint32_t outDev, bool isToR, bool isSpine, bool isCore);

    static void RecordOutOfOrderPacket(uint32_t received_seq, uint32_t expected_seq);
};

}  // namespace ns3

#endif
