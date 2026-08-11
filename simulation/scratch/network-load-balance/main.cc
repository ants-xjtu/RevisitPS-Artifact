/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2023 NUS
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation;
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 *
 * Authors: Chahwan Song <skychahwan@gmail.com>
 */

#include <ns3/assert.h>
#include <ns3/rdma-client-helper.h>
#include <ns3/rdma-client.h>
#include <ns3/rdma-driver.h>
#include <ns3/rdma.h>
#include <ns3/sim-setting.h>
#include <ns3/switch-node.h>
#include <time.h>

#include <fstream>
#include <iostream>
#include <sstream>
#include <unordered_map>

#include "ns3/applications-module.h"
#include "ns3/broadcom-node.h"
#include "ns3/conga-routing.h"
#include "ns3/conweave-voq.h"
#include "ns3/core-module.h"
#include "ns3/error-model.h"
#include "ns3/global-route-manager.h"
#include "ns3/internet-module.h"
#include "ns3/ipv4-static-routing-helper.h"
#include "ns3/letflow-routing.h"
#include "ns3/packet.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/qbb-helper.h"
#include "ns3/qbb-net-device.h"
#include "ns3/rdma-hw.h"
#include "ns3/settings.h"
#include "ai-workload-tracker.h"
#include "ai-workload-scheduler.h"

using namespace ns3;
using namespace std;

NS_LOG_COMPONENT_DEFINE("GENERIC_SIMULATION");

/*------Load balancing parameters-----*/
// mode for load balancer, 0: flow ECMP, 1:RPS, 2: DRILL, 3: Conga, 4: Adaptive,
// 5: weighted random, 6: Letflow, 7: drill-weight, 9: ConWeave, 10: SGLB
uint32_t lb_mode = 0;

// mode for adaptive routing, 0: no AR, 1: AR, 2: ARSP (adaptive routing with selective repeat)
uint32_t ar_mode = 0;

// Conga params (based on paper recommendation)
Time conga_flowletTimeout = MicroSeconds(100);  // 100us
Time conga_dreTime = MicroSeconds(50);
Time conga_agingTime = MicroSeconds(500);
uint32_t conga_quantizeBit = 3;
double conga_alpha = 0.2;

// Letflow params
Time letflow_flowletTimeout = MicroSeconds(100);  // 100us
Time letflow_agingTime = MilliSeconds(2);  // just to clear the unused map entries for simul speed

// Conweave params
Time conweave_extraReplyDeadline = MicroSeconds(4);       // additional term to reply deadline
Time conweave_pathPauseTime = MicroSeconds(8);            // time to send packets to congested path
Time conweave_txExpiryTime = MicroSeconds(1000);          // waiting time for CLEAR
Time conweave_extraVOQFlushTime = MicroSeconds(32);       // extra for uncertainty
Time conweave_defaultVOQWaitingTime = MicroSeconds(500);  // default flush timer if no history
bool conweave_pathAwareRerouting = true;

/*------------------------ simulation variables -----------------------------*/
uint64_t one_hop_delay = 1000;  // nanoseconds
uint32_t cc_mode = 1;           // mode for congestion control, 1: DCQCN
uint32_t lanes_per_destination = 4;  // number of lanes per src-dst pair for mode 5 (Per-Lane DCQCN)
bool enable_qcn = true, enable_pfc = true, use_dynamic_pfc_threshold = true;
uint32_t packet_payload_size = 1000, l2_chunk_size = 0, l2_ack_interval = 0;
double pause_time = 5;  // PFC pause, microseconds
double flowgen_start_time = 2.0, flowgen_stop_time = 2.5, simulator_extra_time = 0.1;
uint32_t workload_type = 0; // 0: DCN 1: Alltoall 2: RingAllreduce 3: TreeAllReduce 4: TreeAllReduceChunked 5: AlltoallV
uint64_t ai_message_size = 16000;
std::string ai_message_sizes_file = "none";
uint32_t ai_nodes_per_group = 8;
uint32_t num_rounds = 1;
// Queue length samples are emitted only within this configured time window.
double qlen_mon_start = 2.0;           // seconds
double qlen_mon_end = 2.5;             // seconds
uint32_t switch_mon_interval = 10000;  // ns
uint32_t sglb_remote_mon_interval = 5000;  // ns
uint64_t cnp_mon_start;                // ns
uint64_t cnp_monitor_bucket = 100000;  // ns
uint64_t irn_mon_start;                // ns
uint64_t irn_monitor_bucket = 100000;  // ns

FILE *pfc_file = NULL;
FILE *fct_output = NULL;
FILE *flow_input_stream = NULL;
FILE *cnp_output = NULL;
FILE *est_error_output = NULL;
FILE *voq_output = NULL;
FILE *voq_detail_output = NULL;
FILE *uplink_output = NULL;
FILE *downlink_output = NULL;
FILE *spine_dl_output = NULL;  // spine switches' downlink (Spine->ToR)
FILE *throughput_output = NULL;
FILE *conn_output = NULL;
FILE *flow_drop_output = NULL;  // file to record dropped flow packets
FILE *drop_incast_output = NULL; // file to record incast drop details
FILE *pfc_incast_output = NULL; // file to record incast pfc pause details
FILE *retransmit_output = NULL;  // file to record retransmit
FILE *qlen_output = NULL;  // file to record queue length monitoring

std::string data_rate, link_delay, topology_file, flow_file;
std::string flow_input_file = "flow.txt";
std::string fct_output_file = "fct.txt";
std::string jct_output_file = "jct.txt";
std::string pfc_output_file = "pfc.txt";
std::string cnp_output_file = "cnp.txt";
std::string qlen_mon_file = "qlen.txt";
std::string voq_mon_file = "voq.txt";
std::string voq_mon_detail_file = "voq_detail.txt";
std::string uplink_mon_file = "uplink.txt";
std::string downlink_mon_file = "downlink.txt";
std::string spine_dl_mon_file = "spine_dl.txt";
std::string throughput_mon_file = "throughput.txt";
std::string conn_mon_file = "conn.txt";
std::string est_error_output_file = "est_error.txt";
std::string flow_drop_file = "flow_drop.txt";  // file to record dropped flow packets
std::string drop_incast_file = "drop_incast.txt";
std::string pfc_incast_file = "pfc_incast.txt";
std::string retransmit_file = "retransmit.txt";  // file to record retransmit
std::string weight_file = "";
std::string group_file = "";

// CC params
double alpha_resume_interval = 55, rp_timer = 300, ewma_gain = 1 / 16;
double rate_decrease_interval = 4;
uint32_t fast_recovery_times = 1;
std::string rate_ai, rate_hai, min_rate = "100Mb/s";
std::string dctcp_rate_ai = "1000Mb/s";

bool clamp_target_rate = false, l2_back_to_zero = false;
double error_rate_per_link = 0.0;
uint32_t has_win = 1;
uint32_t window_size = 0;  // 0 means no window, >0 means window size
uint32_t timeout_slowstart_mode = 0;  // 0: no slow start, 1: min slow start, 2: 22 slow start
uint32_t global_t = 1;
uint32_t mi_thresh = 5;
bool var_win = false, fast_react = true;
bool multi_rate = true;
bool sample_feedback = false;
double u_target = 0.95;
uint32_t int_multi = 1;
bool rate_bound = true;
unordered_map<uint64_t, uint32_t> rate2kmax, rate2kmin;
unordered_map<uint64_t, double> rate2pmax;
unordered_map<uint32_t, Ptr<SwitchNode>> idxNodeToR;  // Id -> Ptr

// config of link-down scenario, ACK priority, and buffer
uint64_t link_down_time = 0;
uint32_t link_down_A = 0, link_down_B = 0;
double buffer_size = 0;  // 0: legacy fallback; -1: Tomahawk dynamic per-port allocation; >0: explicit MB/port

// Added from Here
double load = 10.0;
int enable_irn = 0;
int enable_dcp = 0;
int enable_dcp_ack_opt = 0;
int enable_ideal = 0;
int random_seed = 1;  // change this randomly if you want random expt

uint32_t irnRtoHigh = 320; // 320us
uint32_t irnRtoLow = 100;  // 100us

uint64_t maxRtt, maxBdp;

// app parameters
struct Interface {
    uint32_t idx;
    bool up;
    uint64_t delay;
    uint64_t bw;

    Interface() : idx(0), up(false) {}
};
map<Ptr<Node>, map<Ptr<Node>, Interface>> nbr2if;
// Mapping destination to next hop for each node: <node, <dest, <nexthop0, ...> > >
map<Ptr<Node>, map<Ptr<Node>, vector<Ptr<Node>>>> nextHop;
map<Ptr<Node>, map<Ptr<Node>, uint64_t>> pairDelay;
map<Ptr<Node>, map<Ptr<Node>, uint64_t>> pairTxDelay;
map<Ptr<Node>, map<Ptr<Node>, uint64_t>> pairBw;
map<Ptr<Node>, map<Ptr<Node>, uint64_t>> pairBdp;
map<Ptr<Node>, map<Ptr<Node>, uint64_t>> pairRtt;

// for uplink/Downlink monitoring at TOR switches (load balance performance)
std::map<uint32_t, std::vector<uint32_t>> torId2UplinkIf;
std::map<uint32_t, std::vector<uint32_t>> torId2DownlinkIf;
std::map<uint32_t, std::vector<uint32_t>> spineId2UplinkIf;
std::map<uint32_t, std::vector<uint32_t>> spineId2DownlinkIf;
std::map<uint32_t, std::vector<uint32_t>> coreId2DownlinkIf; // Core only has downlinks to Spines

// for host monitoring rdmahw (throughput and good throughput)
std::map<uint32_t, Ptr<RdmaHw>> hostId2RdmaHw;

// input files
std::ifstream topof, flowf;
// std::ifstream weightf;
NodeContainer n;                         // node container
std::vector<Ipv4Address> serverAddress;  // server address

// flow generator
std::unordered_map<uint32_t, uint32_t> flows_per_host;
uint32_t flow_id = 0;
std::unordered_map<uint32_t, uint16_t> portNumber;
std::unordered_map<uint32_t, uint16_t> dportNumber;
uint16_t *port_per_host;

// Scheduling input flows from flow.txt
struct FlowInput {
    uint32_t src, dst, pg, maxPacketCount, port;
    double start_time;
    uint32_t idx;
};
FlowInput flow_input = {0};  // global variable
uint32_t flow_num;

/**
 * Read flow input from file "flowf"
 */
void ReadFlowInput() {
    if (flow_input.idx < flow_num) {
        flowf >> flow_input.src >> flow_input.dst >> flow_input.pg >> flow_input.maxPacketCount >>
            flow_input.start_time;
        assert(n.Get(flow_input.src)->GetNodeType() == 0 &&
               n.Get(flow_input.dst)->GetNodeType() == 0);
        // std::cout << "Flow input: src: " << flow_input.src
        //           << ", dst: " << flow_input.dst
        //           << ", pg: " << flow_input.pg
        //           << ", maxPacketCount: " << flow_input.maxPacketCount
        //           << ", start_time: " << flow_input.start_time
        //           << ", idx: " << flow_input.idx
        //           << std::endl;
    } else {
        std::cout << "*** input flow is over the prefixed number -- flow number : " << flow_num
                  << std::endl;
        std::cout << "*** flow_input.idx : " << flow_input.idx << std::endl;
        std::cout << "*** THIS IS THE LAST FLOW TO SEND :) " << std::endl;
    }
}

/**
 * Scheduling flows given in /config/L_XX....txt file
 */
void ScheduleFlowInputs(FILE *infile) {
    NS_LOG_DEBUG("ScheduleFlowInputs at " << Simulator::Now());
    while (flow_input.idx < flow_num && Seconds(flow_input.start_time) == Simulator::Now()) {
        uint32_t pg, src, dst, sport, dport, maxPacketCount, target_len;
        pg = flow_input.pg;
        src = flow_input.src;
        dst = flow_input.dst;

        // src port
        sport = portNumber[src];  // get a new port number
        portNumber[src] = portNumber[src] + 1;

        // dst port
        dport = dportNumber[dst];
        dportNumber[dst] = dportNumber[dst] + 1;

        target_len = flow_input.maxPacketCount;  // this is actually not packet-count, but bytes
        if (target_len == 0) {
            target_len = 1;
        }
        assert(n.Get(src)->GetNodeType() == 0 && n.Get(dst)->GetNodeType() == 0);

        /**
         * Turn on if you want to record all input streams into output file for logging.
         * But, the input stream can be found in config. We do not recommend to do this
         * as it consumes storage resource, redundantly.
         */
        if (0) {  // logging input streams to "XXXX_out_in.txt"
            /************************
             * record flow's 4-tuple
             ************************/
            fprintf(infile, "%u %u %u %u %u %lu\n", src, dst, sport, dport, target_len,
                    (uint64_t)(flow_input.start_time * (uint64_t)1000000000));
            fflush(infile);

            /***********    FCT Tracking    **************/
            UdpServerHelper server0(dport);
            server0.SetAttribute("FlowSize", UintegerValue(target_len));
            server0.SetAttribute("irn", BooleanValue(enable_irn));
            server0.SetAttribute("StatHostSrc", UintegerValue(src));
            server0.SetAttribute("StatHostDst", UintegerValue(dst));
            server0.SetAttribute("StatRxLen", UintegerValue(target_len));
            server0.SetAttribute("StatFlowID", UintegerValue(flow_input.idx));
            server0.SetAttribute("Port", UintegerValue(dport));

            ApplicationContainer apps0s = server0.Install(n.Get(dst));  // DST
            apps0s.Start(Seconds(Time(0)));
            apps0s.Stop(Seconds(100.0));
        }  // end of logging input streams

        if (pairRtt.find(n.Get(src)) == pairRtt.end() ||
            pairRtt[n.Get(src)].find(n.Get(dst)) == pairRtt[n.Get(src)].end()) {
            std::cerr << "pairRtt src: " << src << " -> dst: " << dst
                      << " ==> cannot be found from database" << std::endl;
            assert(false);
        }

        // RdmaClientHelper clientHelper(
        //     pg, serverAddress[src], serverAddress[dst], sport, dport, target_len,
        //     has_win ? (global_t == 1 ? maxBdp : pairBdp[n.Get(src)][n.Get(dst)]) : 0,
        //     global_t == 1 ? maxRtt : pairRtt[n.Get(src)][n.Get(dst)]);
        uint32_t window_arg = 0;
        if(has_win) {
            if(window_size > 0) {
                window_arg = window_size;
            } else {
                window_arg = (global_t == 1 ? maxBdp : pairBdp[n.Get(src)][n.Get(dst)]);
            }
        }
        // std::cout << "window_arg: " << window_arg << std::endl;

        RdmaClientHelper clientHelper(
            pg, serverAddress[src], serverAddress[dst], sport, dport, target_len,
            window_arg,
            global_t == 1 ? maxRtt : pairRtt[n.Get(src)][n.Get(dst)]);
        clientHelper.SetAttribute("StatFlowID", IntegerValue(flow_input.idx));

        ApplicationContainer appCon = clientHelper.Install(n.Get(src));  // SRC
        appCon.Start(Seconds(Time(0)));
        appCon.Stop(Seconds(100.0));

        flow_input.idx++;
        ReadFlowInput();
    }

    // schedule the next time to run this function
    if (flow_input.idx < flow_num) {
        Simulator::Schedule(Seconds(flow_input.start_time) - Simulator::Now(), &ScheduleFlowInputs,
                            infile);
    } else {  // no more flows, close the file
        flowf.close();
    }
}

/**
 * @brief CNP frequency monitoring (timestamp nodeId ECN OoO Total)
 */
void cnp_freq_monitoring(FILE *fout, Ptr<RdmaHw> rdmahw) {
    if (rdmahw->cnp_total > 0) {
        // flush
        fprintf(fout, "%lu %u %u %u %u\n", Simulator::Now().GetNanoSeconds(),
                rdmahw->m_node->GetId(), rdmahw->cnp_by_ecn, rdmahw->cnp_by_ooo, rdmahw->cnp_total);
        fflush(fout);

        // initialize
        rdmahw->cnp_by_ecn = 0;
        rdmahw->cnp_by_ooo = 0;
        rdmahw->cnp_total = 0;
    }

    // recursive callback
    Simulator::Schedule(NanoSeconds(cnp_monitor_bucket), &cnp_freq_monitoring, fout, rdmahw);
}

void qlen_print()
{
    Time now = Simulator::Now();
    if (now < Seconds(qlen_mon_start) || now > Seconds(qlen_mon_end)) {
        return;
    }
    if (qlen_output) {
        for (uint32_t i = 0; i < Settings::node_num; i++) {
            if (n.Get(i)->GetNodeType() == 1) {  // is server
                Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(i));
                uint32_t nports = sw->GetNDevices();
                for (uint32_t j = 1; j < nports; j++) {
                    // 假设 egress queue index 同样为 3
                    uint32_t qIndex = 3; 

                    // 修改了 fprintf 格式化字符串，并增加了新的输出项
                    fprintf(qlen_output, "%lu,%u,%u,%u,%u,%u\n", 
                            now.GetNanoSeconds(),
                            i,                                  // node id
                            j,                                  // port id
                            sw->m_mmu->m_usedIngressPGBytes[j][qIndex],
                            sw->m_mmu->DynamicThreshold(j, qIndex),
                            sw->m_mmu->m_usedEgressQSharedBytes[j][qIndex]); // 新增的 Egress queue 输出
                    
                    fflush(qlen_output);
                }
            }
        }
    }
}

void sglb_remote_queue_monitoring() {
    uint64_t now = Simulator::Now().GetNanoSeconds();
    for (std::map<uint32_t, std::map<uint32_t, uint32_t>>::const_iterator spineIt =
             Settings::spineToLeafOutPort.begin();
         spineIt != Settings::spineToLeafOutPort.end(); ++spineIt) {
        uint32_t spineId = spineIt->first;
        Ptr<SwitchNode> swNode = DynamicCast<SwitchNode>(n.Get(spineId));
        if (swNode == 0 || !swNode->m_isSpine) {
            continue;
        }

        for (std::map<uint32_t, uint32_t>::const_iterator leafIt = spineIt->second.begin();
             leafIt != spineIt->second.end(); ++leafIt) {
            uint32_t dstLeafId = leafIt->first;
            uint32_t outPort = leafIt->second;
            if (outPort == 0 || outPort >= swNode->GetNDevices()) {
                continue;
            }

            Ptr<QbbNetDevice> device = DynamicCast<QbbNetDevice>(swNode->GetDevice(outPort));
            if (device == 0 || device->GetQueue() == 0) {
                continue;
            }

            Settings::SglbRemoteState &state = Settings::sglbRemoteStates[spineId][dstLeafId];
            state.remoteQueueBytes = device->GetQueue()->GetNBytesTotal();
            state.lastUpdateNs = now;
        }
    }

    if (Simulator::Now() < Seconds(flowgen_stop_time + 10.00)) {
        Simulator::Schedule(NanoSeconds(sglb_remote_mon_interval), &sglb_remote_queue_monitoring);
    }
}
/**
 * @brief TOR Switch monitoring
 * - VOQ number and uplink throughput at switches
 * - the number of active connections at RNICS
 */
void periodic_monitoring(FILE *fout_voq, FILE *fout_voq_detail, FILE *fout_uplink, FILE *fout_conn,
                         uint32_t *lb_mode) {
    uint32_t lb_mode_val = *lb_mode;
    uint64_t now = Simulator::Now().GetNanoSeconds();
    for (const auto &tor2If : torId2UplinkIf) {  // for each TOR switches
        Ptr<Node> node = n.Get(tor2If.first);    // tor id
        auto swNode = DynamicCast<SwitchNode>(node);
        assert(swNode->m_isToR == true);  // sanity check

        if (lb_mode_val == 9) {  // Conweave
            // monitor VOQ number per switch <time, ToRId, #VOQ, #Pkts>
            uint32_t nVOQ = swNode->m_mmu->m_conweaveRouting.GetNumVOQ();
            uint32_t nVolumeVOQ = swNode->m_mmu->m_conweaveRouting.GetVolumeVOQ();
            fprintf(fout_voq, "%lu,%u,%u,%u\n", now, tor2If.first, nVOQ, nVolumeVOQ);

            // monitor VOQ per destination IP <time, dstip, #VOQ, #Pkts>
            std::unordered_map<uint32_t, std::pair<uint32_t, uint32_t>> dip_to_nvoq_npkt;
            for (auto voq : swNode->m_mmu->m_conweaveRouting.GetVOQMap()) {
                auto &nvoq_npkt = dip_to_nvoq_npkt[voq.second.getDIP()];
                nvoq_npkt.first += 1;
                nvoq_npkt.second += voq.second.getQueueSize();
            }
            for (auto x : dip_to_nvoq_npkt) {
                fprintf(fout_voq_detail, "%lu,%u,%u,%u\n", now, x.first, x.second.first,
                        x.second.second);
            }
        }

        // common: monitor TOR's uplink to measure load balancing performance
        for (const auto &iface : tor2If.second) {
            // monitor uplink txBytes <time, ToRId, OutDev, Bytes, LinkBps>
            uint64_t uplink_txbyte = swNode->GetTxBytesOutDev(iface);
            uint64_t link_bps =
                DynamicCast<QbbNetDevice>(swNode->GetDevice(iface))->GetDataRate().GetBitRate();
            fprintf(fout_uplink, "%lu,%u,%u,%lu,%lu\n", now, tor2If.first, iface, uplink_txbyte,
                    link_bps);
        }
    }
    // common: monitor TOR's downlink to measure load balancing performance
    for (const auto &tor_item : torId2DownlinkIf) {
        uint32_t tor_id = tor_item.first;
        const auto &downlink_interfaces = tor_item.second;

        // 通过 ToR ID 获取交换机节点对象
        Ptr<Node> node = n.Get(tor_id);
        auto swNode = DynamicCast<SwitchNode>(node);

        // 遍历该 ToR 的每一个下行链路接口
        for (const auto &iface : downlink_interfaces) {
            // 监控 downlink txBytes <time, ToRId, OutDev, Bytes, LinkBps>
            uint64_t downlink_txbyte = swNode->GetTxBytesOutDev(iface);
            uint64_t link_bps =
                DynamicCast<QbbNetDevice>(swNode->GetDevice(iface))->GetDataRate().GetBitRate();
            fprintf(downlink_output, "%lu,%u,%u,%lu,%lu\n", now, tor_id, iface, downlink_txbyte,
                    link_bps);
        }
    }

    // Monitor Spine switches' downlink (Spine->ToR direction) for Spine-ToR link utilization
    // Format: <time, SpineId, OutDev, Bytes, LinkBps>
    for (const auto &spine_item : spineId2DownlinkIf) {
        uint32_t spine_id = spine_item.first;
        Ptr<Node> node = n.Get(spine_id);
        auto swNode = DynamicCast<SwitchNode>(node);
        for (const auto &iface : spine_item.second) {
            uint64_t txbyte = swNode->GetTxBytesOutDev(iface);
            uint64_t link_bps =
                DynamicCast<QbbNetDevice>(swNode->GetDevice(iface))->GetDataRate().GetBitRate();
            fprintf(spine_dl_output, "%lu,%u,%u,%lu,%lu\n", now, spine_id, iface, txbyte, link_bps);
        }
    }

    // common: get number of concurrent connections at each server
    for (uint32_t i = 0; i < Settings::node_num; i++) {
        if (n.Get(i)->GetNodeType() == 0) {  // is server
            Ptr<Node> server = n.Get(i);
            Ptr<RdmaDriver> rdmaDriver = server->GetObject<RdmaDriver>();
            Ptr<RdmaHw> rdmaHw = rdmaDriver->m_rdma;
            // monitor total/active QP number <time, serverId, #ExistingQP, #ActiveQP>
            uint64_t nQP = rdmaHw->m_qpMap.size();
            uint64_t nActiveQP = 0;
            for (auto qp : rdmaHw->m_qpMap) {
                if (qp.second->GetBytesLeft() > 0) {  // conns with bytes left
                    nActiveQP++;
                }
            }
            fprintf(fout_conn, "%lu,%u,%lu,%lu\n", now, i, nQP, nActiveQP);

            // monitor throughput <time, serverId, sentBytes, ackedBytes>
            uint64_t sent = rdmaHw->m_accSentBytes;
            uint64_t acked = rdmaHw->m_accAckedBytes;
            fprintf(throughput_output, "%lu,%u,%lu,%lu\n", now, i, sent, acked);
        }
    }

    qlen_print();
    if (Simulator::Now() < Seconds(flowgen_stop_time + 10.00)) {
        // recursive callback
        Simulator::Schedule(NanoSeconds(switch_mon_interval), &periodic_monitoring, fout_voq,
                            fout_voq_detail, fout_uplink, fout_conn, lb_mode);  // every 10us
    }
    return;
}

/**
 * @brief Conga timeout number recording
 */
void conga_history_print() {
    std::cout << "\n------------CONGA History---------------" << std::endl;
    std::cout << "Number of flowlet's timeout:" << CongaRouting::nFlowletTimeout
              << "Conga's timeout: " << conga_flowletTimeout << std::endl;
}

/**
 * @brief Letflow timeout number recording
 */
void letflow_history_print() {
    std::cout << "\n------------Letflow History---------------" << std::endl;
    std::cout << "Number of flowlet's timeout:" << LetflowRouting::nFlowletTimeout
              << "\nLetflow's timeout: " << letflow_flowletTimeout << std::endl;
}

/**
 * @brief Conweave rerouting/VOQ number recording
 */
void conweave_history_print() {
    // Conweave params
    std::cout << "\n------ConWeave parameters-----" << std::endl;
    std::cout << "Param - extraReplyDeadline:" << conweave_extraReplyDeadline << std::endl;
    std::cout << "Param - extraVOQFlushTime:" << conweave_extraVOQFlushTime << std::endl;
    std::cout << "Param - txExpiryTime:" << conweave_txExpiryTime << std::endl;
    std::cout << "Param - defaultVOQWaitingTime:" << conweave_defaultVOQWaitingTime << std::endl;
    std::cout << "Param - pathPauseTime:" << conweave_pathPauseTime << std::endl;
    std::cout << "Param - pathAwareRerouting:" << conweave_pathAwareRerouting << std::endl;

    std::cout << "\n------------ConWeave History---------------" << std::endl;
    std::cout << "Number of INIT's Reply sent (RTT_REPLY):" << ConWeaveRouting::m_nReplyInitSent
              << "\nNumber of Timely RTT_REPLY (INIT's Reply):" << ConWeaveRouting::m_nTimelyInitReplied
              << "\nNumber of TAIL's Reply Sent (CLEAR):" << ConWeaveRouting::m_nReplyTailSent
              << "\nNumber of Timely CLEAR (TAIL's Reply):" << ConWeaveRouting::m_nTimelyTailReplied
              << "\nNumber of NOTIFY Sent:" << ConWeaveRouting::m_nNotifySent
              << "\nNumber of Rerouting:" << ConWeaveRouting::m_nReRoute
              << "\nNumber of OoO enqueued pkts:" << ConWeaveRouting::m_nOutOfOrderPkts
              << "\nNumber of VOQ Flush Total:" << ConWeaveRouting::m_nFlushVOQTotal
              << "\nNumber of VOQ Flush From History:" << ConWeaveRouting::m_historyVOQSize.size()
              << "\nNumber of VOQ Flush by TAIL:" << ConWeaveRouting::m_nFlushVOQByTail
              << std::endl;

    std::cout << "--------------------------" << std::endl;

    /** VOQ: Sanity check*/
    for (size_t ToRId = 0; ToRId < Settings::node_num; ToRId++) {
        Ptr<Node> node = n.Get(ToRId);
        if (node->GetNodeType() == 1) {  // switches
            auto swNode = DynamicCast<SwitchNode>(n.Get(ToRId));
            if (swNode->m_isToR) {  // TOR switch
                uint32_t num_remained_voq = swNode->m_mmu->m_conweaveRouting.GetNumVOQ();
                if (num_remained_voq > 0) {
                    printf("*******************************\n");
                    printf("*** WARNING - Tor Sw (%lu) - VOQ (num=%u) is not flushed yet!! ***\n",
                           ToRId, num_remained_voq);
                    printf(
                        " -- Probably the history print is too early so simulation might not be "
                        "finished?");
                    printf("********************************\n");
                }
            }
        }
    }

    /** Get ConWeave Flush Time Estimation Error */
    if (0) {
        // sanity check - extraVOQFlushTime must be large enough to get accuracy
        assert(conweave_extraVOQFlushTime >= MicroSeconds(128) && "PARAMETER ERROR!!");

        std::cout << "\n--------------------------" << std::endl;
        std::cout << "Extracting ConWeave Estimation Error Data..." << std::endl;
        est_error_output = fopen(est_error_output_file.c_str(), "w");
        for (auto x : ConWeaveVOQ::m_flushEstErrorhistory) {
            fprintf(est_error_output, "%d\n", x);
        }
        ConWeaveVOQ::m_flushEstErrorhistory.clear();
        std::cout << "---------D O N E---------" << std::endl;
    }
}

/**
 * @brief Trace flow drop times
 */
void flow_drop_trace(FILE *fout, const DropEventInfo &info) {
    // 為了方便，我們先從 info 物件中取出 CustomHeader
    const CustomHeader &ch = info.droppedPacketHeader;
    
    uint16_t sport = 0, dport = 0;

    if (ch.l3Prot == 0x6) {  // TCP
        sport = ch.tcp.sport;
        dport = ch.tcp.dport;
    } else if (ch.l3Prot == 0x11) {  // UDP
        sport = ch.udp.sport;
        dport = ch.udp.dport;
    } else if (ch.l3Prot == 0xFC || ch.l3Prot == 0xFD) {  // ACK / NACK
        sport = ch.ack.sport;
        dport = ch.ack.dport;
    } else {
        // 這部分保持不變
        fprintf(fout, "[WARN] Unsupported l3Prot: %d\n", static_cast<int>(ch.l3Prot));
        return;
    }

    Ipv4Address sipAddr = Ipv4Address(ch.sip);
    Ipv4Address dipAddr = Ipv4Address(ch.dip);
    uint32_t sid = Settings::ip_to_node_id(sipAddr);
    uint32_t did = Settings::ip_to_node_id(dipAddr);

    // 【新增】邏輯：將 switchType (uint) 轉換為字串
    const char* switchTypeStr = "UNKNOWN";
    switch (info.switchType) {
        case 1: switchTypeStr = "TOR"; break;
        case 2: switchTypeStr = "SPINE"; break;
        case 3: switchTypeStr = "CORE"; break;
    }

    // 【新增】邏輯：判斷鏈路方向 (Uplink/Downlink)
    const char* linkDirection = "UNKNOWN";
    const uint32_t switchId = info.nodeId;
    const uint32_t portId = info.deviceId;
    
    switch (info.switchType) {
        case 1: // ToR
            if (torId2UplinkIf.count(switchId)) {
                auto const& uplinks = torId2UplinkIf.at(switchId);
                if (std::find(uplinks.begin(), uplinks.end(), portId) != uplinks.end()) {
                    linkDirection = "UPLINK";
                }
            }
            if (torId2DownlinkIf.count(switchId)) {
                auto const& downlinks = torId2DownlinkIf.at(switchId);
                if (std::find(downlinks.begin(), downlinks.end(), portId) != downlinks.end()) {
                    linkDirection = "DOWNLINK";
                }
            }
            break;
        case 2: // Spine
            if (spineId2UplinkIf.count(switchId)) {
                auto const& uplinks = spineId2UplinkIf.at(switchId);
                if (std::find(uplinks.begin(), uplinks.end(), portId) != uplinks.end()) {
                    linkDirection = "UPLINK";
                }
            }
            if (spineId2DownlinkIf.count(switchId)) {
                auto const& downlinks = spineId2DownlinkIf.at(switchId);
                if (std::find(downlinks.begin(), downlinks.end(), portId) != downlinks.end()) {
                    linkDirection = "DOWNLINK";
                }
            }
            break;
        case 3: // Core
            if (coreId2DownlinkIf.count(switchId)) {
                auto const& downlinks = coreId2DownlinkIf.at(switchId);
                if (std::find(downlinks.begin(), downlinks.end(), portId) != downlinks.end()) {
                    linkDirection = "DOWNLINK"; // Core 只有 Downlink
                }
            }
            break;
    }


    // TAG,SwitchID,SwitchType,LinkDirection,DropReason,Port,IncastFlows,IncastSrcs,SIP,DIP,SID,DID,Sport,Dport,Proto,Timestamp
    fprintf(fout, "DROP,%u,%s,%s,%s,%u,%zu,%zu,%u,%u,%u,%u,%u,%u,%lu,%lu\n",
            info.nodeId,                      // 發生丟包的交換機 ID
            switchTypeStr,                    // 【新】交換機類型 (TOR, SPINE, CORE)
            linkDirection,                    // 【新】鏈路方向 (UPLINK, DOWNLINK)
            info.isIngressDrop ? "INGRESS" : "EGRESS", // 丟包原因
            info.deviceId,                    // 擁塞的埠 ID
            info.incastFlowCount,             // Incast Flow 數量
            info.uniqueSrcIpCount,            // 獨立源 IP 數量
            ch.sip,
            ch.dip,
            sid,
            did,
            sport,
            dport,
            static_cast<unsigned long>(ch.l3Prot),
            static_cast<unsigned long>(Simulator::Now().GetNanoSeconds()));

    fflush(fout);
}

void flow_pfc_trace(FILE *fout, const PfcPauseEventInfo &info) {
    // 步驟 1: 將 switchType (uint) 轉換為字串 (與 flow_drop_trace 相同)
    const char* switchTypeStr = "UNKNOWN";
    switch (info.switchType) {
        case 1: switchTypeStr = "TOR"; break;
        case 2: switchTypeStr = "SPINE"; break;
        case 3: switchTypeStr = "CORE"; break;
    }

    // 步驟 2: 判斷最擁塞 Egress Port 的鏈路方向 (Uplink/Downlink)
    // 邏輯與 flow_drop_trace 類似，但我們關心的是 congestedEgDev 的方向
    const char* linkDirection = "UNKNOWN";
    const uint32_t switchId = info.nodeId;
    const uint32_t portId = info.congestedEgDev; // 使用最擁塞的 Egress Port ID
    
    switch (info.switchType) {
        case 1: // ToR
            if (torId2UplinkIf.count(switchId)) {
                auto const& uplinks = torId2UplinkIf.at(switchId);
                if (std::find(uplinks.begin(), uplinks.end(), portId) != uplinks.end()) {
                    linkDirection = "UPLINK";
                }
            }
            if (torId2DownlinkIf.count(switchId)) {
                auto const& downlinks = torId2DownlinkIf.at(switchId);
                if (std::find(downlinks.begin(), downlinks.end(), portId) != downlinks.end()) {
                    linkDirection = "DOWNLINK";
                }
            }
            break;
        case 2: // Spine
            if (spineId2UplinkIf.count(switchId)) {
                auto const& uplinks = spineId2UplinkIf.at(switchId);
                if (std::find(uplinks.begin(), uplinks.end(), portId) != uplinks.end()) {
                    linkDirection = "UPLINK";
                }
            }
            if (spineId2DownlinkIf.count(switchId)) {
                auto const& downlinks = spineId2DownlinkIf.at(switchId);
                if (std::find(downlinks.begin(), downlinks.end(), portId) != downlinks.end()) {
                    linkDirection = "DOWNLINK";
                }
            }
            break;
        case 3: // Core
            if (coreId2DownlinkIf.count(switchId)) {
                auto const& downlinks = coreId2DownlinkIf.at(switchId);
                if (std::find(downlinks.begin(), downlinks.end(), portId) != downlinks.end()) {
                    linkDirection = "DOWNLINK"; // Core 只有 Downlink
                }
            }
            break;
    }

    // 步驟 3: 格式化並輸出 PFC 擁塞事件
    // TAG,SwitchID,SwitchType,LinkDirection,TriggerInPort,CongestedEgPort,QueueBytes,IncastFlows,IncastSrcs,Timestamp
    fprintf(fout, "PFC,%u,%s,%s,%u,%u,%u,%zu,%zu,%lu\n",
            info.nodeId,              // 發生 PFC 的交換機 ID
            switchTypeStr,            // 交換機類型 (TOR, SPINE, CORE)
            linkDirection,            // 最擁塞 Egress 埠的鏈路方向 (UPLINK, DOWNLINK)
            info.triggeringInDev,     // 觸發 PFC 的 Ingress Port ID
            info.congestedEgDev,      // 最擁塞的 Egress Port ID
            info.maxQueueLength,      // 最擁塞 Egress 埠的佇列長度 (Bytes)
            info.incastFlowCount,     // Incast Flow 數量
            info.uniqueSrcIpCount,    // 獨立源 IP 數量
            static_cast<unsigned long>(Simulator::Now().GetNanoSeconds()));

    fflush(fout);
}


/**
 * @brief Trace function for retransmitted packets. Output SIP/DIP/PORTs and timestamps.
 */
void retransmit_trace(FILE* fout, Ptr<RdmaQueuePair> q) {
    uint32_t sid = Settings::ip_to_node_id(q->sip);
    uint32_t did = Settings::ip_to_node_id(q->dip);

    fprintf(fout, "%u %u %u %u %u %u %lu %lu\n",
            q->sip.Get(), q->dip.Get(),     // Source and Destination IP
            sid, did,                       // Source and Destination node ID
            q->sport, q->dport,             // Source and Destination port
            q->startTime.GetTimeStep(),     // Start time of the flow
            Simulator::Now().GetTimeStep()  // Current timestamp (i.e., retransmit time)
    );

    fflush(fout);  // flush to file immediately
}


/**
 * @brief When one RDMA is finished, so does (1) QP, (2) RxQP, (3) write it on file fct.txt.
 */
void qp_finish(FILE *fout, Ptr<RdmaQueuePair> q) {
    WorkloadTracker::GetInstance().OnFlowComplete(q);
    uint32_t sid = Settings::ip_to_node_id(q->sip), did = Settings::ip_to_node_id(q->dip);
    uint64_t base_rtt = pairRtt[n.Get(sid)][n.Get(did)];
    uint64_t b = pairBw[n.Get(sid)][n.Get(did)];
    uint32_t total_bytes =
        q->m_size + ((q->m_size - 1) / packet_payload_size + 1) *
                        (CustomHeader::GetStaticWholeHeaderSize() -
                         IntHeader::GetStaticSize());  // translate to the minimum bytes required
                                                       // (with header but no INT)
    uint64_t standalone_fct = base_rtt + total_bytes * 8000000000lu / b;

    // XXX: remove rxQP from the receiver
    Ptr<Node> dstNode = n.Get(did);
    Ptr<RdmaDriver> rdma = dstNode->GetObject<RdmaDriver>();
    rdma->m_rdma->DeleteRxQp(q->sip.Get(), q->sport, q->dport, q->m_pg);

    // fprintf(fout, "%lu QP complete\n", Simulator::Now().GetTimeStep());
    fprintf(fout, "%u %u %u %u %lu %lu %lu %lu %u\n", Settings::ip_to_node_id(q->sip),
            Settings::ip_to_node_id(q->dip), q->sport, q->dport, q->m_size,
            q->startTime.GetTimeStep(), (Simulator::Now() - q->startTime).GetTimeStep(),
            standalone_fct, q->m_timeoutRetransmitCount);

    // for debugging
    NS_LOG_DEBUG("%u %u %u %u %lu %lu %lu %lu\n" %
                 (Settings::ip_to_node_id(q->sip), Settings::ip_to_node_id(q->dip), q->sport,
                  q->dport, q->m_size, q->startTime.GetTimeStep(),
                  (Simulator::Now() - q->startTime).GetTimeStep(), standalone_fct));
    Settings::cnt_finished_flows++;
    fflush(fout);
}

/**
 * @brief PFC event logging
 */
void get_pfc(FILE *fout, Ptr<QbbNetDevice> dev, uint32_t type) {
    // time, nodeID, nodeType, Interface's Idx, 0:resume, 1:pause
    fprintf(fout, "%lu %u %u %u %u\n", Simulator::Now().GetTimeStep(), dev->GetNode()->GetId(),
            dev->GetNode()->GetNodeType(), dev->GetIfIndex(), type);
}

/*******************************************************************/
#if (false)

/**
 * @brief Qlen monitoring at switches (output: qlen.txt), I think "periodically"...
 *
 */
struct QlenDistribution {
    vector<uint32_t> cnt;  // cnt[i] is the number of times that the queue len is i KB
    void add(uint32_t qlen) {
        uint32_t kb = qlen / 1000;
        if (cnt.size() < kb + 1) cnt.resize(kb + 1);
        cnt[kb]++;
    }
};

map<uint32_t, map<uint32_t, QlenDistribution>> queue_result;

void monitor_buffer(FILE *qlen_output, NodeContainer *n) {
    /*******************************************************************/
    /************************** UNUSED NOW *****************************/
    /*******************************************************************/
    for (uint32_t i = 0; i < n->GetN(); i++) {
        if (n->Get(i)->GetNodeType() == 1) {  // is switch
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n->Get(i));
            if (queue_result.find(i) == queue_result.end()) queue_result[i];
            for (uint32_t j = 1; j < sw->GetNDevices(); j++) {
                uint32_t size = 0;
                for (uint32_t k = 0; k < SwitchMmu::qCnt; k++)
                    size += sw->m_mmu->egress_bytes[j][k];
                queue_result[i][j].add(size);
            }
        }
    }
    if (Simulator::Now().GetTimeStep() % qlen_dump_interval == 0) {
        fprintf(qlen_output, "time: %lu\n", Simulator::Now().GetTimeStep());
        for (auto &it0 : queue_result) {
            for (auto &it1 : it0.second) {
                fprintf(qlen_output, "%u %u", it0.first, it1.first);
                auto &dist = it1.second.cnt;
                for (uint32_t i = 0; i < dist.size(); i++) fprintf(qlen_output, " %u", dist[i]);
                fprintf(qlen_output, "\n");
            }
        }
        fflush(qlen_output);
    }
    if (Simulator::Now() < Seconds(qlen_mon_end))
        Simulator::Schedule(NanoSeconds(qlen_mon_interval), &monitor_buffer, qlen_output, n);
}
#endif
/*******************************************************************/


void PrintDropStatistics(FILE* output) {
    if (!output) return;

    // Calculate totals
    uint32_t tor_up_total = Settings::dropped_pkt_tor_up_ingress + Settings::dropped_pkt_tor_up_egress;
    uint32_t tor_down_total = Settings::dropped_pkt_tor_down_ingress + Settings::dropped_pkt_tor_down_egress;
    uint32_t spine_up_total = Settings::dropped_pkt_spine_up_ingress + Settings::dropped_pkt_spine_up_egress;
    uint32_t spine_down_total = Settings::dropped_pkt_spine_down_ingress + Settings::dropped_pkt_spine_down_egress;
    uint32_t core_total = Settings::dropped_pkt_core_ingress + Settings::dropped_pkt_core_egress;

    fprintf(output, "========== Drop Statistics ==========\n");

    // ➤ ToR Drops
    fprintf(output, "\n[ToR Switches]\n");
    fprintf(output, "  Up Ingress Drops   : %u\n", Settings::dropped_pkt_tor_up_ingress);
    fprintf(output, "  Up Egress Drops    : %u\n", Settings::dropped_pkt_tor_up_egress);
    fprintf(output, "  -> Up Total        : %u\n", tor_up_total);
    fprintf(output, "  Down Ingress Drops : %u\n", Settings::dropped_pkt_tor_down_ingress);
    fprintf(output, "  Down Egress Drops  : %u\n", Settings::dropped_pkt_tor_down_egress);
    fprintf(output, "  -> Down Total      : %u\n", tor_down_total);

    // ➤ Spine Drops
    fprintf(output, "\n[Spine Switches]\n");
    fprintf(output, "  Up Ingress Drops   : %u\n", Settings::dropped_pkt_spine_up_ingress);
    fprintf(output, "  Up Egress Drops    : %u\n", Settings::dropped_pkt_spine_up_egress);
    fprintf(output, "  -> Up Total        : %u\n", spine_up_total);
    fprintf(output, "  Down Ingress Drops : %u\n", Settings::dropped_pkt_spine_down_ingress);
    fprintf(output, "  Down Egress Drops  : %u\n", Settings::dropped_pkt_spine_down_egress);
    fprintf(output, "  -> Down Total      : %u\n", spine_down_total);

    // ➤ Core Drops
    fprintf(output, "\n[Core Switches]\n");
    fprintf(output, "  Ingress Drops      : %u\n", Settings::dropped_pkt_core_ingress);
    fprintf(output, "  Egress Drops       : %u\n", Settings::dropped_pkt_core_egress);
    fprintf(output, "  -> Total           : %u\n", core_total);

    // ➤ Other Events
    fprintf(output, "\n[Other Events]\n");
    fprintf(output, "  Ideal Dropped      : %u\n", Settings::ideal_drop_pkt_count);
    fprintf(output, "  Packets Trimmed    : %u\n", Settings::trimmed_pkt_count);
    fprintf(output, "  Corruption/Error   : %u\n", Settings::dropped_pkt_error);
    fprintf(output, "  AR Retx w/ Drop    : %lu\n", Settings::ar_retransmissions_with_drop);
    fprintf(output, "  AR Retx Spurious   : %lu\n", Settings::ar_spurious_retransmissions);

    fprintf(output, "\n\n========== Out-of-Order Packet Statistics ==========\n");

    // --- Section 1: 整體統計數據 ---
    fprintf(output, "[OOO Overall Stats]\n");
    fprintf(output, "# total_rx_packets,ooo_packets,ooo_rate\n");
    if (Settings::total_rx_pkt_count > 0) {
        double ooo_rate = (double)Settings::ooo_pkt_count / Settings::total_rx_pkt_count;
        fprintf(output, "%lu,%lu,%.6f\n", 
                Settings::total_rx_pkt_count, 
                Settings::ooo_pkt_count, 
                ooo_rate);
    } else {
        fprintf(output, "%lu,%lu,0.0\n", 
                Settings::total_rx_pkt_count, 
                Settings::ooo_pkt_count);
    }
    fprintf(output, "[End Of Section]\n\n");

    // --- Section 2: 亂序距離分佈 ---
    fprintf(output, "[OOO Reordering Distance CDF]\n");
    fprintf(output, "# distance,count\n");
    for (const auto& pair : Settings::reordering_distance_counts) {
        fprintf(output, "%u,%lu\n", pair.first, pair.second);
    }
    fprintf(output, "[End Of Section]\n\n");

    // --- Section 3: 亂序叢集大小分佈 ---
    fprintf(output, "[OOO Burst Size CDF]\n");
    fprintf(output, "# burst_size,occurrences\n");
    for (const auto& pair : Settings::ooo_burst_size_counts) {
        fprintf(output, "%u,%lu\n", pair.first, pair.second);
    }
    fprintf(output, "[End Of Section]\n\n");

    fprintf(output, "=====================================\n");

    fflush(output);
}

/**
 * @brief Stop simulation in the middle (when almost all flows are done).
 * This function allows to finish simulation quickly when all messages are sent.
 */
void stop_simulation_middle() {
    uint32_t target_flow_num = flow_num - 0;  // can be lower than flownum
    if (Settings::cnt_finished_flows >= target_flow_num) {
        std::cout << "\n*** Simulator is enforced to be finished, finished so far: "
                  << Settings::cnt_finished_flows << "/ total: " << target_flow_num
                  << ", Time:" << Simulator::Now() << std::endl;

        // schedule conga timeout monitor
        if (lb_mode == 3) {  // CONGA
            conga_history_print();
        }
        if (lb_mode == 6) {  // LETFLOW
            letflow_history_print();
        }
        if (lb_mode == 9) {  // CONWEAVE
            conweave_history_print();
        }
        // 🟡 写入 drop 信息
        PrintDropStatistics(flow_drop_output);
        Simulator::Stop(NanoSeconds(1));  // finish soon, stop this schedule (NECESSARY!)
        return;
    }

    Simulator::Schedule(MicroSeconds(100), &stop_simulation_middle);  // check every 100us
}

/**
 * @brief Calculate edge-to-edge delays, TX delays, and bandwidths
 */
void CalculateRoute(Ptr<Node> host) {
    // queue for the BFS.
    vector<Ptr<Node>> q;
    // Distance from the host to each node.
    map<Ptr<Node>, int> dis;
    map<Ptr<Node>, uint64_t> delay;
    map<Ptr<Node>, uint64_t> txDelay;
    map<Ptr<Node>, uint64_t> bw;
    // init BFS.
    q.push_back(host);
    dis[host] = 0;
    delay[host] = 0;
    txDelay[host] = 0;
    bw[host] = 0xfffffffffffffffflu;

    // BFS.
    for (int i = 0; i < (int)q.size(); i++) {
        Ptr<Node> now = q[i];
        int d = dis[now];
        for (auto it = nbr2if[now].begin(); it != nbr2if[now].end(); it++) {
            // skip down link
            if (!it->second.up) continue;
            Ptr<Node> next = it->first;
            // If 'next' have not been visited.
            if (dis.find(next) == dis.end()) {
                dis[next] = d + 1;
                delay[next] = delay[now] + it->second.delay;  // maybe nanoseconds?
                txDelay[next] = txDelay[now] + packet_payload_size * 1000000000lu * 8 /
                                                   it->second.bw;  // maybe nanoseconds?
                bw[next] = std::min(bw[now], it->second.bw);
                // we only enqueue switch, because we do not want packets to go through host as
                // middle point
                if (next->GetNodeType() == 1) {
                    q.push_back(next);
                }
            }
            // if 'now' is on the shortest path from 'next' to 'host'.
            if (d + 1 == dis[next]) {
                nextHop[next][host].push_back(now);
            }
        }
    }
    for (auto it : delay) {
        pairDelay[it.first][host] = it.second;
    }
    for (auto it : txDelay) {
        pairTxDelay[it.first][host] = it.second;
    }
    for (auto it : bw) {
        pairBw[it.first][host] = it.second;
    }
}
void CalculateRoutes(NodeContainer &n) {
    for (int i = 0; i < (int)n.GetN(); i++) {
        Ptr<Node> node = n.Get(i);
        if (node->GetNodeType() == 0) {
            CalculateRoute(node);
        }
    }
}

/**
 * @brief Set the Routing Entries object
 */
void SetRoutingEntries() {
    // For each node.
    for (auto i = nextHop.begin(); i != nextHop.end(); i++) {
        Ptr<Node> node = i->first;
        auto &table = i->second;
        for (auto j = table.begin(); j != table.end(); j++) {
            // The destination node.
            Ptr<Node> dst = j->first;
            // The IP address of the dst.
            Ipv4Address dstAddr = dst->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal();
            // The next hops towards the dst.
            vector<Ptr<Node>> nexts = j->second;
            for (int k = 0; k < (int)nexts.size(); k++) {
                Ptr<Node> next = nexts[k];
                uint32_t interface = nbr2if[node][next].idx;
                if (node->GetNodeType() == 1)
                    DynamicCast<SwitchNode>(node)->AddTableEntry(dstAddr, interface);
                else {
                    node->GetObject<RdmaDriver>()->m_rdma->AddTableEntry(dstAddr, interface);
                }
            }
        }
    }
}
/**
 * @brief take down the link between a and b, and redo the routing
 */
void TakeDownLink(NodeContainer n, Ptr<Node> a, Ptr<Node> b) {
    if (!nbr2if[a][b].up) return;
    // take down link between a and b
    nbr2if[a][b].up = nbr2if[b][a].up = false;
    nextHop.clear();
    CalculateRoutes(n);
    // clear routing tables
    for (uint32_t i = 0; i < n.GetN(); i++) {
        if (n.Get(i)->GetNodeType() == 1)
            DynamicCast<SwitchNode>(n.Get(i))->ClearTable();
        else
            n.Get(i)->GetObject<RdmaDriver>()->m_rdma->ClearTable();
    }
    DynamicCast<QbbNetDevice>(a->GetDevice(nbr2if[a][b].idx))->TakeDown();
    DynamicCast<QbbNetDevice>(b->GetDevice(nbr2if[b][a].idx))->TakeDown();
    // reset routing table
    SetRoutingEntries();

    // redistribute qp on each host
    for (uint32_t i = 0; i < n.GetN(); i++) {
        if (n.Get(i)->GetNodeType() == 0)
            n.Get(i)->GetObject<RdmaDriver>()->m_rdma->RedistributeQp();
    }
}

uint64_t get_nic_rate(NodeContainer &n) {
    uint64_t avg_nic_rate;
    uint64_t n_servers = 0;
    for (uint32_t i = 0; i < n.GetN(); i++) {
        if (n.Get(i)->GetNodeType() == 0) {
            avg_nic_rate +=
                DynamicCast<QbbNetDevice>(n.Get(i)->GetDevice(1))->GetDataRate().GetBitRate();
            n_servers += 1;
        }
    }
    return avg_nic_rate / n_servers;
}

/************************************************************************/
//                                                                      //
//                                M A I N                               //
//                                                                      //
/************************************************************************/

int main(int argc, char *argv[]) {
    uint32_t *workload_cdf = nullptr;
    clock_t begint, endt;
    begint = clock();
#ifndef PGO_TRAINING
    if (argc > 1)
#else
    if (true)
#endif
    {
        // Read the configuration file
        std::ifstream conf;
#ifndef PGO_TRAINING
        conf.open(argv[1]);
#else
        conf.open(PATH_TO_PGO_CONFIG);
#endif
        while (!conf.eof()) {
            std::string key;
            conf >> key;
            if (key.compare("FLOW_INPUT_FILE") == 0) {
                std::string v;
                conf >> v;
                flow_input_file = v;
                std::cerr << "FLOW_INPUT_FILE\t\t\t" << flow_input_file << "\n";
            } else if (key.compare("CNP_OUTPUT_FILE") == 0) {
                std::string v;
                conf >> v;
                cnp_output_file = v;
                std::cerr << "CNP_OUTPUT_FILE\t\t\t" << cnp_output_file << "\n";
            } else if (key.compare("EST_ERROR_MON_FILE") == 0) {
                std::string v;
                conf >> v;
                est_error_output_file = v;
                std::cerr << "EST_ERROR_MON_FILE\t\t\t" << est_error_output_file << "\n";
            } else if (key.compare("LB_MODE") == 0) {
                uint32_t v;
                conf >> v;
                lb_mode = v;
                std::cerr << "LB_MODE\t\t\t" << lb_mode << "\n";
            } else if (key.compare("AR_MODE") == 0) {
                uint32_t v;
                conf >> v;
                ar_mode = v;
                std::cerr << "AR_MODE\t\t\t" << ar_mode << "\n";
            } else if (key.compare("SW_MONITORING_INTERVAL") == 0) {
                uint32_t v;
                conf >> v;
                switch_mon_interval = v;
                std::cerr << "SW_MONITORING_INTERVAL\t\t\t" << switch_mon_interval << "\n";
            } else if (key.compare("CONWEAVE_TX_EXPIRY_TIME") == 0) {
                uint32_t v;
                conf >> v;
                conweave_txExpiryTime = Time(MicroSeconds(v));
                std::cerr << "CONWEAVE_TX_EXPIRY_TIME\t\t\t" << conweave_txExpiryTime << "\n";
            } else if (key.compare("CONWEAVE_REPLY_TIMEOUT_EXTRA") == 0) {
                uint32_t v;
                conf >> v;
                conweave_extraReplyDeadline = Time(MicroSeconds(v));
                std::cerr << "CONWEAVE_REPLY_TIMEOUT_EXTRA\t\t\t" << conweave_extraReplyDeadline
                          << "\n";
            } else if (key.compare("CONWEAVE_EXTRA_VOQ_FLUSH_TIME") == 0) {
                uint32_t v;
                conf >> v;
                conweave_extraVOQFlushTime = Time(MicroSeconds(v));
                std::cerr << "CONWEAVE_EXTRA_VOQ_FLUSH_TIME\t\t\t" << conweave_extraVOQFlushTime
                          << "\n";
            } else if (key.compare("CONWEAVE_PATH_PAUSE_TIME") == 0) {
                uint32_t v;
                conf >> v;
                conweave_pathPauseTime = Time(MicroSeconds(v));
                std::cerr << "CONWEAVE_PATH_PAUSE_TIME\t\t\t" << conweave_pathPauseTime << "\n";
            } else if (key.compare("CONWEAVE_DEFAULT_VOQ_WAITING_TIME") == 0) {
                uint32_t v;
                conf >> v;
                conweave_defaultVOQWaitingTime = Time(MicroSeconds(v));
                std::cerr << "CONWEAVE_DEFAULT_VOQ_WAITING_TIME\t\t\t"
                          << conweave_defaultVOQWaitingTime << "\n";
            } else if (key.compare("ENABLE_PFC") == 0) {
                uint32_t v;
                conf >> v;
                enable_pfc = v;
                if (enable_pfc)
                    std::cerr << "ENABLE_PFC\t\t\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "ENABLE_PFC\t\t\t"
                              << "No"
                              << "\n";
            } else if (key.compare("ENABLE_QCN") == 0) {
                uint32_t v;
                conf >> v;
                enable_qcn = v;
                if (enable_qcn)
                    std::cerr << "ENABLE_QCN\t\t\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "ENABLE_QCN\t\t\t"
                              << "No"
                              << "\n";
            } else if (key.compare("USE_DYNAMIC_PFC_THRESHOLD") == 0) {
                uint32_t v;
                conf >> v;
                use_dynamic_pfc_threshold = v;
                if (use_dynamic_pfc_threshold)
                    std::cerr << "USE_DYNAMIC_PFC_THRESHOLD\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "USE_DYNAMIC_PFC_THRESHOLD\t"
                              << "No"
                              << "\n";
            } else if (key.compare("CLAMP_TARGET_RATE") == 0) {
                uint32_t v;
                conf >> v;
                clamp_target_rate = v;
                if (clamp_target_rate)
                    std::cerr << "CLAMP_TARGET_RATE\t\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "CLAMP_TARGET_RATE\t\t"
                              << "No"
                              << "\n";
            } else if (key.compare("PAUSE_TIME") == 0) {
                double v;
                conf >> v;
                pause_time = v;
                std::cerr << "PAUSE_TIME\t\t\t" << pause_time << "\n";
            } else if (key.compare("DATA_RATE") == 0) {
                std::string v;
                conf >> v;
                data_rate = v;
                std::cerr << "DATA_RATE\t\t\t" << data_rate << "\n";
            } else if (key.compare("LINK_DELAY") == 0) {
                std::string v;
                conf >> v;
                link_delay = v;
                std::cerr << "LINK_DELAY\t\t\t" << link_delay << "\n";
            } else if (key.compare("PACKET_PAYLOAD_SIZE") == 0) {
                uint32_t v;
                conf >> v;
                packet_payload_size = v;
                std::cerr << "PACKET_PAYLOAD_SIZE\t\t" << packet_payload_size << "\n";
            } else if (key.compare("L2_CHUNK_SIZE") == 0) {
                uint32_t v;
                conf >> v;
                l2_chunk_size = v;
                std::cerr << "L2_CHUNK_SIZE\t\t\t" << l2_chunk_size << "\n";
            } else if (key.compare("L2_ACK_INTERVAL") == 0) {
                uint32_t v;
                conf >> v;
                l2_ack_interval = v;
                std::cerr << "L2_ACK_INTERVAL\t\t\t" << l2_ack_interval << "\n";
            } else if (key.compare("L2_BACK_TO_ZERO") == 0) {
                uint32_t v;
                conf >> v;
                l2_back_to_zero = v;
                if (l2_back_to_zero)
                    std::cerr << "L2_BACK_TO_ZERO\t\t\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "L2_BACK_TO_ZERO\t\t\t"
                              << "No"
                              << "\n";
            } else if (key.compare("TOPOLOGY_FILE") == 0) {
                std::string v;
                conf >> v;
                topology_file = v;
                std::cerr << "TOPOLOGY_FILE\t\t\t" << topology_file << "\n";
            } else if (key.compare("FLOW_FILE") == 0) {
                std::string v;
                conf >> v;
                flow_file = v;
                std::cerr << "FLOW_FILE\t\t\t" << flow_file << "\n";
            } else if (key.compare("WEIGHT_FILE") == 0) {
                std::string v;
                conf >> v;
                weight_file = v;
                std::cerr << "WEIGHT_FILE\t\t\t" << weight_file << "\n";
            } else if (key.compare("GROUP_FILE") == 0) {
                std::string v;
                conf >> v;
                group_file = v;
                std::cerr << "GROUP_FILE\t\t\t" << group_file << "\n";
            } else if (key.compare("WORKLOAD_TYPE") == 0) {
                uint32_t v;
                conf >> v;
                workload_type = v;
                std::cerr << "WORKLOAD_TYPE\t\t\t" << workload_type << "\n";
            } else if (key.compare("AI_MESSAGE_SIZE") == 0) {
                uint64_t v;
                conf >> v;
                ai_message_size = v;
                std::cerr << "AI_MESSAGE_SIZE\t\t\t" << ai_message_size << "\n";
            } else if (key.compare("AI_MESSAGE_SIZES_FILE") == 0) {
                std::string v;
                conf >> v;
                ai_message_sizes_file = v;
                std::cerr << "AI_MESSAGE_SIZES_FILE\t\t\t" << ai_message_sizes_file << "\n";
            } else if (key.compare("AI_NODES_PER_GROUP") == 0) {
                uint32_t v;
                conf >> v;
                ai_nodes_per_group = v;
                std::cerr << "AI_NODES_PER_GROUP\t\t\t" << ai_nodes_per_group << "\n";
            } else if (key.compare("NUM_ROUNDS") == 0) {
                uint32_t v;
                conf >> v;
                num_rounds = v;
                std::cerr << "NUM_ROUNDS\t\t\t" << num_rounds << "\n";
            }else if (key.compare("FLOWGEN_START_TIME") == 0) {
                double v;
                conf >> v;
                flowgen_start_time = v;
                cnp_mon_start = v;
                irn_mon_start = v;
                std::cerr << "FLOWGEN_START_TIME\t\t" << flowgen_start_time << "\n";
            } else if (key.compare("FLOWGEN_STOP_TIME") == 0) {
                double v;
                conf >> v;
                flowgen_stop_time = v;
                std::cerr << "FLOWGEN_STOP_TIME\t\t" << flowgen_stop_time << "\n";
            } else if (key.compare("ALPHA_RESUME_INTERVAL") == 0) {
                double v;
                conf >> v;
                alpha_resume_interval = v;
                std::cerr << "ALPHA_RESUME_INTERVAL\t\t" << alpha_resume_interval << "\n";
            } else if (key.compare("RP_TIMER") == 0) {
                double v;
                conf >> v;
                rp_timer = v;
                std::cerr << "RP_TIMER\t\t\t" << rp_timer << "\n";
            } else if (key.compare("EWMA_GAIN") == 0) {
                double v;
                conf >> v;
                ewma_gain = v;
                std::cerr << "EWMA_GAIN\t\t\t" << ewma_gain << "\n";
            } else if (key.compare("FAST_RECOVERY_TIMES") == 0) {
                uint32_t v;
                conf >> v;
                fast_recovery_times = v;
                std::cerr << "FAST_RECOVERY_TIMES\t\t" << fast_recovery_times << "\n";
            } else if (key.compare("RATE_AI") == 0) {
                std::string v;
                conf >> v;
                rate_ai = v;
                std::cerr << "RATE_AI\t\t\t\t" << rate_ai << "\n";
            } else if (key.compare("RATE_HAI") == 0) {
                std::string v;
                conf >> v;
                rate_hai = v;
                std::cerr << "RATE_HAI\t\t\t" << rate_hai << "\n";
            } else if (key.compare("ERROR_RATE_PER_LINK") == 0) {
                double v;
                conf >> v;
                error_rate_per_link = v;
                std::cerr << "ERROR_RATE_PER_LINK\t\t" << error_rate_per_link << "\n";
            } else if (key.compare("CC_MODE") == 0) {
                conf >> cc_mode;
                std::cerr << "CC_MODE\t\t" << cc_mode << '\n';
            } else if (key.compare("LANES_PER_DESTINATION") == 0) {
                uint32_t v;
                conf >> v;
                lanes_per_destination = v;
                std::cerr << "LANES_PER_DESTINATION\t\t" << lanes_per_destination << "\n";
            } else if (key.compare("RATE_DECREASE_INTERVAL") == 0) {
                double v;
                conf >> v;
                rate_decrease_interval = v;
                std::cerr << "RATE_DECREASE_INTERVAL\t\t" << rate_decrease_interval << "\n";
            } else if (key.compare("MIN_RATE") == 0) {
                conf >> min_rate;
                std::cerr << "MIN_RATE\t\t" << min_rate << "\n";
            } else if (key.compare("FCT_OUTPUT_FILE") == 0) {
                conf >> fct_output_file;
                std::cerr << "FCT_OUTPUT_FILE\t\t" << fct_output_file << '\n';
            } else if (key.compare("JCT_OUTPUT_FILE") == 0) {
                conf >> jct_output_file;
                std::cerr << "JCT_OUTPUT_FILE\t\t" << jct_output_file << '\n';
            } else if (key.compare("HAS_WIN") == 0) {
                conf >> has_win;
                std::cerr << "HAS_WIN\t\t" << has_win << "\n";
            } else if (key.compare("WINDOW_SIZE") == 0) { 
                conf >> window_size;
                std::cerr << "WINDOW_SIZE\t\t" << window_size << "\n";
            } else if (key.compare("TIMEOUT_SLOWSTART_MODE") == 0) {
                conf >> timeout_slowstart_mode;
                std::cerr << "TIMEOUT_SLOWSTART_MODE\t\t" << timeout_slowstart_mode << "\n";
            } else if (key.compare("GLOBAL_T") == 0) {
                conf >> global_t;
                std::cerr << "GLOBAL_T\t\t" << global_t << '\n';
            } else if (key.compare("MI_THRESH") == 0) {
                conf >> mi_thresh;
                std::cerr << "MI_THRESH\t\t" << mi_thresh << '\n';
            } else if (key.compare("VAR_WIN") == 0) {
                uint32_t v;
                conf >> v;
                var_win = v;
                std::cerr << "VAR_WIN\t\t" << v << '\n';
            } else if (key.compare("FAST_REACT") == 0) {
                uint32_t v;
                conf >> v;
                fast_react = v;
                std::cerr << "FAST_REACT\t\t" << v << '\n';
            } else if (key.compare("U_TARGET") == 0) {
                conf >> u_target;
                std::cerr << "U_TARGET\t\t" << u_target << '\n';
            } else if (key.compare("INT_MULTI") == 0) {
                conf >> int_multi;
                std::cerr << "INT_MULTI\t\t\t\t" << int_multi << '\n';
            } else if (key.compare("RATE_BOUND") == 0) {
                uint32_t v;
                conf >> v;
                rate_bound = v;
                std::cerr << "RATE_BOUND\t\t" << rate_bound << '\n';
            } else if (key.compare("DCTCP_RATE_AI") == 0) {
                conf >> dctcp_rate_ai;
                std::cerr << "DCTCP_RATE_AI\t\t\t\t" << dctcp_rate_ai << "\n";
            } else if (key.compare("PFC_OUTPUT_FILE") == 0) {
                conf >> pfc_output_file;
                std::cerr << "PFC_OUTPUT_FILE\t\t\t\t" << pfc_output_file << '\n';
            } else if (key.compare("LINK_DOWN") == 0) {
                conf >> link_down_time >> link_down_A >> link_down_B;
                std::cerr << "LINK_DOWN\t\t\t\t" << link_down_time << ' ' << link_down_A << ' '
                          << link_down_B << '\n';
            } else if (key.compare("KMAX_MAP") == 0) {
                int n_k;
                conf >> n_k;
                std::cerr << "KMAX_MAP\t\t\t\t";
                for (int i = 0; i < n_k; i++) {
                    uint64_t rate;
                    uint32_t k;
                    conf >> rate >> k;
                    rate2kmax[rate] = k;
                    std::cerr << ' ' << rate << ' ' << k;
                }
                std::cerr << '\n';
            } else if (key.compare("KMIN_MAP") == 0) {
                int n_k;
                conf >> n_k;
                std::cerr << "KMIN_MAP\t\t\t\t";
                for (int i = 0; i < n_k; i++) {
                    uint64_t rate;
                    uint32_t k;
                    conf >> rate >> k;
                    rate2kmin[rate] = k;
                    std::cerr << ' ' << rate << ' ' << k;
                }
                std::cerr << '\n';
            } else if (key.compare("PMAX_MAP") == 0) {
                int n_k;
                conf >> n_k;
                std::cerr << "PMAX_MAP\t\t\t\t";
                for (int i = 0; i < n_k; i++) {
                    uint64_t rate;
                    double p;
                    conf >> rate >> p;
                    rate2pmax[rate] = p;
                    std::cerr << ' ' << rate << ' ' << p;
                }
                std::cerr << '\n';
            } else if (key.compare("BUFFER_SIZE") == 0) {
                conf >> buffer_size;
                std::cerr << "BUFFER_SIZE\t\t\t\t" << buffer_size << '\n';
            } else if (key.compare("QLEN_MON_FILE") == 0) {
                conf >> qlen_mon_file;
                std::cerr << "QLEN_MON_FILE\t\t\t\t" << qlen_mon_file << '\n';
            } else if (key.compare("VOQ_MON_FILE") == 0) {
                conf >> voq_mon_file;
                std::cerr << "VOQ_MON_FILE\t\t\t\t" << voq_mon_file << '\n';
            } else if (key.compare("VOQ_MON_DETAIL_FILE") == 0) {
                conf >> voq_mon_detail_file;
                std::cerr << "VOQ_MON_DETAIL_FILE\t\t\t\t" << voq_mon_detail_file << '\n';
            } else if (key.compare("UPLINK_MON_FILE") == 0) {
                conf >> uplink_mon_file;
                std::cerr << "UPLINK_MON_FILE\t\t\t\t" << uplink_mon_file << '\n';
            } else if (key.compare("DOWNLINK_MON_FILE") == 0) {
                conf >> downlink_mon_file;
                std::cerr << "DOWNLINK_MON_FILE\t\t\t\t" << downlink_mon_file << '\n';
            } else if (key.compare("SPINE_DL_MON_FILE") == 0) {
                conf >> spine_dl_mon_file;
                std::cerr << "SPINE_DL_MON_FILE\t\t\t\t" << spine_dl_mon_file << '\n';
            } else if (key.compare("THROUGHPUT_MON_FILE") == 0) {
                conf >> throughput_mon_file;
                std::cerr << "THROUGHPUT_MON_FILE\t\t\t\t" << throughput_mon_file << '\n';
            } else if (key.compare("CONN_MON_FILE") == 0) {
                conf >> conn_mon_file;
                std::cerr << "CONN_MON_FILE\t\t\t\t" << conn_mon_file << '\n';
            } else if (key.compare("FLOW_DROP_FILE")==0){
                conf >> flow_drop_file;
                std::cerr << "FLOW_DROP_FILE\t\t\t\t" << flow_drop_file << '\n';
            } else if (key.compare("DROP_INCAST_FILE") == 0) {
                conf >> drop_incast_file;
                std::cerr << "DROP_INCAST_FILE\t\t\t\t" << drop_incast_file << '\n';
            } else if (key.compare("PFC_INCAST_FILE") == 0) {
                conf >> pfc_incast_file;
                std::cerr << "PFC_INCAST_FILE\t\t\t\t" << pfc_incast_file << '\n';
            } else if (key.compare("RETRANSMIT_FILE") == 0){
                conf  >> retransmit_file;
                std::cerr << "RETRANSMIT_FILE\t\t\t\t" << retransmit_file << '\n';
            } else if (key.compare("QLEN_MON_START") == 0) {
                conf >> qlen_mon_start;
                std::cerr << "QLEN_MON_START\t\t\t\t" << qlen_mon_start << '\n';
            } else if (key.compare("QLEN_MON_END") == 0) {
                conf >> qlen_mon_end;
                std::cerr << "QLEN_MON_END\t\t\t\t" << qlen_mon_end << '\n';
            } else if (key.compare("MULTI_RATE") == 0) {
                int v;
                conf >> v;
                multi_rate = v;
                std::cerr << "MULTI_RATE\t\t\t\t" << multi_rate << '\n';
            } else if (key.compare("SAMPLE_FEEDBACK") == 0) {
                int v;
                conf >> v;
                sample_feedback = v;
                std::cerr << "SAMPLE_FEEDBACK\t\t\t\t" << sample_feedback << '\n';
            } else if (key.compare("LOAD") == 0) {
                double v;
                conf >> v;
                load = v;
                std::cerr << "LOAD\t\t\t" << load << "\n";
            } else if (key.compare("ENABLE_IRN") == 0) {
                bool v;
                conf >> v;
                enable_irn = v;
                std::cerr << "ENABLE_IRN\t\t" << enable_irn << "\n";
            } else if (key.compare("ENABLE_DCP") == 0) {
                bool v;
                conf >> v;
                enable_dcp = v;
                std::cerr << "ENABLE_DCP\t\t" << enable_dcp << "\n";
            } else if (key.compare("ENABLE_DCP_ACK_OPT") == 0) {
                bool v;
                conf >> v;
                enable_dcp_ack_opt = v;
                std::cerr << "ENABLE_DCP_ACK_OPT\t\t" << enable_dcp_ack_opt << "\n";
            } else if(key.compare("ENABLE_IDEAL") == 0) {
                bool v;
                conf >> v;
                enable_ideal = v;
                std::cerr << "ENABLE_IDEAL\t\t" << enable_ideal << "\n";
            } else if (key.compare("RANDOM_SEED") == 0) {
                int v;
                conf >> v;
                random_seed = v;
                std::cerr << "RANDOM_SEED\t\t\t" << random_seed << "\n";
            } else if (key.compare("IRN_RTOH_HIGH") == 0) {
                int v;
                conf >> v;
                irnRtoHigh = v;
                std::cerr << "IRN_RTOH_HIGH\t\t" << irnRtoHigh << "\n";
            } else if (key.compare("IRN_RTO_LOW") == 0) {
                int v;
                conf >> v;
                irnRtoLow = v;
                std::cerr << "IRN_RTO_LOW\t\t" << irnRtoLow << "\n";
            }

            fflush(stdout);
        }
        conf.close();

    } else {
        std::cerr << "Error: require a config file\n";
        fflush(stdout);
        return 1;
    }

    /******************* READING CONFIG FILE IS DONE ***********************/

    /**
     * Activate ns3 logging
     */
    LogComponentEnable("GENERIC_SIMULATION", LOG_LEVEL_DEBUG);

    /**
     * @brief Random seed setup
     */
    NS_LOG_INFO("Initialize random seed: " << random_seed);
    srand((unsigned)random_seed);
    SeedManager::SetSeed(random_seed);

    /**
     * @brief PFC/QCN setup
     */
    bool dynamicth = use_dynamic_pfc_threshold;
    Config::SetDefault("ns3::QbbNetDevice::PauseTime", UintegerValue(pause_time));
    Config::SetDefault("ns3::QbbNetDevice::QcnEnabled", BooleanValue(enable_qcn));
    Config::SetDefault("ns3::QbbNetDevice::DynamicThreshold", BooleanValue(dynamicth));
    Config::SetDefault("ns3::QbbNetDevice::QbbEnabled", BooleanValue(enable_pfc));
    // if(enable_pfc) {
    //     Config::SetDefault("ns3::SwitchMmu::EgressAlpha", DoubleValue(100.));
    // }

    if (cc_mode != 1 && lb_mode == 9) {
        std::cout << "Currently, ConWeave supports only DCQCN congestion control for RDMA. \nIf "
                     "you want to extend, the reordering delay at DstTor must be considered."
                  << std::endl;
        exit(1);
    }

    /**
     * @brief INT header setup
     */
    IntHop::multi = int_multi;
    // IntHeader::mode
    if (cc_mode == 7)  // timely, use ts
        IntHeader::mode = 1;
    else if (cc_mode == 3)  // hpcc, use int
        IntHeader::mode = 0;
    else  // others, no extra header
        IntHeader::mode = 5;

    /**
     * @brief open topology config, input-flows config.
     */
    topof.open(topology_file.c_str());
    uint32_t node_num, switch_num, link_num;
    topof >> node_num >> switch_num >> link_num;
    if(workload_type == 0)
    {
        flowf.open(flow_file.c_str());
        flowf >> flow_num;
        std::cout << "Flow number: " << flow_num << std::endl;
    }

    /*-------Parameter of Settings-------*/
    Settings::node_num = node_num;
    Settings::host_num = node_num - switch_num;
    Settings::switch_num = switch_num;
    Settings::lb_mode = lb_mode;
    Settings::ar_mode = ar_mode;
    Settings::packet_payload = packet_payload_size;
    // Settings::MTU = packet_payload_size + 48;  // for simplicity
    /*------------------------------------*/
    flow_drop_output = fopen(flow_drop_file.c_str(), "w");
    drop_incast_output = fopen(drop_incast_file.c_str(), "w");
    pfc_incast_output = fopen(pfc_incast_file.c_str(), "w");
    qlen_output = fopen(qlen_mon_file.c_str(), "w");
    // fprintf(flow_drop_output, "type,sip,dip,sid,did,sport,dport,prot,timestamp\n");


    std::vector<uint32_t> node_type(node_num, 0);
    for (uint32_t i = 0; i < switch_num; i++) {
        uint32_t sid;
        topof >> sid;
        node_type[sid] = 1;
    }
    for (uint32_t i = 0; i < node_num; i++) {
        if (node_type[i] == 0)
            n.Add(CreateObject<Node>());
        else {
            Ptr<SwitchNode> sw = CreateObject<SwitchNode>();
            n.Add(sw);
            // if(topology_file == "config/bigswitch_H128_100G_OS1.txt") sw->SetAttribute("EcnEnabled", BooleanValue(false));
            // else sw->SetAttribute("EcnEnabled", BooleanValue(enable_qcn));
            sw->SetAttribute("EcnEnabled", BooleanValue(enable_qcn));
            sw->TraceConnectWithoutContext(
            "SwitchDropPacket",
            MakeBoundCallback(flow_drop_trace, drop_incast_output));
            if(enable_pfc){
                sw->TraceConnectWithoutContext(
                "SwitchPfcPause",
                MakeBoundCallback(flow_pfc_trace, pfc_incast_output));
            }
        }
    }
    NS_LOG_INFO("Create nodes.");

    /*----------------------------------------*/

    InternetStackHelper internet;
    internet.Install(n);  // aggregate ipv4, ipv6, udp, tcp, etc

    //
    // Assign IP to each server
    //
    for (uint32_t i = 0; i < node_num; i++) {
        if (n.Get(i)->GetNodeType() == 0) {  // is server
            serverAddress.resize(i + 1);
            serverAddress[i] = Settings::node_id_to_ip(i);
        }
    }

    NS_LOG_INFO("Create channels.");

    //
    // Explicitly create the channels required by the topology.
    //
    Ptr<RateErrorModel> rem = CreateObject<RateErrorModel>();
    Ptr<UniformRandomVariable> uv = CreateObject<UniformRandomVariable>();
    rem->SetRandomVariable(uv);
    uv->SetStream(50);
    rem->SetAttribute("ErrorRate", DoubleValue(error_rate_per_link));
    rem->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));

    pfc_file = fopen(pfc_output_file.c_str(), "w");

    QbbHelper qbb;
    Ipv4AddressHelper ipv4;
    std::vector<std::pair<uint32_t, uint32_t>> link_pairs;  // src, dst link pairs
    for (uint32_t i = 0; i < link_num; i++) {
        uint32_t src, dst;
        std::string data_rate, link_delay;
        double error_rate;
        topof >> src >> dst >> data_rate >> link_delay >> error_rate;

        /** ASSUME: fixed one-hop delay across network
         *  EXCEPTION: "AsymDelay" topologies intentionally have a subset of
         *  Leaf-Spine links bumped to 5us / 10us, so the uniform-delay check
         *  is skipped for them.
         */
        // if(topology_file != "config/bigswitch_H128_100G_OS1.txt") assert(std::to_string(one_hop_delay) + "ns" == link_delay);
         if(topology_file.find("AsymDelay") == std::string::npos
            && topology_file != "config/bigswitch_H16_100G_OS1.txt"
            && topology_file != "config/bigswitch_H128_100G_OS1.txt") {
             assert(std::to_string(one_hop_delay) + "ns" == link_delay);
         }

        link_pairs.push_back(std::make_pair(src, dst));
        Ptr<Node> snode = n.Get(src), dnode = n.Get(dst);

        qbb.SetDeviceAttribute("DataRate", StringValue(data_rate));
        qbb.SetChannelAttribute("Delay", StringValue(link_delay));

        if (error_rate > 0) {
            Ptr<RateErrorModel> rem = CreateObject<RateErrorModel>();
            Ptr<UniformRandomVariable> uv = CreateObject<UniformRandomVariable>();
            rem->SetRandomVariable(uv);
            uv->SetStream(50);
            rem->SetAttribute("ErrorRate", DoubleValue(error_rate));
            rem->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));
            qbb.SetDeviceAttribute("ReceiveErrorModel", PointerValue(rem));
        } else {
            qbb.SetDeviceAttribute("ReceiveErrorModel", PointerValue(rem));
        }

        fflush(stdout);

        // Assigne server IP
        // Note: this should be before the automatic assignment below (ipv4.Assign(d)),
        // because we want our IP to be the primary IP (first in the IP address list),
        // so that the global routing is based on our IP
        NetDeviceContainer d = qbb.Install(snode, dnode);
        if (snode->GetNodeType() == 0) {
            Ptr<Ipv4> ipv4 = snode->GetObject<Ipv4>();
            ipv4->AddInterface(d.Get(0));
            ipv4->AddAddress(1, Ipv4InterfaceAddress(serverAddress[src], Ipv4Mask(0xff000000)));
        }
        if (dnode->GetNodeType() == 0) {
            Ptr<Ipv4> ipv4 = dnode->GetObject<Ipv4>();
            ipv4->AddInterface(d.Get(1));
            ipv4->AddAddress(1, Ipv4InterfaceAddress(serverAddress[dst], Ipv4Mask(0xff000000)));
        }

        // used to create a graph of the topology
        nbr2if[snode][dnode].idx = DynamicCast<QbbNetDevice>(d.Get(0))->GetIfIndex();
        nbr2if[snode][dnode].up = true;
        nbr2if[snode][dnode].delay =
            DynamicCast<QbbChannel>(DynamicCast<QbbNetDevice>(d.Get(0))->GetChannel())
                ->GetDelay()
                .GetTimeStep();
        nbr2if[snode][dnode].bw = DynamicCast<QbbNetDevice>(d.Get(0))->GetDataRate().GetBitRate();
        nbr2if[dnode][snode].idx = DynamicCast<QbbNetDevice>(d.Get(1))->GetIfIndex();
        nbr2if[dnode][snode].up = true;
        nbr2if[dnode][snode].delay =
            DynamicCast<QbbChannel>(DynamicCast<QbbNetDevice>(d.Get(1))->GetChannel())
                ->GetDelay()
                .GetTimeStep();
        nbr2if[dnode][snode].bw = DynamicCast<QbbNetDevice>(d.Get(1))->GetDataRate().GetBitRate();

        // This is just to set up the connectivity between nodes. The IP addresses are useless
        char ipstring[16];
        Ipv4Address x;
        sprintf(ipstring, "10.%d.%d.0", i / 254 + 1, i % 254 + 1);
        ipv4.SetBase(ipstring, "255.255.255.0");
        ipv4.Assign(d);

        // setup PFC trace
        DynamicCast<QbbNetDevice>(d.Get(0))->TraceConnectWithoutContext(
            "QbbPfc", MakeBoundCallback(&get_pfc, pfc_file, DynamicCast<QbbNetDevice>(d.Get(0))));
        DynamicCast<QbbNetDevice>(d.Get(1))->TraceConnectWithoutContext(
            "QbbPfc", MakeBoundCallback(&get_pfc, pfc_file, DynamicCast<QbbNetDevice>(d.Get(1))));
    }

    std::cout << "(AVG) NIC RATE: " << get_nic_rate(n) << std::endl;

    /* Get IP address <-> NodeID pairs */
    Ipv4Address empty_ip;
    for (uint32_t i = 0; i < node_num; ++i) {
        if (n.Get(i)->GetNodeType() == 0) {  // is server
            if (serverAddress[i].IsEqual(empty_ip)) {
                printf("XXX ERROR %d\n", i);
                printf("size of serverAddress: %lu", serverAddress.size());
                NS_FATAL_ERROR("An end-host belongs to no link");
            }
        }
        Settings::hostId2IpMap[i] = serverAddress[i].Get();
        Settings::hostIp2IdMap[serverAddress[i].Get()] = i;
    }

    // config switch
    for (uint32_t i = 0; i < node_num; i++) {
        if (n.Get(i)->GetNodeType() == 1) {  // is switch
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(i));
            uint32_t shift = 3;  // by default 1/8
            for (uint32_t j = 1; j < sw->GetNDevices(); j++) {
                Ptr<QbbNetDevice> dev = DynamicCast<QbbNetDevice>(sw->GetDevice(j));
                // set ecn
                uint64_t rate = dev->GetDataRate().GetBitRate();
                NS_ASSERT_MSG(rate2kmin.find(rate) != rate2kmin.end(),
                              "must set kmin for each link speed");
                NS_ASSERT_MSG(rate2kmax.find(rate) != rate2kmax.end(),
                              "must set kmax for each link speed");
                NS_ASSERT_MSG(rate2pmax.find(rate) != rate2pmax.end(),
                              "must set pmax for each link speed");
                assert(rate2kmin.find(rate) != rate2kmin.end() &&
                       rate2kmax.find(rate) != rate2kmax.end() &&
                       rate2pmax.find(rate) != rate2pmax.end());
                sw->m_mmu->ConfigEcn(j, rate2kmin[rate], rate2kmax[rate], rate2pmax[rate]);
                // set pfc
                uint64_t delay =
                    DynamicCast<QbbChannel>(dev->GetChannel())->GetDelay().GetTimeStep();
                uint32_t headroom = rate * delay / 8 / 1000000000 * 2 + 2 * sw->m_mmu->MTU;
                sw->m_mmu->ConfigHdrm(j, headroom);
            }
            sw->m_mmu->ConfigNPort(sw->GetNDevices() - 1);

            // Dynamic buffer size allocation based on active ports and bandwidth
            uint32_t active_ports = sw->GetNDevices() - 1;  // exclude loopback
            double dynamic_buffer_size_MB = 0;

            if (buffer_size < -0.5) {  // -1: Tomahawk dynamic per-port allocation
                // If buffer_size is specified in run.py, calculate dynamic allocation
                // Get the bandwidth of the first port to determine switch type
                uint64_t port_bandwidth = 0;
                if (active_ports > 0) {
                    Ptr<QbbNetDevice> dev = DynamicCast<QbbNetDevice>(sw->GetDevice(1));
                    port_bandwidth = dev->GetDataRate().GetBitRate();
                }

                // Per-port buffer allocation based on bandwidth (MB per port)
                // 100G: 0.5MB/port, 400G: 1.765625MB/port (to achieve 16MB for 32x100G, 113MB for 64x400G)
                double buffer_per_port_MB = 0.5; // Default for 100G

                uint64_t bandwidth_gbps = port_bandwidth / (1000ULL * 1000 * 1000);
                if (bandwidth_gbps >= 400) {
                    buffer_per_port_MB = 1.765625; // 113MB / 64 ports = 1.765625MB/port
                } else if (bandwidth_gbps >= 200) {
                    buffer_per_port_MB = 1.0;      // Interpolate for 200G
                } else if (bandwidth_gbps >= 100) {
                    buffer_per_port_MB = 0.5;      // 16MB / 32 ports = 0.5MB/port
                } else if (bandwidth_gbps >= 50) {
                    buffer_per_port_MB = 0.25;     // Scale down for lower speeds
                } else {
                    buffer_per_port_MB = 0.125;    // Minimum for very low speeds
                }

                // Calculate total buffer and floor to integer
                double total_buffer_MB = active_ports * buffer_per_port_MB;
                dynamic_buffer_size_MB = total_buffer_MB;

                // Ensure minimum buffer size
                if (dynamic_buffer_size_MB < 1) dynamic_buffer_size_MB = 1;
                std::cout << "Switch " << sw->GetId()
                         << ": " << active_ports << " ports"
                         << ", " << bandwidth_gbps << "Gbps each"
                         << ", " << buffer_per_port_MB << "MB/port"
                         << ", allocated " << dynamic_buffer_size_MB << "MB buffer"
                         << std::endl;
                sw->m_mmu->ConfigBufferSize((uint32_t)(dynamic_buffer_size_MB * 1024 * 1024));
            } else if (buffer_size < 0.001){
                // Fallback to topology-specific settings for legacy support
                if(topology_file == "config/bigswitch_H16_100G_OS1.txt" || topology_file == "config/bigswitch_H128_100G_OS1.txt") {
                    dynamic_buffer_size_MB = 6;
                } else {
                    dynamic_buffer_size_MB = 9;  // Use default automatic sizing
                }
                sw->m_mmu->ConfigBufferSize((uint32_t)(dynamic_buffer_size_MB * 1024 * 1024));
            } else {
                // Allocate buffer based on total bandwidth: buffer_size MB per 100Gbps
                uint64_t port_bandwidth = 0;
                if (active_ports > 0) {
                    Ptr<QbbNetDevice> dev = DynamicCast<QbbNetDevice>(sw->GetDevice(1));
                    port_bandwidth = dev->GetDataRate().GetBitRate();
                }
                double bandwidth_gbps = port_bandwidth / (1000.0 * 1000 * 1000);
                if(active_ports < 8) active_ports = 8;  // To avoid too small buffer for low-port-count switches (e.g., 4-port 100G switch), set a minimum of 8 active ports for buffer calculation
                if(active_ports > 24) active_ports = 32;
                if(bandwidth_gbps < 100) bandwidth_gbps = 100;  // To avoid too small buffer for low-speed ports, set a minimum of 25Gbps for buffer calculation
                double total_bandwidth_gbps = active_ports * bandwidth_gbps;
                dynamic_buffer_size_MB = (total_bandwidth_gbps / 100.0) * buffer_size;
                if (dynamic_buffer_size_MB < 0.001) dynamic_buffer_size_MB = 1;

                // if(bandwidth_gbps == 100) dynamic_buffer_size_MB = 2 * dynamic_buffer_size_MB;
                std::cout << "Switch " << sw->GetId()
                        << ": " << active_ports << " ports"
                        << ", " << bandwidth_gbps << "Gbps each"
                        << ", configured " << buffer_size << "MB/100Gbps"
                        << ", allocated " << dynamic_buffer_size_MB << "MB total buffer"
                        << std::endl;

                sw->m_mmu->ConfigBufferSize((uint32_t)(dynamic_buffer_size_MB * 1024 * 1024));
            }
            sw->m_mmu->node_id = sw->GetId();
            sw->m_mmu->SetIngressAlpha(0.0625);
            if(enable_pfc){
                sw->m_mmu->SetEgressAlpha(100);
                sw->m_mmu->SetPFCEnabled(true);
            } else {
                sw->m_mmu->SetEgressAlpha(1);
                sw->m_mmu->SetPFCEnabled(false);
            }
            sw->m_mmu->InitSwitch();
            // NS_LOG_INFO("Node %u : Broadcom switch (%u ports / %gMB MMU)\n" %
            //             (i, sw->GetNDevices() - 1, sw->m_mmu->GetMmuBufferBytes() / 1000000.));
        }
    }

    fct_output = fopen(fct_output_file.c_str(), "w");
    flow_input_stream = fopen(flow_input_file.c_str(), "w");
    if (cc_mode == 1) {
        cnp_output = fopen(cnp_output_file.c_str(), "w");
    }

    /**
     * @brief install RDMA driver (Mellanox parameters)
     *
     * [ClampTargetRate]clamp_tgt_rate (false) - when receiving a CNP, the target rate is always
     *updated to be the current rate
     *[-]clamp_tgt_rate_after_time_inc (true) - when receiving a CNP, the target rate is updated to
     *be the current rate also if the last rate increase event was due to the timer, and not only
     *due to the byte counter
     * [-]initial_alpha_value(1023) -
     * [RateDecreaseInterval]rate_reduce_monitor_period(4) - Minimal interval for rate reduction for
     *a flow. If a CNP is received during the interval, the flow rate is reduced at the beginning of
     *the next rate_reduce_monitor_period interval to (1-Alpha/Gd)*CurrentRate. rpg_gd is given as
     *log2(Gd), where Gd may only be powers of 2.
     * [-]rpg_gd(11) - If an CNP is received, the flow rate is reduced at the beginning of the next
     *rate_reduce_monitor_period interval to (1-Alpha/Gd)*CurrentRate.
     * -> in this simulator, (alpha / gd) ~ 0.5 setup, initially. We do not need rpg_gd parameter.
     * [RateOnFirstCnp]rate_to_set_on_first_cnp(0) - The rate that is set for the flow, upon first
     *CNP received, in Mbps. [RPTimer]rpg_time_reset(300us) - Time counter for rate increase event
     *[FastRecoveryTimes]rpg_threshold(1) - Number of rate increase events for switching between
     *Fast Recovery, Active Increase, Hyper Active Increase modes.
     * [AlphaResumInterval]dce_tcp_rtt(1) - Window for sampling of moving average calculation of
     *alpha
     * [-]dce_tcp_g(1019) - Weight of the new sampling in moving average calculation of alpha
     * [-]rpg_byte_reset(32767) - Byte counter for rate increase event
     * [-]rpg_min_dec_fac(50) -  Maximal factor by which the rate can be reduced (2 means that the
     *new rate can be divided by 2 at maximum)
     */

    // manually type BDP
    std::map<std::string, uint32_t> topo2bdpMap;
    topo2bdpMap[std::string("leaf_spine_128_100G_OS2")] = 104000;  // RTT=8320
    topo2bdpMap[std::string("leaf_spine_L8_S16_100G_OS1")] = 104000;  // RTT=8320
    topo2bdpMap[std::string("leaf_spine_L2_S4_100G_OS1")] = 104000;  // RTT=8320
    topo2bdpMap[std::string("leaf_spine_L2_S4_100G_OS2")] = 104000;  // RTT=8320
    topo2bdpMap[std::string("leaf_spine_L2_S8_100G_OS1")] = 104000;  // RTT=8320
    topo2bdpMap[std::string("leaf_spine_L16_S16_100G_OS1")] = 104000;  // RTT=8320
    topo2bdpMap[std::string("fat_k8_100G_OS2")] = 156000;      // RTT=12480 --> all 100G links
    topo2bdpMap[std::string("fat_k8_100G_OS1")] = 156000;      // RTT=12480 --> all 100G links
    // Add 200G topologies
    topo2bdpMap[std::string("leaf_spine_L8_S16_200G_OS1")] = 204000;  // RTT=8320
    topo2bdpMap[std::string("fat_k8_200G_OS1")] = 306000;  // RTT=8080
    // Add 400G topologies
    topo2bdpMap[std::string("leaf_spine_L8_S8_400G_OS2")] = 404000;  // RTT=8080
    topo2bdpMap[std::string("leaf_spine_L8_S16_400G_OS1")] = 404000;  // RTT=8080
    topo2bdpMap[std::string("leaf_spine_L2_S4_400G_OS1")] = 404000;  // RTT=8080
    topo2bdpMap[std::string("fat_k8_400G_OS1")] = 606000;  // RTT=8080
    // Add Asy topologies
    topo2bdpMap[std::string("three_layer_p4_tor4_l19_l28_s8_nofail_OS1")] = 156000;       // RTT=12480 --> all 100G links
    topo2bdpMap[std::string("three_layer_p4_tor4_l19_l28_s8_faill2_OS1")] = 156000;       // RTT=12480 --> all 100G links
    topo2bdpMap[std::string("three_layer_p4_tor4_l19_l28_s8_faill1_OS1")] = 156000;       // RTT=12480 --> all 100G links
    topo2bdpMap[std::string("three_layer_p4_tor4_l19_l28_s8_faill12_OS1")] = 156000;       // RTT=12480 --> all 100G links
    topo2bdpMap[std::string("three_layer_p4_tor4_l19_l24_s8_faill23_OS1")] = 156000;       // RTT=12480 --> all 100G links
    topo2bdpMap[std::string("three_layer_p4_tor4_l19_l28_s8_failhalf_OS1")] = 156000;       // RTT=12480 --> all 100G links
    topo2bdpMap[std::string("bigswitch_H128_100G_OS1")] = 104000;
    topo2bdpMap[std::string("bigswitch_H16_100G_OS1")] = 104000;
    // Added Asymmetric Topologies
    topo2bdpMap[std::string("leafspine_L8_S8_100G_Asym10pct_Ratio0.5_OS2")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S8_100G_Asym10pct_Ratio0.2_OS2")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S8_100G_Asym20pct_Ratio0.5_OS2")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S8_100G_Asym20pct_Ratio0.2_OS2")] = 104000;
    
    topo2bdpMap[std::string("leafspine_L8_S16_100G_Asym10pct_Ratio0.5_OS1")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S16_100G_Asym10pct_Ratio0.2_OS1")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S16_100G_Asym20pct_Ratio0.5_OS1")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S16_100G_Asym20pct_Ratio0.2_OS1")] = 104000;
    // New naming convention (config/test/leaf_spine_topo_asy_gen.py)
    // For delay-asym topos, real maxBdp > 104000 because of 10us links, but
    // we intentionally keep BDP lookup at 104000. The assertions below relax
    // uniform-link-delay / maxBdp equality for any "AsymDelay" topology.
    topo2bdpMap[std::string("leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S16_100G_AsymBw20pct_R0.5_OS1")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S16_100G_AsymFail1pct_OS1")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S16_100G_AsymFail10pct_OS1")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S16_100G_AsymDelay10pct_5us_OS1")] = 104000;
    topo2bdpMap[std::string("leafspine_L8_S16_100G_AsymDelay10pct_10us_OS1")] = 104000;
    
    // AI workload config is now dynamic based on ai_nodes_per_group parameter

    // topology_file
    bool found_topo2bdpMap = false;
    uint32_t irn_bdp_lookup = 0;
    std::cout << "DEBUG: Looking for topology config for: " << topology_file << std::endl;
    for (auto pair : topo2bdpMap) {
        std::cout << "DEBUG: Checking against: " << pair.first << std::endl;
        if (topology_file.find(pair.first) !=
            std::string::npos) {  // if topology file string includes the word
            std::cout << "DEBUG: Found topo2bdpMap match: " << pair.first << std::endl;
            irn_bdp_lookup = pair.second;
            found_topo2bdpMap = true;
            break;
        }
    }
    if (found_topo2bdpMap == false) {
        std::cout << __FILE__ << "(" << __LINE__ << ")"
                  << " ERROR - topo2bdpMap has no matched item with " << topology_file << std::endl;
        assert(false);
    }

    // rdmaHw config
    // retransmit_output = fopen(retransmit_file.c_str(), "w");
    // fprintf(retransmit_output, "sip,dip,sid,did,sport,dport,start_time,retransmit_time\n");
    for (uint32_t i = 0; i < node_num; i++) {
        if (n.Get(i)->GetNodeType() == 0) {  // is server
            // create RdmaHw
            Ptr<RdmaHw> rdmaHw = CreateObject<RdmaHw>();
            rdmaHw->SetAttribute("ClampTargetRate", BooleanValue(clamp_target_rate));
            rdmaHw->SetAttribute("AlphaResumInterval", DoubleValue(alpha_resume_interval));
            rdmaHw->SetAttribute("RPTimer", DoubleValue(rp_timer));
            rdmaHw->SetAttribute("FastRecoveryTimes", UintegerValue(fast_recovery_times));
            rdmaHw->SetAttribute("EwmaGain", DoubleValue(ewma_gain));
            rdmaHw->SetAttribute("RateAI", DataRateValue(DataRate(rate_ai)));
            rdmaHw->SetAttribute("RateHAI", DataRateValue(DataRate(rate_hai)));
            rdmaHw->SetAttribute("L2BackToZero", BooleanValue(l2_back_to_zero));
            rdmaHw->SetAttribute("L2ChunkSize", UintegerValue(l2_chunk_size));
            rdmaHw->SetAttribute("L2AckInterval", UintegerValue(l2_ack_interval));
            rdmaHw->SetAttribute("CcMode", UintegerValue(cc_mode));
            rdmaHw->SetAttribute("LanesPerDestination", UintegerValue(lanes_per_destination));  // 新增
            rdmaHw->SetAttribute("RateDecreaseInterval", DoubleValue(rate_decrease_interval));
            rdmaHw->SetAttribute("MinRate", DataRateValue(DataRate(min_rate)));
            rdmaHw->SetAttribute("Mtu", UintegerValue(packet_payload_size));
            rdmaHw->SetAttribute("MiThresh", UintegerValue(mi_thresh));
            rdmaHw->SetAttribute("VarWin", BooleanValue(var_win));
            rdmaHw->SetAttribute("FastReact", BooleanValue(fast_react));
            rdmaHw->SetAttribute("MultiRate", BooleanValue(multi_rate));
            rdmaHw->SetAttribute("SampleFeedback", BooleanValue(sample_feedback));
            rdmaHw->SetAttribute("TargetUtil", DoubleValue(u_target));
            rdmaHw->SetAttribute("RateBound", BooleanValue(rate_bound));
            rdmaHw->SetAttribute("DctcpRateAI", DataRateValue(DataRate(dctcp_rate_ai)));
            rdmaHw->SetAttribute("IrnEnable", BooleanValue(enable_irn));
            rdmaHw->SetAttribute("DcpEnable", BooleanValue(enable_dcp));
            rdmaHw->SetAttribute("DcpAckOptEnable", BooleanValue(enable_dcp_ack_opt));
            rdmaHw->SetAttribute("IdealEnable", BooleanValue(enable_ideal));
            rdmaHw->SetAttribute("TimeoutSlowStartMode", UintegerValue(timeout_slowstart_mode));
            /*modification begin*/
            if(ar_mode == 0) {
                // std::cout << "[INFO]: AR_MODE 0 is selected, no AR." << std::endl;
                rdmaHw->SetAttribute("AREnable", BooleanValue(false));  // no AR
            } else if(ar_mode == 1) {
                // std::cout << "[INFO]: AR_MODE 1 is selected, AR" << std::endl;
                rdmaHw->SetAttribute("AREnable", BooleanValue(true));  // AR
            } else if(ar_mode == 2) {
                // rdmaHw->SetAttribute("ArMode", UintegerValue(2));  // AR with CNP
                std::cout << "[ERROR]: AR_MODE 2 is not supported yet, use AR_MODE 1 instead." << std::endl;
            } else {
                NS_FATAL_ERROR("ar_mode must be 0, 1, or 2");
            }
            
            /*modification end*/
            // topo2bdpMap (e.g., longest BDP 25000: 8us * 25Gbps)
            rdmaHw->SetAttribute("IrnRtoHigh", TimeValue(MicroSeconds(irnRtoHigh)));  // 1930
            rdmaHw->SetAttribute("IrnRtoLow", TimeValue(MicroSeconds(irnRtoLow)));   // 454
            if(window_size > irn_bdp_lookup){
                rdmaHw->SetAttribute("IrnBdp", UintegerValue(window_size));
            }else{
                rdmaHw->SetAttribute("IrnBdp", UintegerValue(irn_bdp_lookup));
            }

            rdmaHw->SetAttribute("DcpRto", TimeValue(MicroSeconds(irnRtoHigh)));
            rdmaHw->SetAttribute("IdealRto", TimeValue(MicroSeconds(irnRtoHigh)));

            // add host rdmahw to monitoring map
            hostId2RdmaHw[i] = rdmaHw;
            // Monitoring CNP Marking frequency of DCQCN
            if (cc_mode == 1) {
                Simulator::Schedule(NanoSeconds(cnp_mon_start), &cnp_freq_monitoring, cnp_output,
                                    rdmaHw);
            }

            // create and install RdmaDriver
            Ptr<RdmaDriver> rdma = CreateObject<RdmaDriver>();
            Ptr<Node> node = n.Get(i);
            rdma->SetNode(node);
            rdma->SetRdmaHw(rdmaHw);
            // add host rdmahw to setting monitoring map
            Settings::NodeIdToRdmaHwMap[node->GetId()] = rdmaHw;

            node->AggregateObject(rdma);
            rdma->Init();
            rdma->TraceConnectWithoutContext("QpComplete",
                                             MakeBoundCallback(qp_finish, fct_output));

            // rdmaHw->TraceConnectWithoutContext("RetransmitStart",
            //                                 MakeBoundCallback(retransmit_trace, retransmit_output));
        }
    }

    /**
     * @brief setup switch's CcMode and ACK with high priority
     */
    for (uint32_t i = 0; i < node_num; i++) {
        if (n.Get(i)->GetNodeType() == 1) {  // switch
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(i));
            sw->SetAttribute("CcMode", UintegerValue(cc_mode));
            sw->SetAttribute("AckHighPrio", UintegerValue(1));
            if(enable_dcp){
                std::cout << "[Switch] Enable PacketTrimming (DCP mode ON)" << std::endl;
                sw->SetAttribute("PacketTrimming", BooleanValue(enable_dcp));
            }
            if(enable_ideal){
                std::cout << "[Switch] Enable IdealLossRecovery (ideal mode ON)" << std::endl;
                sw->SetAttribute("IdealLossRecovery", BooleanValue(enable_ideal));
            }
        }
    }

    /**
     * @brief setup routing
     */
    CalculateRoutes(n);
    SetRoutingEntries();

    /**
     * @brief get BDP and delay
     */
    maxRtt = maxBdp = 0;
    fprintf(stderr, "node_num=%d\n", node_num);
    for (uint32_t i = 0; i < node_num; i++) {
        if (n.Get(i)->GetNodeType() != 0) continue;
        for (uint32_t j = i + 1; j < node_num; j++) {
            if (n.Get(j)->GetNodeType() != 0) continue;
            uint64_t delay = pairDelay[n.Get(i)][n.Get(j)];
            uint64_t txDelay = pairTxDelay[n.Get(i)][n.Get(j)];
            uint64_t rtt = delay * 2 + txDelay;
            uint64_t bw = pairBw[n.Get(i)][n.Get(j)];
            uint64_t bdp = rtt * bw / 1000000000 / 8;
            pairBdp[n.Get(i)][n.Get(j)] = bdp;
            pairBdp[n.Get(j)][n.Get(i)] = bdp;
            pairRtt[n.Get(i)][n.Get(j)] = rtt;
            pairRtt[n.Get(j)][n.Get(i)] = rtt;

            if (bdp > maxBdp) maxBdp = bdp;
            if (rtt > maxRtt) maxRtt = rtt;
        }
    }
    fprintf(stderr, "maxRtt: %lu, maxBdp: %lu\n", maxRtt, maxBdp);
    // if(topology_file != "config/bigswitch_H128_100G_OS1.txt") assert(maxBdp == irn_bdp_lookup);
    // For "AsymDelay" topologies: a subset of links have 5us/10us one-way delay,
    // so the computed maxBdp (based on actual link delays) is larger than
    // irn_bdp_lookup (which we intentionally keep at 104000). The BDP constraint
    // is therefore loosened: we just sanity-check irn_bdp_lookup <= maxBdp.
    if(topology_file.find("AsymDelay") != std::string::npos) {
        assert(irn_bdp_lookup <= maxBdp);
    } else if(topology_file != "config/bigswitch_H16_100G_OS1.txt"
              &&  topology_file != "config/bigswitch_H128_100G_OS1.txt") {
        assert(maxBdp == irn_bdp_lookup);
    }

    std::cout << "Configuring switches" << std::endl;
     /*******************************************************************/
    /* PASS 1: Identify ToR (Leaf) switches                      */
    /* A switch connected to any host (NodeType 0) is a ToR.     */
    /*******************************************************************/
    for (auto &pair : link_pairs) {
        Ptr<Node> probably_host = n.Get(pair.first);
        Ptr<Node> probably_switch = n.Get(pair.second);

        // host-switch link
        if (probably_host->GetNodeType() == 0 && probably_switch->GetNodeType() == 1) {
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(probably_switch);
            if (!sw->m_isToR) {
                sw->m_isToR = true;
                std::cout << "  - Switch " << sw->GetId() << " identified as ToR (Leaf)." << std::endl;
            }
            uint32_t hostIP = serverAddress[pair.first].Get();
            sw->m_isToR_hostIP.insert(hostIP);
            if (idxNodeToR.find(sw->GetId()) == idxNodeToR.end()) {
                idxNodeToR[sw->GetId()] = sw;
            };
        }
    }
    /*******************************************************************/
    /* PASS 2: Identify Spine switches                             */
    /* A non-ToR switch connected to a ToR is a Spine.             */
    /*******************************************************************/
    for (uint32_t i = 0; i < n.GetN(); i++) {
        Ptr<Node> node = n.Get(i);
        if (node->GetNodeType() == 1) { // It's a switch
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(node);
            if (sw->m_isToR) continue; // Skip if it's already a ToR

            // C++11 compatible loop
            for (auto const& pair : nbr2if[node]) {
                Ptr<Node> neighbor_node = pair.first;
                if (neighbor_node->GetNodeType() == 1) { // Neighbor is also a switch
                    Ptr<SwitchNode> neighbor_sw = DynamicCast<SwitchNode>(neighbor_node);
                    if (neighbor_sw->m_isToR) {
                        sw->m_isSpine = true;
                        std::cout << "  - Switch " << sw->GetId() << " identified as Spine." << std::endl;
                        break; // Found one ToR neighbor, that's enough
                    }
                }
            }
        }
    }

    /*******************************************************************/
    /* PASS 3: Identify Core switches                              */
    /* Any switch that is not a ToR and not a Spine is a Core.     */
    /*******************************************************************/
    for (uint32_t i = 0; i < n.GetN(); i++) {
        Ptr<Node> node = n.Get(i);
        if (node->GetNodeType() == 1) { // It's a switch
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(node);
            if (!sw->m_isToR && !sw->m_isSpine) {
                sw->m_isCore = true;
                 std::cout << "  - Switch " << sw->GetId() << " identified as Core." << std::endl;
            }
        }
    }

    if (lb_mode == 10) {
        for (uint32_t i = 0; i < n.GetN(); i++) {
            Ptr<Node> node = n.Get(i);
            if (node->GetNodeType() != 1) {
                continue;
            }

            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(node);
            for (std::map<Ptr<Node>, Interface>::const_iterator nbrIt = nbr2if[node].begin();
                 nbrIt != nbr2if[node].end(); ++nbrIt) {
                Ptr<Node> neighbor = nbrIt->first;
                uint32_t portIndex = nbrIt->second.idx;

                if (neighbor->GetNodeType() == 0 && sw->m_isToR) {
                    uint32_t hostIP = serverAddress[neighbor->GetId()].Get();
                    Settings::hostIpToLeafId[hostIP] = sw->GetId();
                } else if (neighbor->GetNodeType() == 1) {
                    Ptr<SwitchNode> neighborSw = DynamicCast<SwitchNode>(neighbor);
                    if (sw->m_isToR && neighborSw->m_isSpine) {
                        Settings::leafPortToSpineId[sw->GetId()][portIndex] = neighborSw->GetId();
                    }
                    if (sw->m_isSpine && neighborSw->m_isToR) {
                        Settings::spineToLeafOutPort[sw->GetId()][neighborSw->GetId()] = portIndex;
                    }
                }
            }
        }
    }

    /* config load balancer's switches using ToR-to-ToR routing */
    if(lb_mode == 5 || lb_mode == 7) {
        for (auto &pair : link_pairs) {
            Ptr<Node> probably_host = n.Get(pair.first);
            Ptr<Node> probably_switch = n.Get(pair.second);

            // host-switch link
            if (probably_host->GetNodeType() == 0 && probably_switch->GetNodeType() == 1) {
                Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(probably_switch);
                uint32_t hostIP = serverAddress[pair.first].Get();
                Settings::hostIp2SwitchId[hostIP] = sw->GetId();  // hostIP -> connected switch's ID
            }
        }
    }
    
    if (lb_mode == 3 || lb_mode == 6 || lb_mode == 9) {  // Conga, Letflow, Conweave
        NS_LOG_INFO("Configuring Load Balancer's Switches");
        for (auto &pair : link_pairs) {
            Ptr<Node> probably_host = n.Get(pair.first);
            Ptr<Node> probably_switch = n.Get(pair.second);

            // host-switch link
            if (probably_host->GetNodeType() == 0 && probably_switch->GetNodeType() == 1) {
                Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(probably_switch);
                uint32_t hostIP = serverAddress[pair.first].Get();
                Settings::hostIp2SwitchId[hostIP] = sw->GetId();  // hostIP -> connected switch's ID
            }
        }

        // Conga: m_congaFromLeafTable, m_congaToLeafTable, m_congaRoutingTable
        // Letflow: m_letflowRoutingTable
        // Conweave: m_ConWeaveRoutingTable, m_rxToRId2BaseRTT
        for (auto i = nextHop.begin(); i != nextHop.end(); i++) {  // every node
            if (i->first->GetNodeType() == 1) {                    // switch
                Ptr<Node> nodeSrc = i->first;
                Ptr<SwitchNode> swSrc = DynamicCast<SwitchNode>(nodeSrc);  // switch
                uint32_t swSrcId = swSrc->GetId();

                if (swSrc->m_isToR) {
                    // printf("--- ToR Switch %d\n", swSrcId);

                    auto table1 = i->second;
                    for (auto j = table1.begin(); j != table1.end(); j++) {
                        Ptr<Node> dst = j->first;  // dst
                        uint32_t dstIP = Settings::hostId2IpMap[dst->GetId()];
                        uint32_t swDstId = Settings::hostIp2SwitchId[dstIP];  // Rx(dst)ToR

                        if (swSrcId == swDstId) {
                            continue;  // if in the same pod, then skip
                        }

                        if (lb_mode == 3) {
                            // initialize `m_congaFromLeafTable` and `m_congaToLeafTable`
                            swSrc->m_mmu->m_congaRouting
                                .m_congaFromLeafTable[swDstId];  // dynamically will be added in
                                                                 // conga
                            swSrc->m_mmu->m_congaRouting.m_congaToLeafTable[swDstId];
                        }

                        // construct paths
                        uint32_t pathId;
                        uint8_t path_ports[4] = {0, 0, 0, 0};  // interface is always large than 0
                        vector<Ptr<Node>> nexts1 = j->second;
                        for (auto next1 : nexts1) {
                            uint32_t outPort1 = nbr2if[nodeSrc][next1].idx;
                            auto nexts2 = nextHop[next1][dst];
                            if (nexts2.size() == 1 && nexts2[0]->GetId() == swDstId) {
                                // this destination has 2-hop distance
                                uint32_t outPort2 = nbr2if[next1][nexts2[0]].idx;
                                // printf("[IntraPod-2hop] %d (%d)-> %d (%d) -> %d -> %d\n",
                                // nodeSrc->GetId(), outPort1, next1->GetId(), outPort2,
                                // nexts2[0]->GetId(), dst->GetId());
                                path_ports[0] = (uint8_t)outPort1;
                                path_ports[1] = (uint8_t)outPort2;
                                pathId = *((uint32_t *)path_ports);
                                if (lb_mode == 3) {
                                    swSrc->m_mmu->m_congaRouting.m_congaRoutingTable[swDstId]
                                        .insert(pathId);
                                }
                                if (lb_mode == 6) {
                                    swSrc->m_mmu->m_letflowRouting.m_letflowRoutingTable[swDstId]
                                        .insert(pathId);
                                }
                                if (lb_mode == 9) {
                                    swSrc->m_mmu->m_conweaveRouting.m_ConWeaveRoutingTable[swDstId]
                                        .insert(pathId);
                                    swSrc->m_mmu->m_conweaveRouting.m_rxToRId2BaseRTT[swDstId] =
                                        one_hop_delay * 4;
                                }
                                continue;
                            }

                            for (auto next2 : nexts2) {
                                uint32_t outPort2 = nbr2if[next1][next2].idx;
                                auto nexts3 = nextHop[next2][dst];
                                if (nexts3.size() == 1 && nexts3[0]->GetId() == swDstId) {
                                    // this destination has 3-hop distance
                                    uint32_t outPort3 = nbr2if[next2][nexts3[0]].idx;
                                    // printf("[IntraPod-3hop] %d (%d)-> %d (%d) -> %d (%d) -> %d ->
                                    // %d\n", nodeSrc->GetId(), outPort1, next1->GetId(), outPort2,
                                    // next2->GetId(), outPort3, nexts3[0]->GetId(), dst->GetId());
                                    path_ports[0] = (uint8_t)outPort1;
                                    path_ports[1] = (uint8_t)outPort2;
                                    path_ports[2] = (uint8_t)outPort3;
                                    pathId = *((uint32_t *)path_ports);
                                    if (lb_mode == 3) {
                                        swSrc->m_mmu->m_congaRouting.m_congaRoutingTable[swDstId]
                                            .insert(pathId);
                                    }
                                    if (lb_mode == 6) {
                                        swSrc->m_mmu->m_letflowRouting
                                            .m_letflowRoutingTable[swDstId]
                                            .insert(pathId);
                                    }
                                    if (lb_mode == 9) {
                                        swSrc->m_mmu->m_conweaveRouting
                                            .m_ConWeaveRoutingTable[swDstId]
                                            .insert(pathId);
                                        swSrc->m_mmu->m_conweaveRouting.m_rxToRId2BaseRTT[swDstId] =
                                            one_hop_delay * 6;
                                    }
                                    continue;
                                }

                                for (auto next3 : nexts3) {
                                    uint32_t outPort3 = nbr2if[next2][next3].idx;
                                    auto nexts4 = nextHop[next3][dst];
                                    if (nexts4.size() == 1 && nexts4[0]->GetId() == swDstId) {
                                        // this destination has 4-hop distance
                                        uint32_t outPort4 = nbr2if[next3][nexts4[0]].idx;
                                        // printf("[IntraPod-4hop] %d (%d)-> %d (%d) -> %d (%d) ->
                                        // %d (%d) -> %d -> %d\n", nodeSrc->GetId(), outPort1,
                                        // next1->GetId(), outPort2, next2->GetId(), outPort3,
                                        // next3->GetId(), outPort4, nexts4[0]->GetId(),
                                        // dst->GetId());
                                        path_ports[0] = (uint8_t)outPort1;
                                        path_ports[1] = (uint8_t)outPort2;
                                        path_ports[2] = (uint8_t)outPort3;
                                        path_ports[3] = (uint8_t)outPort4;
                                        pathId = *((uint32_t *)path_ports);
                                        if (lb_mode == 3) {
                                            swSrc->m_mmu->m_congaRouting
                                                .m_congaRoutingTable[swDstId]
                                                .insert(pathId);
                                        }
                                        if (lb_mode == 6) {
                                            swSrc->m_mmu->m_letflowRouting
                                                .m_letflowRoutingTable[swDstId]
                                                .insert(pathId);
                                        }
                                        if (lb_mode == 9) {
                                            swSrc->m_mmu->m_conweaveRouting
                                                .m_ConWeaveRoutingTable[swDstId]
                                                .insert(pathId);
                                            swSrc->m_mmu->m_conweaveRouting
                                                .m_rxToRId2BaseRTT[swDstId] = one_hop_delay * 8;
                                        }
                                        continue;
                                    } else {
                                        printf("Too large topology?\n");
                                        assert(false);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // m_outPort2BitRateMap - only for Conga
        for (auto i = nextHop.begin(); i != nextHop.end(); i++) {  // every node
            if (i->first->GetNodeType() == 1) {                    // switch
                Ptr<Node> node = i->first;
                Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(node);  // switch
                uint32_t swId = sw->GetId();

                auto table = i->second;
                for (auto j = table.begin(); j != table.end(); j++) {
                    Ptr<Node> dst = j->first;  // dst
                    uint32_t dstIP = Settings::hostId2IpMap[dst->GetId()];
                    uint32_t swDstId = Settings::hostIp2SwitchId[dstIP];

                    for (auto next : j->second) {
                        uint32_t outPort = nbr2if[node][next].idx;
                        uint64_t bw = nbr2if[node][next].bw;
                        sw->m_mmu->m_congaRouting.SetLinkCapacity(outPort, bw);
                        // printf("Node: %d, interface: %d, bw: %lu\n", swId, outPort, bw);
                    }
                }
            }
        }

        // Constant setup, and switchInfo
        for (auto i = nextHop.begin(); i != nextHop.end(); i++) {  // every node
            if (i->first->GetNodeType() == 1) {
                Ptr<Node> node = i->first;
                Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(node);  // switch
                NS_LOG_INFO("Switch Info - ID:%u, ToR:%d\n" % (sw->GetId(), sw->m_isToR));
                if (lb_mode == 3) {
                    sw->m_mmu->m_congaRouting.SetConstants(conga_dreTime, conga_agingTime,
                                                           conga_flowletTimeout, conga_quantizeBit,
                                                           conga_alpha);
                    sw->m_mmu->m_congaRouting.SetSwitchInfo(sw->m_isToR, sw->GetId());
                }
                if (lb_mode == 6) {
                    sw->m_mmu->m_letflowRouting.SetConstants(letflow_agingTime,
                                                             letflow_flowletTimeout);
                    sw->m_mmu->m_letflowRouting.SetSwitchInfo(sw->m_isToR, sw->GetId());
                }
                if (lb_mode == 9) {
                    sw->m_mmu->m_conweaveRouting.SetConstants(
                        conweave_extraReplyDeadline, conweave_extraVOQFlushTime,
                        conweave_txExpiryTime, conweave_defaultVOQWaitingTime,
                        conweave_pathPauseTime, conweave_pathAwareRerouting);
                    sw->m_mmu->m_conweaveRouting.SetSwitchInfo(sw->m_isToR, sw->GetId());
                }
            }
        }

        // schedule conga timeout monitor
        if (lb_mode == 3) {  // CONGA
            Simulator::Schedule(Seconds(flowgen_stop_time + simulator_extra_time),
                                conga_history_print);
        }
        if (lb_mode == 6) {  // LETFLOW
            Simulator::Schedule(Seconds(flowgen_stop_time + simulator_extra_time),
                                letflow_history_print);
        }
        if (lb_mode == 9) {  // CONWEAVE
            Simulator::Schedule(Seconds(flowgen_stop_time + simulator_extra_time),
                                conweave_history_print);
        }
    }

    // populate routing tables (although we use our custom impl in switch_node.cc)
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // maintain port number for each host
    for (uint32_t i = 0; i < node_num; i++) {
        if (n.Get(i)->GetNodeType() == 0) {
            portNumber[i] = 10000;  // each host use port number from 10000
            dportNumber[i] = 100;
        }
    }

    if(workload_type == 0) {
        flow_input.idx = 0;
        port_per_host = new uint16_t[node_num - switch_num];
        if (flow_num > 0) {
            // generate flows
            ReadFlowInput();
            Simulator::Schedule(Seconds(0), &ScheduleFlowInputs, flow_input_stream);
        }
    } else {
        // AI workload
        std::cout << "DEBUG: Starting AI workload initialization, workload_type=" << workload_type << std::endl;

        // Use ai_nodes_per_group to dynamically calculate groups
        uint32_t num_node_per_g = ai_nodes_per_group;
        uint32_t n_host = node_num - switch_num;
        uint32_t num_groups = max(1u, (uint32_t)(n_host / num_node_per_g));
        std::cout << "AI grouping: " << num_groups << " groups x " << num_node_per_g << " nodes per group (total " << n_host << " nodes)" << std::endl;

        std::vector<std::vector<uint32_t>> groups(num_groups);
        for (uint32_t g = 0; g < num_groups; ++g) {
            for (uint32_t i = 0; i < num_node_per_g; ++i) {
                groups[g].push_back(i * num_groups + g);
            }
        }

        for (uint32_t g = 0; g < num_groups; ++g) {
            std::cout << "groups[" << g << "] = { ";
            for (size_t j = 0; j < groups[g].size(); ++j) {
                std::cout << groups[g][j];
                if (j + 1 < groups[g].size()) std::cout << ", ";
            }
            std::cout << " }" << std::endl;
        }
        uint64_t message_size = ai_message_size;
        WorkloadType workload_type_enum;
        uint32_t ai_win = 0;
        uint64_t ai_rtt = 0;
        ai_rtt = maxRtt;
        if(has_win) {
            if(window_size > 0) {
                ai_win = window_size;
            } else {
                ai_win = maxBdp;
            }
        }
        if (workload_type == 1) {
            workload_type_enum = WorkloadType::AllToAll;
            flow_num = num_rounds * (num_node_per_g - 1) * num_groups * num_node_per_g;
            std::cout << "Flow number: " << flow_num << std::endl;
        } else if (workload_type == 2) {
            workload_type_enum = WorkloadType::RingAllReduce;
            flow_num = num_rounds * (num_node_per_g - 1) * num_groups * num_node_per_g * 2;
            std::cout << "Flow number: " << flow_num << std::endl;
        } else if (workload_type == 3) {
            workload_type_enum = WorkloadType::TreeAllReduce;
            flow_num = num_rounds * (num_node_per_g - 1) * num_groups * 2; // reduce + broadcast phases
            std::cout << "Flow number: " << flow_num << std::endl;
        } else if (workload_type == 4) {
            workload_type_enum = WorkloadType::TreeAllReduceChunked;
            uint32_t num_chunks = (ai_message_size + 8191) / 8192; // 8KB chunks
            flow_num = num_rounds * (num_node_per_g - 1) * num_groups * 2 * num_chunks;
            std::cout << "Flow number: " << flow_num << " (chunked with " << num_chunks << " chunks)" << std::endl;
        } else if (workload_type == 5) {
            workload_type_enum = WorkloadType::AllToAllV;
            flow_num = num_rounds * (num_node_per_g - 1) * num_groups * num_node_per_g;
            std::cout << "Flow number: " << flow_num << " (AlltoallV with variable message sizes)" << std::endl;

            // Parse AlltoallV message sizes file
            std::vector<std::vector<uint64_t>> message_sizes_matrix;
            if (ai_message_sizes_file != "none") {
                std::ifstream msg_file(ai_message_sizes_file);
                if (msg_file.is_open()) {
                    message_sizes_matrix.resize(num_groups);
                    std::string line;
                    while (std::getline(msg_file, line)) {
                        if (line.empty() || line[0] == '#') continue;

                        std::istringstream iss(line);
                        uint32_t group_id, src_idx, dst_idx;
                        uint64_t msg_size;
                        if (iss >> group_id >> src_idx >> dst_idx >> msg_size) {
                            if (group_id < message_sizes_matrix.size()) {
                                size_t expected_size = num_node_per_g * num_node_per_g;
                                if (message_sizes_matrix[group_id].size() < expected_size) {
                                    message_sizes_matrix[group_id].resize(expected_size);
                                }
                                size_t idx = src_idx * num_node_per_g + dst_idx;
                                if (idx < message_sizes_matrix[group_id].size()) {
                                    message_sizes_matrix[group_id][idx] = msg_size;
                                }
                            }
                        }
                    }
                    msg_file.close();
                    std::cout << "Loaded AlltoallV message sizes from: " << ai_message_sizes_file << std::endl;
                } else {
                    std::cerr << "Warning: Could not open AlltoallV message sizes file: " << ai_message_sizes_file << std::endl;
                    std::cerr << "Using uniform message sizes instead." << std::endl;
                    // Fill with uniform sizes as fallback
                    message_sizes_matrix.resize(num_groups);
                    for (uint32_t g = 0; g < num_groups; ++g) {
                        message_sizes_matrix[g].resize(num_node_per_g * num_node_per_g, message_size);
                    }
                }
            } else {
                // Fill with uniform sizes as fallback
                message_sizes_matrix.resize(num_groups);
                for (uint32_t g = 0; g < num_groups; ++g) {
                    message_sizes_matrix[g].resize(num_node_per_g * num_node_per_g, message_size);
                }
            }

            // Use specialized initialization for AllToAllV
            WorkloadTracker::GetInstance().InitializeAllToAllV(num_rounds, groups, message_sizes_matrix);
        } else {
            std::cerr << "Unknown workload type: " << workload_type << std::endl;
            assert(false);
        }

        // Initialize other workload types normally
        if (workload_type != 5) {
            WorkloadTracker::GetInstance().Initialize(workload_type_enum, num_rounds, groups, message_size);
        }
        WorkloadTracker::GetInstance().SetSimulationContext(n, serverAddress, portNumber, dportNumber, ai_win, ai_rtt);
        WorkloadTracker::GetInstance().SetJctOutputFile(jct_output_file);
        Simulator::Schedule(Seconds(flowgen_start_time), &WorkloadTracker::StartFirstRound, &WorkloadTracker::GetInstance());
        // flow_num = num_rounds * (num_node_per_g - 1) * num_groups * num_node_per_g;
        // std::cout << "Flow number: " << flow_num << std::endl;
    }

    topof.close();

    if (!weight_file.empty()) {
        std::ifstream wf(weight_file.c_str());
        if (wf.is_open()) {
        uint32_t nid, pid, did;
        double w;
        while (wf >> nid >> did >> pid >> w) {
            // 存入 Settings
            Settings::portWeights[nid][did][pid] = w;
            // Debug 输出 (可选)
            std::cout << "Loaded Weight: Node " << nid  << " Dest " << did << " Port " << pid << " = " << w << std::endl;
        }
        wf.close();
        std::cout << "Weights loaded from " << weight_file << std::endl;
        } else {
        std::cerr << "Error: Cannot open weights file: " << weight_file << std::endl;
        }
    } else {
        std::cout << "No WEIGHT_FILE specified, using default weights (1.0)." << std::endl;
    }

    // Load DRILL-style group file (format: src dst port gid gweight)
    //   同一 (src,dst,gid) 会出现多行 —— 每行对应组内一条路径/端口；
    //   gweight 在各行相同（组级字段），直接覆盖写入即可，端口则逐行追加。
    if (!group_file.empty()) {
        std::ifstream gf(group_file.c_str());
        if (gf.is_open()) {
            uint32_t nid, did, pid, gid;
            double gw;
            uint32_t n_rows = 0;
            while (gf >> nid >> did >> pid >> gid >> gw) {
                auto &grp = Settings::drillGroups[nid][did][gid];
                grp.weight = gw;              // 覆盖写入（组级字段）
                grp.ports.push_back(pid);     // 端口追加
                ++n_rows;
            }
            gf.close();
            std::cout << "Groups loaded from " << group_file
                      << " (" << n_rows << " rows)" << std::endl;
        } else {
            std::cerr << "Error: Cannot open group file: " << group_file << std::endl;
        }
    } else {
        std::cout << "No GROUP_FILE specified, DoLbDrillWeight will fall back to Adaptive Spray." << std::endl;
    }

    // schedule link down
    if (link_down_time > 0) {
        Simulator::Schedule(Seconds(flowgen_start_time) + MicroSeconds(link_down_time),
                        &TakeDownLink, n, n.Get(link_down_A), n.Get(link_down_B));
    }

    if (lb_mode == 9) {
        voq_output = fopen(voq_mon_file.c_str(), "w");                // specific to ConWeave
        voq_detail_output = fopen(voq_mon_detail_file.c_str(), "w");  // specific to ConWeave
    }

    uplink_output = fopen(uplink_mon_file.c_str(), "w");  // common
    downlink_output = fopen(downlink_mon_file.c_str(), "w");  // common
    spine_dl_output = fopen(spine_dl_mon_file.c_str(), "w");  // Spine->ToR
    throughput_output = fopen(throughput_mon_file.c_str(), "w"); 
    conn_output = fopen(conn_mon_file.c_str(), "w");      // common

    // update torId2UplinkIf, torId2DownlinkIf
    for (size_t ToRId = 0; ToRId < Settings::node_num; ToRId++) {
        Ptr<Node> node = n.Get(ToRId);
        if (node->GetNodeType() == 1) {  // switches
            auto swNode = DynamicCast<SwitchNode>(n.Get(ToRId));
            for (auto const& pair : nbr2if[node]) {
                Ptr<Node> neighbor_node = pair.first;
                Interface interface = pair.second;
                uint32_t portIndex = interface.idx;

                if (swNode->m_isToR || topology_file == "config/bigswitch_H128_100G_OS1.txt" || topology_file == "config/bigswitch_H16_100G_OS1.txt") {
                    if (neighbor_node->GetNodeType() == 0) { // Neighbor is a Host
                        torId2DownlinkIf[swNode->GetId()].push_back(portIndex);
                    } else { // Neighbor is another switch
                        auto neighbor_sw = DynamicCast<SwitchNode>(neighbor_node);
                        if (neighbor_sw->m_isSpine) { // Neighbor is a Spine
                            torId2UplinkIf[swNode->GetId()].push_back(portIndex);
                        }
                    }
                } else if (swNode->m_isSpine) {
                    // Neighbor must be a switch
                    auto neighbor_sw = DynamicCast<SwitchNode>(neighbor_node);
                    if (neighbor_sw->m_isToR) { // Neighbor is a ToR
                        spineId2DownlinkIf[swNode->GetId()].push_back(portIndex);
                    } else if (neighbor_sw->m_isCore) { // Neighbor is a Core
                        spineId2UplinkIf[swNode->GetId()].push_back(portIndex);
                    }
                } else if (swNode->m_isCore) {
                    // Neighbor must be a Spine switch
                    auto neighbor_sw = DynamicCast<SwitchNode>(neighbor_node);
                    if(neighbor_sw->m_isSpine) {
                        coreId2DownlinkIf[swNode->GetId()].push_back(portIndex);
                    }
                }
            }
        }
    }

    for (const auto &entry : torId2UplinkIf) {
        uint32_t torId = entry.first;
        for (uint32_t portIdx : entry.second) {
            Settings::ToRId2UporDownMap[torId][portIdx] = true;  // true 表示 uplink
        }
    }

    for (const auto &entry : torId2DownlinkIf) {
        uint32_t torId = entry.first;
        for (uint32_t portIdx : entry.second) {
            Settings::ToRId2UporDownMap[torId][portIdx] = false;  // false 表示 downlink
        }
    }

    // Populate Spine switch port directions
    for (const auto &entry : spineId2UplinkIf) {
        uint32_t spineId = entry.first;
        for (uint32_t portIdx : entry.second) {
            Settings::SpineId2UporDownMap[spineId][portIdx] = true; // true means uplink (to Core)
        }
    }

    for (const auto &entry : spineId2DownlinkIf) {
        uint32_t spineId = entry.first;
        for (uint32_t portIdx : entry.second) {
            Settings::SpineId2UporDownMap[spineId][portIdx] = false; // false means downlink (to ToR)
        }
    }

    // Populate Core switch port directions
    for (const auto &entry : coreId2DownlinkIf) {
        uint32_t coreId = entry.first;
        for (uint32_t portIdx : entry.second) {
            // Core switches only have downlinks to Spine switches in this topology
            Settings::CoreId2UporDownMap[coreId][portIdx] = false; // false means downlink (to Spine)
        }
    }

    if (lb_mode == 10) {
        Simulator::Schedule(Seconds(flowgen_start_time), &sglb_remote_queue_monitoring);
    }
    Simulator::Schedule(Seconds(flowgen_start_time), &periodic_monitoring, voq_output,
                        voq_detail_output, uplink_output, conn_output, &lb_mode);

    //
    // Now, do the actual simulation.
    //
    std::cout << "------------------------------------------" << std::endl;
    std::cout << "Running Simulation.\n";
    fflush(stdout);
    NS_LOG_INFO("Run Simulation.");
    Simulator::Schedule(Seconds(flowgen_start_time),
                        &stop_simulation_middle);  // check every 100us
    Simulator::Stop(Seconds(flowgen_stop_time + 10.0));
    Simulator::Run();

    /*-----------------------------------------------------------------------------*/
    /*----- we don't need below. Just we can enforce to close this simulation. -----*/
    /*-----------------------------------------------------------------------------*/
    Simulator::Destroy();
    if (flow_drop_output) {
        fclose(flow_drop_output);
    }
    if (drop_incast_output) {
        fclose(drop_incast_output);
    }
    NS_LOG_INFO("Total number of packets: " << RdmaHw::nAllPkts);
    NS_LOG_INFO("Done.");
    endt = clock();
    std::cerr << (double)(endt - begint) / CLOCKS_PER_SEC << "\n";
}
