#include "ns3/settings.h"

namespace ns3 {
/* helper function */
Ipv4Address Settings::node_id_to_ip(uint32_t id) {
    return Ipv4Address(0x0b000001 + ((id / 256) * 0x00010000) + ((id % 256) * 0x00000100));
}
uint32_t Settings::ip_to_node_id(Ipv4Address ip) {
    return (ip.Get() >> 8) & 0xffff;
}

/* others */
uint32_t Settings::lb_mode = 0;
uint32_t Settings::ar_mode = 0;

std::map<uint32_t, Ptr<RdmaHw>> Settings::NodeIdToRdmaHwMap;
std::map<uint32_t, uint32_t> Settings::hostIp2IdMap;
std::map<uint32_t, uint32_t> Settings::hostId2IpMap;
std::map<uint32_t, std::map<uint32_t, bool>> Settings::ToRId2UporDownMap;
std::map<uint32_t, std::map<uint32_t, bool>> Settings::SpineId2UporDownMap;
std::map<uint32_t, std::map<uint32_t, bool>> Settings::CoreId2UporDownMap;

/* statistics */
uint32_t Settings::node_num = 0;
uint32_t Settings::host_num = 0;
uint32_t Settings::switch_num = 0;
uint64_t Settings::cnt_finished_flows = 0;
uint32_t Settings::packet_payload = 1000;

uint32_t Settings::dropped_pkt_sw_ingress = 0;
uint32_t Settings::dropped_pkt_sw_egress = 0;
uint32_t Settings::dropped_pkt_tor_up_ingress = 0;
uint32_t Settings::dropped_pkt_tor_down_ingress = 0;
uint32_t Settings::dropped_pkt_tor_up_egress = 0;
uint32_t Settings::dropped_pkt_tor_down_egress = 0;
uint32_t Settings::dropped_pkt_spine_up_ingress = 0;
uint32_t Settings::dropped_pkt_spine_down_ingress = 0;
uint32_t Settings::dropped_pkt_spine_up_egress = 0;
uint32_t Settings::dropped_pkt_spine_down_egress = 0;
uint32_t Settings::dropped_pkt_core_ingress = 0;
uint32_t Settings::dropped_pkt_core_egress = 0;
uint32_t Settings::dropped_pkt_error = 0;
uint32_t Settings::trimmed_pkt_count = 0;
uint32_t Settings::ideal_drop_pkt_count = 0;
uint64_t Settings::ar_retransmissions_with_drop = 0;
uint64_t Settings::ar_spurious_retransmissions = 0;

uint64_t Settings::total_rx_pkt_count = 0;
uint64_t Settings::ooo_pkt_count = 0;
std::map<uint32_t, uint64_t> Settings::reordering_distance_counts;
std::map<uint32_t, uint64_t> Settings::ooo_burst_size_counts;

/* for load balancer */
std::map<uint32_t, uint32_t> Settings::hostIp2SwitchId;

/* for weight load balancer */
std::map<uint32_t, std::map<uint32_t, std::map<uint32_t, double>>> Settings::portWeights;
std::map<uint32_t, std::map<uint32_t, Settings::SglbRemoteState>> Settings::sglbRemoteStates;
std::map<uint32_t, std::map<uint32_t, uint32_t>> Settings::leafPortToSpineId;
std::map<uint32_t, uint32_t> Settings::hostIpToLeafId;
std::map<uint32_t, std::map<uint32_t, uint32_t>> Settings::spineToLeafOutPort;

/* for DRILL-style group load balancer (WCMP between groups + spraying within) */
std::map<uint32_t, std::map<uint32_t, std::map<uint32_t, Settings::DrillGroup>>> Settings::drillGroups;

void Settings::RecordPacketDropIngress(uint32_t swId, uint32_t outDev, bool isToR, bool isSpine, bool isCore) {
    if (isToR) {
        // ToR logic (no changes)
        auto itSw = ToRId2UporDownMap.find(swId);
        if (itSw != ToRId2UporDownMap.end()) {
            auto &portMap = itSw->second;
            auto itPort = portMap.find(outDev);
            if (itPort != portMap.end()) {
                if (itPort->second) { // true means uplink
                    dropped_pkt_tor_up_ingress++;
                } else { // false means downlink
                    dropped_pkt_tor_down_ingress++;
                }
            } else {
                std::cerr << "[ERROR] Sw(" << swId << "), unknown port " << outDev
                          << " in ToRId2UporDownMap (Ingress)" << std::endl;
            }
        } else {
            std::cerr << "[ERROR] Sw(" << swId << ") not found in ToRId2UporDownMap (Ingress)" << std::endl;
        }
    } else if (isSpine) {
        // UPDATED Spine logic
        auto itSw = SpineId2UporDownMap.find(swId);
        if (itSw != SpineId2UporDownMap.end()) {
            auto &portMap = itSw->second;
            auto itPort = portMap.find(outDev);
            if (itPort != portMap.end()) {
                if (itPort->second) { // true means uplink (to Core)
                    dropped_pkt_spine_up_ingress++;
                } else { // false means downlink (to ToR)
                    dropped_pkt_spine_down_ingress++;
                }
            } else {
                std::cerr << "[ERROR] Sw(" << swId << "), unknown port " << outDev
                          << " in SpineId2UporDownMap (Ingress)" << std::endl;
            }
        } else {
            std::cerr << "[ERROR] Sw(" << swId << ") not found in SpineId2UporDownMap (Ingress)" << std::endl;
        }
    } else if (isCore) {
        // Core logic (no up/down distinction needed)
        dropped_pkt_core_ingress++;
    } else {
        std::cerr << "[ERROR] Unknown switch type for drop recording at Sw(" << swId << ")" << std::endl;
    }
}

void Settings::RecordPacketDropEgress(uint32_t swId, uint32_t outDev, bool isToR, bool isSpine, bool isCore) {
    if (isToR) {
        // ToR logic (no changes)
        auto itSw = ToRId2UporDownMap.find(swId);
        if (itSw != ToRId2UporDownMap.end()) {
            auto &portMap = itSw->second;
            auto itPort = portMap.find(outDev);
            if (itPort != portMap.end()) {
                if (itPort->second) { // true means uplink
                    dropped_pkt_tor_up_egress++;
                } else { // false means downlink
                    dropped_pkt_tor_down_egress++;
                }
            } else {
                std::cerr << "[ERROR] Sw(" << swId << "), unknown port " << outDev
                          << " in ToRId2UporDownMap (Egress)" << std::endl;
            }
        } else {
            std::cerr << "[ERROR] Sw(" << swId << ") not found in ToRId2UporDownMap (Egress)" << std::endl;
        }
    } else if (isSpine) {
        // UPDATED Spine logic
        auto itSw = SpineId2UporDownMap.find(swId);
        if (itSw != SpineId2UporDownMap.end()) {
            auto &portMap = itSw->second;
            auto itPort = portMap.find(outDev);
            if (itPort != portMap.end()) {
                if (itPort->second) { // true means uplink (to Core)
                    dropped_pkt_spine_up_egress++;
                } else { // false means downlink (to ToR)
                    dropped_pkt_spine_down_egress++;
                }
            } else {
                std::cerr << "[ERROR] Sw(" << swId << "), unknown port " << outDev
                          << " in SpineId2UporDownMap (Egress)" << std::endl;
            }
        } else {
            std::cerr << "[ERROR] Sw(" << swId << ") not found in SpineId2UporDownMap (Egress)" << std::endl;
        }
    } else if (isCore) {
        // Core logic (no up/down distinction needed)
        dropped_pkt_core_egress++;
    } else {
        std::cerr << "[ERROR] Unknown switch type for drop recording at Sw(" << swId << ")" << std::endl;
    }
}

void Settings::RecordOutOfOrderPacket(uint32_t received_seq, uint32_t expected_seq) {
    total_rx_pkt_count++;
    if (received_seq > expected_seq) {
        ooo_pkt_count++;

        uint32_t distance = received_seq - expected_seq;

        reordering_distance_counts[distance]++;
    }
}

}  // namespace ns3
