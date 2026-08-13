#include "rdma-hw.h"

#include <ns3/ipv4-header.h>
#include <ns3/seq-ts-header.h>
#include <ns3/simulator.h>
#include <ns3/udp-header.h>

#include <climits>

#include "cn-header.h"
#include "flow-stat-tag.h"
#include "ns3/boolean.h"
#include "ns3/data-rate.h"
#include "ns3/double.h"
#include "ns3/flow-id-num-tag.h"
#include "ns3/lane-id-tag.h"
#include "ns3/pointer.h"
#include "ns3/ppp-header.h"
#include "ns3/settings.h"
#include "ns3/switch-node.h"
#include "ns3/uinteger.h"
#include "ppp-header.h"
#include "qbb-header.h"

#include "ns3/flowsize-tag.h"

namespace ns3 {

NS_LOG_COMPONENT_DEFINE("RdmaHw");

std::unordered_map<unsigned, unsigned> acc_timeout_count;
uint64_t RdmaHw::nAllPkts = 0;

TypeId RdmaHw::GetTypeId(void) {
    static TypeId tid =
        TypeId("ns3::RdmaHw")
            .SetParent<Object>()
            .AddAttribute("MinRate", "Minimum rate of a throttled flow",
                          DataRateValue(DataRate("100Mb/s")),
                          MakeDataRateAccessor(&RdmaHw::m_minRate), MakeDataRateChecker())
            .AddAttribute("Mtu", "Mtu.", UintegerValue(1000), MakeUintegerAccessor(&RdmaHw::m_mtu),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("CcMode", "which mode of DCQCN is running", UintegerValue(0),
                          MakeUintegerAccessor(&RdmaHw::m_cc_mode), MakeUintegerChecker<uint32_t>())
            .AddAttribute("NACKGenerationInterval", "The NACK/CNP Generation interval",
                          DoubleValue(4.0), MakeDoubleAccessor(&RdmaHw::m_nack_interval),
                          MakeDoubleChecker<double>())
            .AddAttribute("L2ChunkSize", "Layer 2 chunk size. Disable chunk mode if equals to 0.",
                          UintegerValue(4000), MakeUintegerAccessor(&RdmaHw::m_chunk),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("L2AckInterval", "Layer 2 Ack intervals. Disable ack if equals to 0.",
                          UintegerValue(1), MakeUintegerAccessor(&RdmaHw::m_ack_interval),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("L2BackToZero", "Layer 2 go back to zero transmission.",
                          BooleanValue(false), MakeBooleanAccessor(&RdmaHw::m_backto0),
                          MakeBooleanChecker())
            .AddAttribute("EwmaGain",
                          "Control gain parameter which determines the level of rate decrease",
                          DoubleValue(1.0 / 16), MakeDoubleAccessor(&RdmaHw::m_g),
                          MakeDoubleChecker<double>())
            .AddAttribute("RateOnFirstCnp", "the fraction of rate on first CNP", DoubleValue(1.0),
                          MakeDoubleAccessor(&RdmaHw::m_rateOnFirstCNP),
                          MakeDoubleChecker<double>())
            .AddAttribute("ClampTargetRate", "Clamp target rate.", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_EcnClampTgtRate), MakeBooleanChecker())
            .AddAttribute("RPTimer", "The rate increase timer at RP in microseconds",
                          DoubleValue(300.0), MakeDoubleAccessor(&RdmaHw::m_rpgTimeReset),
                          MakeDoubleChecker<double>())
            .AddAttribute("RateDecreaseInterval", "The interval of rate decrease check",
                          DoubleValue(4.0), MakeDoubleAccessor(&RdmaHw::m_rateDecreaseInterval),
                          MakeDoubleChecker<double>())
            .AddAttribute("FastRecoveryTimes", "The rate increase timer at RP", UintegerValue(1),
                          MakeUintegerAccessor(&RdmaHw::m_rpgThreshold),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("AlphaResumInterval", "The interval of resuming alpha", DoubleValue(1.0),
                          MakeDoubleAccessor(&RdmaHw::m_alpha_resume_interval),
                          MakeDoubleChecker<double>())
            .AddAttribute("RateAI", "Rate increment unit in AI period",
                          DataRateValue(DataRate("5Mb/s")), MakeDataRateAccessor(&RdmaHw::m_rai),
                          MakeDataRateChecker())
            .AddAttribute("RateHAI", "Rate increment unit in hyperactive AI period",
                          DataRateValue(DataRate("50Mb/s")), MakeDataRateAccessor(&RdmaHw::m_rhai),
                          MakeDataRateChecker())
            .AddAttribute("VarWin", "Use variable window size or not", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_var_win), MakeBooleanChecker())
            .AddAttribute("FastReact", "Fast React to congestion feedback", BooleanValue(true),
                          MakeBooleanAccessor(&RdmaHw::m_fast_react), MakeBooleanChecker())
            .AddAttribute("MiThresh", "Threshold of number of consecutive AI before MI",
                          UintegerValue(5), MakeUintegerAccessor(&RdmaHw::m_miThresh),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("TargetUtil",
                          "The Target Utilization of the bottleneck bandwidth, by default 95%",
                          DoubleValue(0.95), MakeDoubleAccessor(&RdmaHw::m_targetUtil),
                          MakeDoubleChecker<double>())
            .AddAttribute(
                "UtilHigh",
                "The upper bound of Target Utilization of the bottleneck bandwidth, by default 98%",
                DoubleValue(0.98), MakeDoubleAccessor(&RdmaHw::m_utilHigh),
                MakeDoubleChecker<double>())
            .AddAttribute("RateBound", "Bound packet sending by rate, for test only",
                          BooleanValue(true), MakeBooleanAccessor(&RdmaHw::m_rateBound),
                          MakeBooleanChecker())
            .AddAttribute("MultiRate", "Maintain multiple rates in HPCC", BooleanValue(true),
                          MakeBooleanAccessor(&RdmaHw::m_multipleRate), MakeBooleanChecker())
            .AddAttribute("SampleFeedback", "Whether sample feedback or not", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_sampleFeedback), MakeBooleanChecker())
            .AddAttribute("TimelyAlpha", "Alpha of TIMELY", DoubleValue(0.875),
                          MakeDoubleAccessor(&RdmaHw::m_tmly_alpha), MakeDoubleChecker<double>())
            .AddAttribute("TimelyBeta", "Beta of TIMELY", DoubleValue(0.8),
                          MakeDoubleAccessor(&RdmaHw::m_tmly_beta), MakeDoubleChecker<double>())
            .AddAttribute("TimelyTLow", "TLow of TIMELY (ns)", UintegerValue(50000),
                          MakeUintegerAccessor(&RdmaHw::m_tmly_TLow),
                          MakeUintegerChecker<uint64_t>())
            .AddAttribute("TimelyTHigh", "THigh of TIMELY (ns)", UintegerValue(500000),
                          MakeUintegerAccessor(&RdmaHw::m_tmly_THigh),
                          MakeUintegerChecker<uint64_t>())
            .AddAttribute("TimelyMinRtt", "MinRtt of TIMELY (ns)", UintegerValue(20000),
                          MakeUintegerAccessor(&RdmaHw::m_tmly_minRtt),
                          MakeUintegerChecker<uint64_t>())
            .AddAttribute("DctcpRateAI", "DCTCP's Rate increment unit in AI period",
                          DataRateValue(DataRate("1000Mb/s")),
                          MakeDataRateAccessor(&RdmaHw::m_dctcp_rai), MakeDataRateChecker())
            .AddAttribute("IrnEnable", "Enable IRN", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_irn), MakeBooleanChecker())
            /*modification begin*/
            .AddAttribute("AREnable", "Enable Adaptive Routing", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_adaptiveRouting), MakeBooleanChecker())
            .AddAttribute("TimeoutSlowStartMode", "Timeout slow start mode",
                          UintegerValue(0), MakeUintegerAccessor(&RdmaHw::m_timeoutSlowStartMode),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("DcpEnable", "Enable DCP", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_dcp), MakeBooleanChecker())
            .AddAttribute("DcpAckOptEnable", "Enable DCP Ack Optimization", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_dcp_ack_opt), MakeBooleanChecker())
            .AddAttribute("DcpRto", "High RTO for IRN", TimeValue(MicroSeconds(320)),
                          MakeTimeAccessor(&RdmaHw::m_dcp_rto), MakeTimeChecker())
            .AddAttribute("IdealEnable", "Enable Ideal Loss Recovery", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_ideal), MakeBooleanChecker())
            .AddAttribute("IdealRto", "RTO for Ideal mechanism", TimeValue(MicroSeconds(4000)),
                          MakeTimeAccessor(&RdmaHw::m_ideal_rto), MakeTimeChecker())
            .AddAttribute("LanesPerDestination", "Number of lanes per src-dst pair for mode 5",
                          UintegerValue(4), MakeUintegerAccessor(&RdmaHw::m_lanesPerDestination),
                          MakeUintegerChecker<uint32_t>(1))
            /*modification end*/
            .AddAttribute("IrnRtoLow", "Low RTO for IRN", TimeValue(MicroSeconds(454)),
                          MakeTimeAccessor(&RdmaHw::m_irn_rtoLow), MakeTimeChecker())
            .AddAttribute("IrnRtoHigh", "High RTO for IRN", TimeValue(MicroSeconds(1350)),
                          MakeTimeAccessor(&RdmaHw::m_irn_rtoHigh), MakeTimeChecker())
            .AddAttribute("IrnBdp", "BDP Limit for IRN in Bytes", UintegerValue(100000),
                          MakeUintegerAccessor(&RdmaHw::m_irn_bdp), MakeUintegerChecker<uint32_t>())
            .AddAttribute("L2Timeout", "Sender's timer of waiting for the ack",
                          TimeValue(MilliSeconds(4)), MakeTimeAccessor(&RdmaHw::m_waitAckTimeout),
                          MakeTimeChecker())
            /*modification begin*/
            .AddTraceSource("RetransmitStart", "Retransmit start",
                        MakeTraceSourceAccessor(&RdmaHw::m_traceRetransmitStart))
            /*modification end*/;
    return tid;
}

RdmaHw::RdmaHw() {
    cnp_total = 0;
    cnp_by_ecn = 0;
    cnp_by_ooo = 0;
    m_accSentBytes = 0;
    m_accAckedBytes = 0;
    m_lanesPerDestination = 4;  // Default: 4 lanes per src-dst pair
}

void RdmaHw::SetNode(Ptr<Node> node) { m_node = node; }
void RdmaHw::Setup(QpCompleteCallback cb) {
    for (uint32_t i = 0; i < m_nic.size(); i++) {
        Ptr<QbbNetDevice> dev = m_nic[i].dev;
        if (dev == NULL) continue;
        // share data with NIC
        dev->m_rdmaEQ->m_qpGrp = m_nic[i].qpGrp;
        // setup callback
        dev->m_rdmaReceiveCb = MakeCallback(&RdmaHw::Receive, this);
        dev->m_rdmaLinkDownCb = MakeCallback(&RdmaHw::SetLinkDown, this);
        dev->m_rdmaPktSent = MakeCallback(&RdmaHw::PktSent, this);
        // config NIC
        dev->m_rdmaEQ->m_mtu = m_mtu;
        dev->m_rdmaEQ->m_rdmaGetNxtPkt = MakeCallback(&RdmaHw::GetNxtPacket, this);
    }
    // setup qp complete callback
    m_qpCompleteCallback = cb;
}

uint32_t RdmaHw::GetNicIdxOfQp(Ptr<RdmaQueuePair> qp) {
    auto &v = m_rtTable[qp->dip.Get()];
    if (v.size() > 0) {
        return v[qp->GetHash() % v.size()];
    }
    NS_ASSERT_MSG(false, "We assume at least one NIC is alive");
    std::cout << "We assume at least one NIC is alive" << std::endl;
    exit(1);
}

uint64_t RdmaHw::GetQpKey(uint32_t dip, uint16_t sport, uint16_t dport,
                          uint16_t pg) {  // Sender perspective
    return ((uint64_t)dip << 32) | ((uint64_t)sport << 16) | (uint64_t)dport | (uint64_t)pg;
}
Ptr<RdmaQueuePair> RdmaHw::GetQp(uint64_t key) {
    auto it = m_qpMap.find(key);

    // lookup main memory
    if (it != m_qpMap.end()) {
        return it->second;
    }

    return NULL;
}
void RdmaHw::AddQueuePair(uint64_t size, uint16_t pg, Ipv4Address sip, Ipv4Address dip,
                          uint16_t sport, uint16_t dport, uint32_t win, uint64_t baseRtt,
                          int32_t flow_id) {
    // create qp
    Ptr<RdmaQueuePair> qp = CreateObject<RdmaQueuePair>(pg, sip, dip, sport, dport);
    qp->SetSize(size);
    qp->SetWin(win);
    qp->SetBaseRtt(baseRtt);
    qp->SetVarWin(m_var_win);
    qp->SetFlowId(flow_id);
    qp->SetTimeout(m_waitAckTimeout);

    if (m_irn) {
        qp->irn.m_enabled = m_irn;
        qp->irn.m_bdp = m_irn_bdp;
        qp->irn.m_rtoLow = m_irn_rtoLow;
        qp->irn.m_rtoHigh = m_irn_rtoHigh;
    }
    if(m_dcp) {
        qp->dcp.m_enabled = m_dcp;
        qp->dcp.m_rto = m_dcp_rto;
    }
    if(m_ideal) {
        qp->ideal.m_enabled = m_ideal;
        qp->ideal.m_rto = m_ideal_rto;
    }

    // add qp
    uint32_t nic_idx = GetNicIdxOfQp(qp);
    m_nic[nic_idx].qpGrp->AddQp(qp);
    uint64_t key = GetQpKey(dip.Get(), sport, dport, pg);
    m_qpMap[key] = qp;

    // set init variables
    DataRate m_bps = m_nic[nic_idx].dev->GetDataRate();
    qp->m_rate = m_bps;
    qp->m_max_rate = m_bps;
    if (m_cc_mode == 1) {
        qp->mlx.m_targetRate = m_bps;
    } else if (m_cc_mode == 2) {// Per-Destination DCQCN (New Logic)
        auto it = m_destDcqcnStateMap.find(dip.Get());
        if (it == m_destDcqcnStateMap.end()) {
            // Ptr<DestDcqcnState> destState = CreateObject<DestDcqcnState>();
            Ptr<DestDcqcnState> destState = Ptr<DestDcqcnState>(new DestDcqcnState());
            destState->m_rate = m_bps;
            destState->m_targetRate = m_bps;
            destState->m_activeQps = 0;  // Initialize with zero active QPs
            it = m_destDcqcnStateMap.emplace(dip.Get(), destState).first;
        }
        it->second->m_activeQps++;
        qp->m_destDcqcnState = it->second;
        it->second->qps.push_back(qp);
        // NOTE: No rate distribution call needed here.
    } else if (m_cc_mode == 5) {  // Per-Lane DCQCN
        // Create lane group key from dip only (sip is same for all QPs on this RdmaHw)
        uint64_t laneGroupKey = dip.Get();

        // Find or create LaneGroup
        auto it = m_laneGroupMap.find(laneGroupKey);
        if (it == m_laneGroupMap.end()) {
            // Create new LaneGroup
            Ptr<LaneGroup> laneGroup = Ptr<LaneGroup>(new LaneGroup());
            // laneGroup->m_sip = sip.Get();
            laneGroup->m_dip = dip.Get();
            laneGroup->m_numLanes = m_lanesPerDestination;

            // Initialize all lanes
            for (uint32_t i = 0; i < m_lanesPerDestination; i++) {
                Ptr<LaneDcqcnState> lane = Ptr<LaneDcqcnState>(new LaneDcqcnState());
                lane->m_laneId = i;
                lane->m_rate = m_bps;
                lane->m_targetRate = m_bps;
                lane->m_runningQp = nullptr;
                laneGroup->m_lanes.push_back(lane);
            }

            it = m_laneGroupMap.emplace(laneGroupKey, laneGroup).first;
        }

        // Round-robin assignment to next lane
        Ptr<LaneGroup> laneGroup = it->second;

        // Safety checks
        if (laneGroup->m_lanes.empty()) {
            return;
        }

        uint32_t laneIdx = laneGroup->m_nextLaneIdx % laneGroup->m_lanes.size();
        Ptr<LaneDcqcnState> lane = laneGroup->m_lanes[laneIdx];
        laneGroup->m_nextLaneIdx = (laneIdx + 1) % laneGroup->m_lanes.size();

        // Associate QP with the lane
        qp->m_laneDcqcnState = lane;

        // Check if lane is idle or busy
        if (lane->m_runningQp == nullptr) {
            lane->m_runningQp = qp;
            m_nic[nic_idx].dev->NewQp(qp); // only running Lane sending Packet
        } else {
            lane->m_waitingQueue.push_back(qp);
        }
    } else if (m_cc_mode == 3) {
        qp->hp.m_curRate = m_bps;
        if (m_multipleRate) {
            for (uint32_t i = 0; i < IntHeader::maxHop; i++) qp->hp.hopState[i].Rc = m_bps;
        }
    } else if (m_cc_mode == 7) {
        qp->tmly.m_curRate = m_bps;
    }

    // Notify Nic
    if (m_cc_mode != 5) {
        m_nic[nic_idx].dev->NewQp(qp);
    }
}

void RdmaHw::DeleteQueuePair(Ptr<RdmaQueuePair> qp) {
    // remove qp from the m_qpMap
    uint64_t key = GetQpKey(qp->dip.Get(), qp->sport, qp->dport, qp->m_pg);

    // record to Akashic record
    NS_ASSERT(akashic_Qp.find(key) == akashic_Qp.end());  // should not be already existing
    akashic_Qp.insert(key);

    // delete
    m_qpMap.erase(key);
}

// DATA UDP's src = this key's dst (receiver's dst)
uint64_t RdmaHw::GetRxQpKey(uint32_t dip, uint16_t dport, uint16_t sport,
                            uint16_t pg) {  // Receiver perspective
    return ((uint64_t)dip << 32) | ((uint64_t)pg << 16) | ((uint64_t)sport << 16) |
           (uint64_t)dport;  // srcIP, srcPort
}

// src/dst are already flipped (this is calleld by UDP Data packet)
Ptr<RdmaRxQueuePair> RdmaHw::GetRxQp(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport,
                                     uint16_t pg, bool create) {
    uint64_t rxKey = GetRxQpKey(dip, dport, sport, pg);
    auto it = m_rxQpMap.find(rxKey);

    // main memory lookup
    if (it != m_rxQpMap.end()) return it->second;

    if (create) {
        // create new rx qp
        Ptr<RdmaRxQueuePair> q = CreateObject<RdmaRxQueuePair>();
        // init the qp
        q->sip = sip;
        q->dip = dip;
        q->sport = sport;
        q->dport = dport;
        q->m_ecn_source.qIndex = pg;
        q->m_flow_id = -1;     // unknown
        m_rxQpMap[rxKey] = q;  // store in map
        return q;
    }
    return NULL;
}
uint32_t RdmaHw::GetNicIdxOfRxQp(Ptr<RdmaRxQueuePair> q) {
    auto &v = m_rtTable[q->dip];
    if (v.size() > 0) {
        return v[q->GetHash() % v.size()];
    }
    NS_ASSERT_MSG(false, "We assume at least one NIC is alive");
    std::cout << "We assume at least one NIC is alive" << std::endl;
    exit(1);
}

// Receiver's perspective?
void RdmaHw::DeleteRxQp(uint32_t dip, uint16_t dport, uint16_t sport, uint16_t pg) {
    uint64_t key = GetRxQpKey(dip, dport, sport, pg);

    // record to Akashic record
    NS_ASSERT(akashic_RxQp.find(key) == akashic_RxQp.end());  // should not be already existing
    akashic_RxQp.insert(key);

    // delete
    m_rxQpMap.erase(key);
}

int RdmaHw::ReceiveUdp(Ptr<Packet> p, CustomHeader &ch) {
    uint8_t ecnbits = ch.GetIpv4EcnBits();

    // uint32_t payload_size = p->GetSize() - ch.GetSerializedSize();
    uint32_t headerSize = ch.GetSerializedSize();
    uint32_t packetSize = p->GetSize();
    uint32_t payload_size = (packetSize > headerSize) ? (packetSize - headerSize) : 0;

    // ======================== 新增Debug输出 START ========================
    // std::cout << "Time " << Simulator::Now().GetSeconds() << "s - Node " << m_node->GetId()
    //           << ": [ReceiveUdp Payload Calc] packetSize=" << packetSize
    //           << ", headerSize=" << headerSize
    //           << ", calculated_payload_size=" << payload_size << std::endl;
    // ======================== 新增Debug输出 END ==========================


    // find corresponding rx queue pair
    Ptr<RdmaRxQueuePair> rxQp =
        GetRxQp(ch.dip, ch.sip, ch.udp.dport, ch.udp.sport, ch.udp.pg, true);
    if (rxQp == NULL) {
        uint64_t rxKey = GetRxQpKey(ch.sip, ch.udp.sport, ch.udp.dport, ch.udp.pg);
        if (akashic_RxQp.find(rxKey) != akashic_RxQp.end()) {
            // printf("[GetRxQPUDP] Akashic access: %u(%d) -> %u(%d)\n", this->m_node->GetId(),
            // ch.udp.dport, ch.sip, ch.udp.sport);
            return 1;  // just drop
        } else {
            printf("ERROR: UDP NIC cannot find the flow\n");
            exit(1);
        }
    }

    if (ecnbits != 0) {
        rxQp->m_ecn_source.ecnbits |= ecnbits;
        rxQp->m_ecn_source.qfb++;
    }

    rxQp->m_ecn_source.total++;
    rxQp->m_milestone_rx = m_ack_interval;

    if (rxQp->m_flow_id < 0) {
        FlowIDNUMTag fit;
        if (p->PeekPacketTag(fit)) {
            rxQp->m_flow_id = fit.GetId();
        }
    }

    bool cnp_check = false;
    /*modification begin*/
    // if(m_node->GetId() == 98 && ch.udp.dport == 3904)
    // {
    //     std::cout << Simulator::Now().GetTimeStep()
    //         << " [ReceiveUDP] Node: " << m_node->GetId()
    //         << ", Seq: " << ch.udp.seq
    //         << ", SrcPort: " << ch.udp.sport
    //         << ", DstPort: " << ch.udp.dport
    //         << ", ECN: " << static_cast<uint32_t>(ecnbits)
    //         << ", PayloadSize: " << payload_size
    //         << std::endl;
    // }
    /*modification end*/
    int x = ReceiverCheckSeq(ch.udp.seq, rxQp, payload_size, cnp_check);

    if(m_dcp && !m_adaptiveRouting && x == 1) {
        uint32_t flowsize = 0;
        FlowsizeTag tag;
        bool foundunFlowsize = p->PeekPacketTag(tag);
        if (foundunFlowsize) {
            flowsize = tag.GetValue();
        }
        if(rxQp->ReceiverNextExpectedSeq >= flowsize) {
            //std::cout << "next seq: "  << rxQp->ReceiverNextExpectedSeq << " "<< tag.GetValue() << std::endl;
            x = 7;
        } else if (m_dcp_ack_opt && !cnp_check && !ecnbits) {
            x = 5;
        }
    }

    if (x == 1 || x == 2 || x == 6 || x == 7) {  // generate ACK or NACK
        qbbHeader seqh;
        seqh.SetSeq(rxQp->ReceiverNextExpectedSeq);
        seqh.SetPG(ch.udp.pg);
        seqh.SetSport(ch.udp.dport);
        seqh.SetDport(ch.udp.sport);
        seqh.SetIntHeader(ch.udp.ih);

        if(m_dcp) {
            if (x == 2) {
                seqh.SetSeq(ch.udp.seq);
            } else if( x != 7 && !m_adaptiveRouting && !m_dcp_ack_opt) {
                seqh.SetSeq(0);
            } 
        }

        if (m_irn) {
            if (x == 2) {
                seqh.SetIrnNack(ch.udp.seq);
                seqh.SetIrnNackSize(payload_size);
            } else {
                seqh.SetIrnNack(0);  // NACK without ackSyndrome (ACK) in loss recovery mode
                seqh.SetIrnNackSize(0);
            }
        }

        if (ecnbits || cnp_check) {  // NACK accompanies with CNP packet
            // XXX monitor CNP generation at sender
            cnp_total++;
            if (ecnbits) cnp_by_ecn++;
            if (cnp_check) cnp_by_ooo++;
            seqh.SetCnp();
        }

        Ptr<Packet> newp =
            Create<Packet>(std::max(60 - 14 - 20 - (int)seqh.GetSerializedSize(), 0));
        newp->AddHeader(seqh);

        Ipv4Header head;  // Prepare IPv4 header
        head.SetDestination(Ipv4Address(ch.sip));
        head.SetSource(Ipv4Address(ch.dip));
        // head.SetProtocol(x == 1 ? 0xFC : 0xFD);  // ack=0xFC nack=0xFD
        if (x == 1 || x == 7) {
            head.SetProtocol(0xFC);
        } else {
            head.SetProtocol(0xFD);
        }
        head.SetTtl(64);
        head.SetPayloadSize(newp->GetSize());
        head.SetIdentification(rxQp->m_ipid++);

        {
            FlowIDNUMTag fit;
            if (p->PeekPacketTag(fit)) {
                newp->AddPacketTag(fit);
            }

            // Copy LaneIdTag for per-lane ECMP routing
            LaneIdTag laneTag;
            if (p->PeekPacketTag(laneTag)) {
                newp->AddPacketTag(laneTag);
            }
        }

        newp->AddHeader(head);
        AddHeader(newp, 0x800);  // Attach PPP header

        // send
        uint32_t nic_idx = GetNicIdxOfRxQp(rxQp);
        m_nic[nic_idx].dev->RdmaEnqueueHighPrioQ(newp);
        m_nic[nic_idx].dev->TriggerTransmit();
    }
    return 0;
}

int RdmaHw::ReceiveCnp(Ptr<Packet> p, CustomHeader &ch) {
    std::cerr << "ReceiveCnp is called. Exit this program." << std::endl;
    exit(1);
    // QCN on NIC
    // This is a Congestion signal
    // Then, extract data from the congestion packet.
    // We assume, without verify, the packet is destinated to me
    uint32_t qIndex = ch.cnp.qIndex;
    if (qIndex == 1) {  // DCTCP
        std::cout << "TCP--ignore\n";
        return 0;
    }
    NS_ASSERT(ch.cnp.fid == ch.udp.dport);
    uint16_t udpport = ch.cnp.fid;  // corresponds to the sport (CNP's dport)
    uint16_t sport = ch.udp.sport;  // corresponds to the dport (CNP's sport)
    uint8_t ecnbits = ch.cnp.ecnBits;
    uint16_t qfb = ch.cnp.qfb;
    uint16_t total = ch.cnp.total;

    uint32_t i;
    // get qp
    uint64_t key = GetQpKey(ch.sip, udpport, sport, qIndex);
    Ptr<RdmaQueuePair> qp = GetQp(key);
    if (qp == NULL) {
        // lookup akashic memory
        if (akashic_Qp.find(key) != akashic_Qp.end()) {
            // printf("[GetQPCNP] Akashic access: %u(%d) -> %u(%d)\n", this->m_node->GetId(),
            // udpport, ch.sip, sport);
            return 1;  // just drop
        } else {
            printf("ERROR: QCN NIC cannot find the flow\n");
            exit(1);
        }
    }
    // get nic
    uint32_t nic_idx = GetNicIdxOfQp(qp);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    if (qp->m_rate == 0)  // lazy initialization
    {
        qp->m_rate = dev->GetDataRate();
        if (m_cc_mode == 1) {
            qp->mlx.m_targetRate = dev->GetDataRate();
        } else if (m_cc_mode == 3) {
            qp->hp.m_curRate = dev->GetDataRate();
            if (m_multipleRate) {
                for (uint32_t i = 0; i < IntHeader::maxHop; i++)
                    qp->hp.hopState[i].Rc = dev->GetDataRate();
            }
        } else if (m_cc_mode == 7) {
            qp->tmly.m_curRate = dev->GetDataRate();
        }
    }
    return 0;
}

int RdmaHw::ReceiveAck(Ptr<Packet> p, CustomHeader &ch) {
    uint16_t qIndex = ch.ack.pg;
    uint16_t port = ch.ack.dport;   // sport for this host
    uint16_t sport = ch.ack.sport;  // dport for this host (sport of ACK packet)
    uint32_t seq = ch.ack.seq;
    uint8_t cnp = (ch.ack.flags >> qbbHeader::FLAG_CNP) & 1;
    int i;
    uint64_t key = GetQpKey(ch.sip, port, sport, qIndex);
    Ptr<RdmaQueuePair> qp = GetQp(key);
    if (qp == NULL) {
        // lookup akashic memory
        if (akashic_Qp.find(key) != akashic_Qp.end()) {
            // printf("[GetQPACK] Akashic access: %u(%d) -> %u(%d)\n", this->m_node->GetId(), port,
            // ch.sip, sport);
            return 1;
        } else {
            printf("ERROR: Node: %u %s - NIC cannot find the flow\n", m_node->GetId(),
                   (ch.l3Prot == 0xFC ? "ACK" : "NACK"));
            // ======================== 新增Debug输出 START ========================
            // This is a fatal error. The ACK/NACK is for a completely unknown flow.
            // std::cerr << "Time " << Simulator::Now().GetSeconds() << "s - Node " << m_node->GetId()
            //           << ": [ERROR] Received a " << (ch.l3Prot == 0xFC ? "ACK" : "NACK")
            //           << " for an UNKNOWN flow." << std::endl;
            // std::cerr << "  - Details used for lookup:" << std::endl;
            // std::cerr << "    - NACK Source IP (Original Dest): " << Ipv4Address(ch.sip) << std::endl;
            // std::cerr << "    - Orig Src Port (NACK Dest):      " << port << std::endl;
            // std::cerr << "    - Orig Dest Port (NACK Src):      " << sport << std::endl;
            // std::cerr << "    - Priority Group:                 " << qIndex << std::endl;
            // std::cerr << "    - Generated Lookup Key:           " << key << std::endl;
            // ======================== 新增Debug输出 END ==========================
            exit(1);
        }
    }

    uint32_t nic_idx = GetNicIdxOfQp(qp);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    if (m_ack_interval == 0)
        std::cout << "ERROR: shouldn't receive ack\n";
    else {
        // record the old snd_una value
        uint64_t old_una = qp->snd_una;
        // DCP 
        if (m_dcp) {
            // 如果是NACK包 (由Trimming触发)
            if (ch.l3Prot == 0xFD) { 
                // 既然已经是NACK了，直接获取序列号，不再检查是否>0
                uint32_t lostSeq = ch.ack.seq;

                // 检查这个包是否真的还在飞行中
                if (qp->dcp.inflightPackets.count(lostSeq)) {
                    // std::cout << "Time " << Simulator::Now().GetSeconds() << "s - Node " << m_node->GetId()
                    //   << ": [DCP NACK] Received NACK for seq=" << lostSeq
                    //   << ". Queuing for retransmission." << std::endl;
                    // 只记录需要重传的seq，不立即重传
                    qp->dcp.retransmissionQueue.insert(lostSeq);
                }
                if (m_timeoutSlowStartMode != 0) {
                    Time now = Simulator::Now();
                    if (now - qp->dcp.m_lastSlowStartTime >= m_dcp_rto) {
                        qp->dcp.m_lastSlowStartTime = now;
                        ResetDcqcnStateOnTimeout(qp);
                    }
                }
            }
            // 如果是ACK包
            else {
                if(m_adaptiveRouting) {
                    qp->Acknowledge(seq);
                    if(seq >= qp->m_size ) {
                        qp->dcp.inflightPackets.clear();
                        qp->dcp.retransmissionQueue.clear();
                    }
                } else if (ch.ack.seq >= qp->m_size) {
                    // std::cout << "Time " << Simulator::Now().GetSeconds() << "s - Node " << m_node->GetId()
                    //   << ": [DCP Final ACK] Received final ACK for flow (seq=" << ch.ack.seq
                    //   << "). Cleaning up QP." << std::endl;
                    qp->Acknowledge(qp->m_size);
                    qp->dcp.inflightPackets.clear();
                    qp->dcp.retransmissionQueue.clear();
                }
            }
        } else {
            if (!m_backto0) {
                qp->Acknowledge(seq);
            } else {
                uint32_t goback_seq = seq / m_chunk * m_chunk;
                qp->Acknowledge(goback_seq);
            }
            if (qp->irn.m_enabled) {
                // handle NACK
                NS_ASSERT(ch.l3Prot == 0xFD);

                // for bdp-fc calculation update m_irn_maxAck
                if (seq > qp->irn.m_highest_ack) qp->irn.m_highest_ack = seq;
                        

                if (ch.ack.irnNackSize != 0) {
                    // ch.ack.irnNack contains the seq triggered this NACK
                    qp->irn.m_sack.sack(ch.ack.irnNack, ch.ack.irnNackSize);
                }

                uint32_t sack_seq, sack_len;
                if (qp->irn.m_sack.peekFrontBlock(&sack_seq, &sack_len)) {
                    if (qp->snd_una == sack_seq) {
                        qp->snd_una += sack_len;
                    }
                }

                qp->irn.m_sack.discardUpTo(qp->snd_una);

                if (qp->snd_nxt < qp->snd_una) {
                    qp->snd_nxt = qp->snd_una;
                }
                // if (qp->irn.m_sack.IsEmpty())  { //
                if (qp->irn.m_recovery && qp->snd_una >= qp->irn.m_recovery_seq) {
                    qp->irn.m_recovery = false;
                }
            } else {
                if (qp->snd_nxt < qp->snd_una) {
                    qp->snd_nxt = qp->snd_una;
                }
            }   
        }
        // if(m_node->GetId() == 0 && sport == 3904)
        // {
            // std::cout << Simulator::Now().GetTimeStep()
            //             << " [ReceiveAck] Node: " << m_node->GetId()
            //             << ", Type: " << (ch.l3Prot == 0xFC ? "ACK" : "NACK")
            //             << ", Seq: " << seq
            //             << ", SrcPort: " << sport
            //             << ", DstPort: " << port
            //             << ", SACK: " << ch.ack.irnNack
            //             << ", SACKsize: " << ch.ack.irnNackSize
            //             << ", UnackSeq: " << qp->snd_una
            //             << ", OldUna: " << old_una
            //             << std::endl;
        // }
        
        if (qp->snd_una > old_una) {
            m_accAckedBytes += (qp->snd_una - old_una);
        }

        if(qp->ChangeNotActive() && m_cc_mode == 2){
            if(qp->m_destDcqcnState->m_activeQps > 0) {
                qp->m_destDcqcnState->m_activeQps--;
            }
        }

        if (qp->IsFinished()) {
            QpComplete(qp);
        }
    }

    /**
     * IB Spec Vol. 1 o9-85
     * The requester need not separately time each request launched into the
     * fabric, but instead simply begins the timer whenever it is expecting a response.
     * Once started, the timer is restarted each time an acknowledge
     * packet is received as long as there are outstanding expected responses.
     * The timer does not detect the loss of a particular expected acknowledge
     * packet, but rather simply detects the persistent absence of response
     * packets.
     * */
    if (!qp->IsFinished() && qp->GetOnTheFly() > 0) {
        if (qp->m_retransmit.IsRunning()) qp->m_retransmit.Cancel();
        qp->m_retransmit = Simulator::Schedule(qp->GetRto(m_mtu), &RdmaHw::HandleTimeout, this, qp,
                                               qp->GetRto(m_mtu));
    }

    if (m_irn) {
        if (ch.ack.irnNackSize != 0) {
            if(m_adaptiveRouting)
            {
                std::cout << "NACK received, but m_adaptiveRouting is not enabled. "
                          << "This should not happen." << std::endl;
            }
            if (!qp->irn.m_recovery) {
                qp->irn.m_recovery_seq = qp->snd_nxt;
                RecoverQueue(qp);
                qp->irn.m_recovery = true;
            }
        } else {
            if (qp->irn.m_recovery) {
                qp->irn.m_recovery = false;
            }
        }

    } else if (ch.l3Prot == 0xFD)  // NACK
    {
        // if(m_adaptiveRouting && !m_dcp)
        // {
        //     std::cout << "NACK received, but m_adaptiveRouting is not enabled. "
        //           << "This should not happen." << std::endl;
        // }
        if(!m_dcp) RecoverQueue(qp);
    }

    // handle cnp
    if (cnp) {
        if (m_cc_mode == 1) {  // mlx version
            cnp_received_mlx(qp);
        } else if (m_cc_mode == 2) {
            cnp_received_mlx_Dest(qp);
        }
        //COMMENTED OUT FOR DEBUGGING
        else if (m_cc_mode == 5) {  // Per-Lane DCQCN
            cnp_received_mlx_Lane(qp);
        }
    } 

    if (m_cc_mode == 3) {
        HandleAckHp(qp, p, ch);
    } else if (m_cc_mode == 7) {
        HandleAckTimely(qp, p, ch);
    } else if (m_cc_mode == 8) {
        HandleAckDctcp(qp, p, ch);
    }
    // ACK may advance the on-the-fly window, allowing more packets to send
    dev->TriggerTransmit();
    return 0;
}

size_t RdmaHw::getIrnBufferOverhead() {
    size_t overhead = 0;
    for (auto it = m_rxQpMap.begin(); it != m_rxQpMap.end(); it++) {
        overhead += it->second->m_irn_sack_.getSackBufferOverhead();
    }
    return overhead;
}

int RdmaHw::Receive(Ptr<Packet> p, CustomHeader &ch) {
    // #if (SLB_DEBUG == true)
    //     std::cout << "[RdmaHw::Receive] Node(" << m_node->GetId() << ")," << PARSE_FIVE_TUPLE(ch)
    //     << "l3Prot:" << ch.l3Prot << ",at" << Simulator::Now() << std::endl;
    // #endif
    if (ch.l3Prot == 0x11) {  // UDP
        return ReceiveUdp(p, ch);
    } else if (ch.l3Prot == 0xFF) {  // CNP
        return ReceiveCnp(p, ch);
    } else if (ch.l3Prot == 0xFD) {  // NACK
        return ReceiveAck(p, ch);
    } else if (ch.l3Prot == 0xFC) {  // ACK
        return ReceiveAck(p, ch);
    }
    return 0;
}

/**
 * @brief Check sequence number when UDP DATA is received
 *
 * @return int
 * 0: should not reach here
 * 1: generate ACK
 * 2: still in loss recovery of IRN
 * 4: OoO, but skip to send NACK as it is already NACKed.
 * 6: NACK but functionality is ACK (indicating all packets are received)
 */
int RdmaHw::ReceiverCheckSeq(uint32_t seq, Ptr<RdmaRxQueuePair> q, uint32_t size, bool &cnp) {
    uint32_t expected = q->ReceiverNextExpectedSeq;
    Settings::RecordOutOfOrderPacket(seq, expected);
    if (m_dcp) {
        if(size == 0) {
            // std::cout << "Time " << Simulator::Now().GetSeconds() << "s - Node " << m_node->GetId()
            //       << ": [DCP Receiver] Got TRIMMED packet (seq=" << seq << ", size=0). Triggering NACK." << std::endl;
            cnp = true;
            return 2;
        }
        else {
            if(seq >= q->ReceiverNextExpectedSeq)
            {
                q->m_recvTracker.Insert(seq, size);
                uint32_t newExpected = q->m_recvTracker.GetNextExpectedSeq();
                if(newExpected > q->ReceiverNextExpectedSeq) {
                    q->ReceiverNextExpectedSeq = newExpected;
                    if (q->ReceiverNextExpectedSeq >= q->m_milestone_rx) {
                        q->m_milestone_rx += m_ack_interval;
                        // std::cout << "[Recv] Ack triggered: milestone reached. Next milestone: "
                        //       << q->m_milestone_rx << "\n";
                        return 1; // 发 ACK
                    } else if (q->ReceiverNextExpectedSeq % m_chunk == 0) {
                        // std::cout << "[Recv] Ack triggered: chunk boundary reached.\n";
                        return 1; // 发 ACK
                    } else {
                        // std::cout << "[Recv] No ack: waiting for more data.\n";
                        return 5; // 静默
                    }
                } else {
                    return 5;
                }
            } else {
                return 1;
            }
        }
    }
    
    if (m_adaptiveRouting) {
        if(seq >= q->ReceiverNextExpectedSeq)
        {
            uint64_t ooo_bytes_before_insert = q->m_recvTracker.GetOutOfOrderBytes();
            // std::cout << "[Recv] Insert block: [" << seq << ", " << (seq + size) << ")\n";
            q->m_recvTracker.Insert(seq, size);
            uint32_t newExpected = q->m_recvTracker.GetNextExpectedSeq();
            // std::cout << "[Recv] New expected: " << newExpected 
            //       << " (Previous expected: " << q->ReceiverNextExpectedSeq << ")\n";

            if (newExpected > q->ReceiverNextExpectedSeq) {
                q->ReceiverNextExpectedSeq = newExpected;
                Settings::ooo_burst_size_counts[ooo_bytes_before_insert]++;

                if (q->ReceiverNextExpectedSeq >= q->m_milestone_rx) {
                    q->m_milestone_rx += m_ack_interval;
                    // std::cout << "[Recv] Ack triggered: milestone reached. Next milestone: "
                    //       << q->m_milestone_rx << "\n";
                    return 1; // 发 ACK
                } else if (q->ReceiverNextExpectedSeq % m_chunk == 0) {
                    // std::cout << "[Recv] Ack triggered: chunk boundary reached.\n";
                    return 1; // 发 ACK
                } else {
                    // std::cout << "[Recv] No ack: waiting for more data.\n";
                    return 5; // 静默
                }
            } else {
                // 没推进 expected，说明收到的是重复包或乱序包
                // std::cout << "[Recv] Duplicate or out-of-order: no progress.\n";
                return 5; // 静默
            }
        } else {
            return 1;
        }
    }
    if (seq == expected || (seq < expected && seq + size >= expected)) {
        if (m_irn) {
            if (q->m_milestone_rx < seq + size) q->m_milestone_rx = seq + size;
            q->ReceiverNextExpectedSeq += size - (expected - seq);
            {
                uint32_t sack_seq, sack_len;
                if (q->m_irn_sack_.peekFrontBlock(&sack_seq, &sack_len)) {
                    if (sack_seq <= q->ReceiverNextExpectedSeq)
                        q->ReceiverNextExpectedSeq +=
                            (sack_len - (q->ReceiverNextExpectedSeq - sack_seq));
                }
            }
            size_t progress = q->m_irn_sack_.discardUpTo(q->ReceiverNextExpectedSeq);
            if (q->m_irn_sack_.IsEmpty()) {
                return 6;  // This generates NACK, but actually functions as an ACK (indicates all
                           // packet has been received)
            } else {
                // should we put nack timer here
                return 2;  // Still in loss recovery mode of IRN
            }
            return 0;  // should not reach here
        }

        q->ReceiverNextExpectedSeq += size - (expected - seq);
        if (q->ReceiverNextExpectedSeq >= q->m_milestone_rx) {
            q->m_milestone_rx +=
                m_ack_interval;  // if ack_interval is small (e.g., 1), condition is meaningless
            return 1;            // Generate ACK
        } else if (q->ReceiverNextExpectedSeq % m_chunk == 0) {
            return 1;
        } else {
            return 5;
        }
    } else if (seq > expected) {
        // Generate NACK
        if (m_irn) {
            if (q->m_milestone_rx < seq + size) q->m_milestone_rx = seq + size;

            // if seq is already nacked, check for nacktimer
            if (q->m_irn_sack_.blockExists(seq, size) && Simulator::Now() < q->m_nackTimer) {
                return 4;  // don't need to send nack yet
            }
            q->m_nackTimer = Simulator::Now() + MicroSeconds(m_nack_interval);
            q->m_irn_sack_.sack(seq, size);  // set SACK
            NS_ASSERT(q->m_irn_sack_.discardUpTo(expected) ==
                      0);  // SACK blocks must be larger than expected
            cnp = true;    // XXX: out-of-order should accompany with CNP (?) TODO: Check on CX6
            return 2;      // generate SACK
        }
        if (Simulator::Now() >= q->m_nackTimer || q->m_lastNACK != expected) {  // new NACK
            q->m_nackTimer = Simulator::Now() + MicroSeconds(m_nack_interval);
            q->m_lastNACK = expected;
            if (m_backto0) {
                q->ReceiverNextExpectedSeq = q->ReceiverNextExpectedSeq / m_chunk * m_chunk;
            }
            cnp = true;  // XXX: out-of-order should accompany with CNP (?) TODO: Check on CX6
            return 2;
        } else {
            // skip to send NACK
            return 4;
        }
    } else {
        // Duplicate.
        if (m_irn) {
            // if (q->ReceiverNextExpectedSeq - 1 == q->m_milestone_rx) {
            // 	return 6; // This generates NACK, but actually functions as an ACK (indicates all
            // packet has been received)
            // }
            if (q->m_irn_sack_.IsEmpty()) {
                return 6;  // This generates NACK, but actually functions as an ACK (indicates all
                           // packet has been received)
            } else {
                // should we put nack timer here
                return 2;  // Still in loss recovery mode of IRN
            }
        }
        // Duplicate.
        return 1;  // According to IB Spec C9-110
                   /**
                    * IB Spec C9-110
                    * A responder shall respond to all duplicate requests in PSN order;
                    * i.e. the request with the (logically) earliest PSN shall be executed first. If,
                    * while responding to a new or duplicate request, a duplicate request is received
                    * with a logically earlier PSN, the responder shall cease responding
                    * to the original request and shall begin responding to the duplicate request
                    * with the logically earlier PSN.
                    */
    }
}

void RdmaHw::AddHeader(Ptr<Packet> p, uint16_t protocolNumber) {
    PppHeader ppp;
    ppp.SetProtocol(EtherToPpp(protocolNumber));
    p->AddHeader(ppp);
}

uint16_t RdmaHw::EtherToPpp(uint16_t proto) {
    switch (proto) {
        case 0x0800:
            return 0x0021;  // IPv4
        case 0x86DD:
            return 0x0057;  // IPv6
        default:
            NS_ASSERT_MSG(false, "PPP Protocol number not defined!");
    }
    return 0;
}

void RdmaHw::RecoverQueue(Ptr<RdmaQueuePair> qp) {
    qp->snd_nxt = qp->snd_una;
    if(m_dcp) {
        qp->dcp.inflightPackets.clear();
        qp->dcp.retransmissionQueue.clear();
    }
    if(m_cc_mode == 2) {
        qp->m_destDcqcnState->m_activeQps++;
    }
}

void RdmaHw::QpComplete(Ptr<RdmaQueuePair> qp) {
    NS_ASSERT(!m_qpCompleteCallback.IsNull());
    if (m_cc_mode == 1) {
        Simulator::Cancel(qp->mlx.m_eventUpdateAlpha);
        Simulator::Cancel(qp->mlx.m_eventDecreaseRate);
        Simulator::Cancel(qp->mlx.m_rpTimer);
    }
    // Remove QP from the shared state's tracking list for per-destination mode.
    // Note: We do NOT cancel the shared timers.
    // Note: We do NOT clear qp->m_destDcqcnState for the same reason as lane mode.
    if (m_cc_mode == 2 && qp->m_destDcqcnState) {
        qp->m_destDcqcnState->qps.remove(qp);
    }
    // Per-Lane mode: wakeup next waiting QP
    if (m_cc_mode == 5 && qp->m_laneDcqcnState) {
        Ptr<LaneDcqcnState> lane = qp->m_laneDcqcnState;
        // Clear the running QP if it's this one
        if (lane->m_runningQp == qp) {
            lane->m_runningQp = nullptr;
            // Wakeup the next QP in the waiting queue
            WakeupNextQpInLane(lane);
        } else {
            // QP might be in the waiting queue, remove it to prevent accessing freed memory
            lane->m_waitingQueue.remove(qp);
        }
        // NOTE: We do NOT clear qp->m_laneDcqcnState because:
        // - LaneDcqcnState is shared among multiple QPs for the same src-dst pair
        // - If delayed CNPs arrive after QP completion, they should still update the lane state
        // - The lane state will persist for future flows on the same lane
    }
    if (qp->m_retransmit.IsRunning()) qp->m_retransmit.Cancel();

    // This callback will log info. It also calls deletetion the rxQp on the receiver
    m_qpCompleteCallback(qp);
    // delete TxQueuePair
    DeleteQueuePair(qp);
}

void RdmaHw::SetLinkDown(Ptr<QbbNetDevice> dev) {
    printf("RdmaHw: node:%u a link down\n", m_node->GetId());
}

void RdmaHw::AddTableEntry(Ipv4Address &dstAddr, uint32_t intf_idx) {
    uint32_t dip = dstAddr.Get();
    m_rtTable[dip].push_back(intf_idx);
}

void RdmaHw::ClearTable() { m_rtTable.clear(); }

void RdmaHw::RedistributeQp() {
    // clear old qpGrp
    for (uint32_t i = 0; i < m_nic.size(); i++) {
        if (m_nic[i].dev == NULL) continue;
        m_nic[i].qpGrp->Clear();
    }

    // redistribute qp
    for (auto &it : m_qpMap) {
        Ptr<RdmaQueuePair> qp = it.second;
        uint32_t nic_idx = GetNicIdxOfQp(qp);
        m_nic[nic_idx].qpGrp->AddQp(qp);
        // Notify Nic
        m_nic[nic_idx].dev->ReassignedQp(qp);
    }
}

void RdmaHw::NotifyPacketDrop(uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg, uint32_t seq, uint32_t payloadSize) {
    uint64_t key = GetQpKey(dip, sport, dport, pg);
    Ptr<RdmaQueuePair> qp = GetQp(key);

    // CRITICAL: Check if QP exists BEFORE calling any functions on it
    if (qp == NULL) {
        return;
    }

    if (m_adaptiveRouting) {
        qp->RecordArDrop(seq);
    }

    if (!qp->ideal.m_enabled) {
        return;
    }

    if (m_cc_mode == 1) {  // mlx version
        cnp_received_mlx(qp);
    } else if (m_cc_mode == 2) {
        cnp_received_mlx_Dest(qp);
    }
    // COMMENTED OUT FOR DEBUGGING - Testing basic QP setup/wakeup only
    else if (m_cc_mode == 5) {  // Per-Lane DCQCN
        cnp_received_mlx_Lane(qp);
    }

    qp->ideal.droppedPackets[seq] = payloadSize;

    if(m_timeoutSlowStartMode != 0) ResetDcqcnStateOnTimeout(qp);

    uint32_t nic_idx = GetNicIdxOfQp(qp);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;
    dev->TriggerTransmit();
}

Ptr<Packet> RdmaHw::GetNxtPacket(Ptr<RdmaQueuePair> qp) {
    // Per-Lane mode: only the running QP can send packets
    // COMMENTED OUT FOR DEBUGGING - Testing basic QP setup/wakeup only
    // if (m_cc_mode == 5 && qp->m_laneDcqcnState) {
    //     Ptr<LaneDcqcnState> lane = qp->m_laneDcqcnState;
    //     if (lane->m_runningQp != qp) {
    //         // This QP is waiting in the queue, cannot send yet
    //         return nullptr;
    //     }
    // }

    uint32_t payload_size;
    uint32_t seq;
    bool isRetransmission = false;
    if (qp->ideal.m_enabled && !qp->ideal.droppedPackets.empty()) {
        isRetransmission = true;
        auto it = qp->ideal.droppedPackets.begin();
        seq = it->first;
        payload_size = it->second;
        qp->ideal.droppedPackets.erase(it);
    } else if (m_dcp && !qp->dcp.retransmissionQueue.empty()) {
        isRetransmission = true;
        seq = *qp->dcp.retransmissionQueue.begin();
        qp->dcp.retransmissionQueue.erase(qp->dcp.retransmissionQueue.begin());

        // 查找对应的负载大小
        auto it = qp->dcp.inflightPackets.find(seq);
        if (it != qp->dcp.inflightPackets.end()) {
            payload_size = it->second;
            // std::cout << "Time " << Simulator::Now().GetSeconds() << "s - Node " << m_node->GetId()
            //               << ": [DCP Retransmit] Retransmitting packet (seq=" << seq
            //               << ", size=" << payload_size << ")." << std::endl;
        } else {
            // 如果在inflight缓冲区找不到，说明该包可能已被最终ACK确认
            // 无需重传，直接返回
            NS_ASSERT_MSG(false, "DCP Logic Error: Retransmission seq (" << seq 
                        << ") not found in inflight buffer for an active QP. Flow ID: " 
                        << qp->m_flow_id);
            return nullptr;
        }
    } else {
        payload_size = qp->GetBytesLeft();
        if (m_mtu < payload_size) {  // possibly last packet
            payload_size = m_mtu;
        }
        seq = (uint32_t)qp->snd_nxt;
        // std::cout << "Time " << Simulator::Now().GetSeconds() << "s - Node " << m_node->GetId()
        //                   << ": [New Packet] Sending new packet (seq=" << seq
        //                   << ", size=" << payload_size << ")." << std::endl;
        if(m_dcp) {
            if (payload_size > 0) { // 仅当确实有数据要发送时才记录
                qp->dcp.inflightPackets[seq] = payload_size;
            }
        }
    }
    
    bool proceed_snd_nxt = true;
    qp->stat.txTotalPkts += 1;
    qp->stat.txTotalBytes += payload_size;

    // trace accumulated send packets
    m_accSentBytes += payload_size;

    Ptr<Packet> p = Create<Packet>(payload_size);

    // dcp add flow size tag
    if(m_dcp)
    {
        FlowsizeTag flowsizetag;
        flowsizetag.SetValue(qp->m_size);
        p->AddPacketTag(flowsizetag);
    }

    // add SeqTsHeader
    SeqTsHeader seqTs;
    seqTs.SetSeq(seq);
    seqTs.SetPG(qp->m_pg);
    p->AddHeader(seqTs);
    // add udp header
    UdpHeader udpHeader;
    udpHeader.SetDestinationPort(qp->dport);
    udpHeader.SetSourcePort(qp->sport);
    p->AddHeader(udpHeader);
    // add ipv4 header
    Ipv4Header ipHeader;
    ipHeader.SetSource(qp->sip);
    ipHeader.SetDestination(qp->dip);
    ipHeader.SetProtocol(0x11);
    ipHeader.SetPayloadSize(p->GetSize());
    ipHeader.SetTtl(64);
    ipHeader.SetTos(0);
    ipHeader.SetIdentification(qp->m_ipid);
    p->AddHeader(ipHeader);
    // add ppp header
    PppHeader ppp;
    ppp.SetProtocol(0x0021);  // EtherToPpp(0x800), see point-to-point-net-device.cc
    p->AddHeader(ppp);

    // attach Stat Tag
    uint8_t packet_pos = UINT8_MAX;
    {
        FlowIDNUMTag fint;
        if (!p->PeekPacketTag(fint)) {
            fint.SetId(qp->m_flow_id);
            fint.SetFlowSize(qp->m_size);
            p->AddPacketTag(fint);
        }

        // Add LaneIdTag for per-lane DCQCN mode
        if (m_cc_mode == 5 && qp->m_laneDcqcnState) {
            LaneIdTag laneTag;
            laneTag.SetLaneId(qp->m_laneDcqcnState->m_laneId);
            p->AddPacketTag(laneTag);
        }

        FlowStatTag fst;
        uint64_t size = qp->m_size;
        if (!p->PeekPacketTag(fst)) {
            if (size < m_mtu && qp->snd_nxt + payload_size >= qp->m_size) {
                fst.SetType(FlowStatTag::FLOW_START_AND_END);
            } else if (qp->snd_nxt + payload_size >= qp->m_size) {
                fst.SetType(FlowStatTag::FLOW_END);
            } else if (qp->snd_nxt == 0) {
                fst.SetType(FlowStatTag::FLOW_START);
            } else {
                fst.SetType(FlowStatTag::FLOW_NOTEND);
            }
            packet_pos = fst.GetType();
            fst.setInitiatedTime(Simulator::Now().GetSeconds());
            p->AddPacketTag(fst);
        }
    }

    if (qp->irn.m_enabled) {
        if (qp->irn.m_max_seq < seq) qp->irn.m_max_seq = seq;
    }

    if (!isRetransmission && proceed_snd_nxt)
    {
        // qp->snd_nxt += payload_size;
        uint32_t oldSndNxt = qp->snd_nxt;
        qp->snd_nxt += payload_size;

        // std::cout << "[Send] snd_nxt advanced from " 
        //         << oldSndNxt << " to " << qp->snd_nxt 
        //         << " (payload_size=" << payload_size << ")" 
        //         << std::endl;
    }

    qp->m_ipid++;

    // return
    return p;
}

void RdmaHw::PktSent(Ptr<RdmaQueuePair> qp, Ptr<Packet> pkt, Time interframeGap) {
    qp->lastPktSize = pkt->GetSize();
    UpdateNextAvail(qp, interframeGap, pkt->GetSize());

    if (pkt) {
        CustomHeader ch(CustomHeader::L2_Header | CustomHeader::L3_Header |
                        CustomHeader::L4_Header);
        pkt->PeekHeader(ch);
#if (SLB_DEBUG == true)
        std::cout << "[RdmaHw::PktSent] Node(" << m_node->GetId() << ")," << PARSE_FIVE_TUPLE(ch)
                  << "l3Prot:" << ch.l3Prot << ",at" << Simulator::Now() << std::endl;
#endif
        RdmaHw::nAllPkts += 1;
        if (ch.l3Prot == 0x11) {  // UDP

            // if(m_node->GetId() == 0 && ch.udp.dport == 3904)
            // {
            //     // 从 CustomHeader 中获取 ECN 位
            //     uint8_t ecnbits = ch.GetIpv4EcnBits();
            //     // 计算 payload 大小
            //     uint32_t payload_size = pkt->GetSize() - ch.GetSerializedSize();

            //     std::cout << Simulator::Now().GetTimeStep()
            //                 << " [PktSent_UDP] Node: " << m_node->GetId()
            //                 << ", Seq: " << ch.udp.seq
            //                 << ", SrcPort: " << ch.udp.sport
            //                 << ", DstPort: " << ch.udp.dport
            //                 << ", ECN: " << static_cast<uint32_t>(ecnbits)
            //                 << ", PayloadSize: " << payload_size
            //                 << std::endl;
            // }
            // Update Timer
            if (qp->m_retransmit.IsRunning()) qp->m_retransmit.Cancel();
            qp->m_retransmit = Simulator::Schedule(qp->GetRto(m_mtu), &RdmaHw::HandleTimeout, this,
                                                   qp, qp->GetRto(m_mtu));
        } else if (ch.l3Prot == 0xFC || ch.l3Prot == 0xFD || ch.l3Prot == 0xFF) {  // ACK, NACK, CNP
        } else if (ch.l3Prot == 0xFE) {                                            // PFC
        }
    }
}

void RdmaHw::HandleTimeout(Ptr<RdmaQueuePair> qp, Time rto) {
    // Assume Outstanding Packets are lost
    // std::cerr << "Timeout on qp=" << qp << std::endl;
    if (qp->IsFinished() || qp->GetOnTheFly() == 0) {
        return;
    }

    uint32_t nic_idx = GetNicIdxOfQp(qp);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    // IRN: disable timeouts when PFC is enabled to prevent spurious retransmissions
    if (qp->irn.m_enabled && dev->IsQbbEnabled()) return;

    if (acc_timeout_count.find(qp->m_flow_id) == acc_timeout_count.end())
        acc_timeout_count[qp->m_flow_id] = 0;
    acc_timeout_count[qp->m_flow_id]++;

    if (m_adaptiveRouting) {
        qp->RecordArTimeoutRetransmission();
    }

    // Call the new encapsulated function to reset congestion state.
    if ((qp->irn.m_enabled || qp->dcp.m_enabled) && m_timeoutSlowStartMode != 0) ResetDcqcnStateOnTimeout(qp);

    if (qp->irn.m_enabled) qp->irn.m_recovery = true;

    /*modification begin*/
    m_traceRetransmitStart(qp);
    qp->m_timeoutRetransmitCount++;
    /*modification end*/
    RecoverQueue(qp);
    dev->TriggerTransmit();
}

void RdmaHw::UpdateNextAvail(Ptr<RdmaQueuePair> qp, Time interframeGap, uint32_t pkt_size) {
    Time sendingTime;
    DataRate current_rate;

    if (m_cc_mode == 2 && qp->m_destDcqcnState) {
        // Per-destination mode: calculate fair share rate on the fly.
        Ptr<DestDcqcnState> destState = qp->m_destDcqcnState;
        // size_t num_qps = destState->qps.size();
        size_t num_qps = destState->m_activeQps;
        if (num_qps > 0) {
            // Divide the aggregate rate by the number of active QPs.
            uint64_t shared_bitrate = destState->m_rate.GetBitRate() / num_qps;
            current_rate = DataRate(shared_bitrate);
        } else {
            // Fallback for safety, though this case should not be hit for an active QP.
            current_rate = destState->m_rate;
        }
    } else if (m_cc_mode == 5 && qp->m_laneDcqcnState) {
        // Per-lane mode: use the lane's rate directly (no sharing needed)
        // since only one QP runs per lane at a time
        current_rate = qp->m_laneDcqcnState->m_rate;
    } else {
        // Per-QP mode: use the QP's individual rate.
        current_rate = qp->m_rate;
    }
    if (m_rateBound)
        // sendingTime = interframeGap + Seconds(qp->m_rate.CalculateTxTime(pkt_size));
        sendingTime = interframeGap + Seconds(current_rate.CalculateTxTime(pkt_size));
    else
        sendingTime = interframeGap + Seconds(qp->m_max_rate.CalculateTxTime(pkt_size));
    qp->m_nextAvail = Simulator::Now() + sendingTime;
}

void RdmaHw::ChangeRate(Ptr<RdmaQueuePair> qp, DataRate new_rate) {
#if 1
    Time sendingTime = Seconds(qp->m_rate.CalculateTxTime(qp->lastPktSize));
    Time new_sendintTime = Seconds(new_rate.CalculateTxTime(qp->lastPktSize));
    qp->m_nextAvail = qp->m_nextAvail + new_sendintTime - sendingTime;
    // update nic's next avail event
    uint32_t nic_idx = GetNicIdxOfQp(qp);
    m_nic[nic_idx].dev->UpdateNextAvail(qp->m_nextAvail);
#endif

    // change to new rate
    qp->m_rate = new_rate;
}

#define PRINT_LOG 0
/******************************
 * Mellanox's version of DCQCN
 *****************************/
void RdmaHw::UpdateAlphaMlx(Ptr<RdmaQueuePair> q) {
#if PRINT_LOG
// std::cout << Simulator::Now() << " alpha update:" << m_node->GetId() << ' ' << q->mlx.m_alpha <<
// ' ' << (int)q->mlx.m_alpha_cnp_arrived << '\n'; printf("%lu alpha update: %08x %08x %u %u
// %.6lf->", Simulator::Now().GetTimeStep(), q->sip.Get(), q->dip.Get(), q->sport, q->dport,
// q->mlx.m_alpha);
#endif
    if (q->mlx.m_alpha_cnp_arrived) {                       // cnp -> increase
        q->mlx.m_alpha = (1 - m_g) * q->mlx.m_alpha + m_g;  // binary feedback
    } else {                                                // no cnp -> decrease
        q->mlx.m_alpha = (1 - m_g) * q->mlx.m_alpha;        // binary feedback
    }
#if PRINT_LOG
// printf("%.6lf\n", q->mlx.m_alpha);
#endif
    q->mlx.m_alpha_cnp_arrived = false;  // clear the CNP_arrived bit
    ScheduleUpdateAlphaMlx(q);
}
void RdmaHw::ScheduleUpdateAlphaMlx(Ptr<RdmaQueuePair> q) {
    q->mlx.m_eventUpdateAlpha = Simulator::Schedule(MicroSeconds(m_alpha_resume_interval),
                                                    &RdmaHw::UpdateAlphaMlx, this, q);
}

void RdmaHw::cnp_received_mlx(Ptr<RdmaQueuePair> q) {
    if (!q) return;  // Safety check
    q->mlx.m_alpha_cnp_arrived = true;     // set CNP_arrived bit for alpha update
    q->mlx.m_decrease_cnp_arrived = true;  // set CNP_arrived bit for rate decrease
    if (q->mlx.m_first_cnp) {
        // init alpha
        q->mlx.m_alpha = 1;
        q->mlx.m_alpha_cnp_arrived = false;
        // schedule alpha update
        ScheduleUpdateAlphaMlx(q);
        // schedule rate decrease
        ScheduleDecreaseRateMlx(q, 1);  // add 1 ns to make sure rate decrease is after alpha update
        // set rate on first CNP
        q->mlx.m_targetRate = q->m_rate = m_rateOnFirstCNP * q->m_rate;
        q->mlx.m_first_cnp = false;
    }
}

void RdmaHw::CheckRateDecreaseMlx(Ptr<RdmaQueuePair> q) {
    ScheduleDecreaseRateMlx(q, 0);
    if (q->mlx.m_decrease_cnp_arrived) {
#if PRINT_LOG
        printf("%lu rate dec: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(),
               q->sip.Get(), q->dip.Get(), q->sport, q->dport,
               q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
#endif
        // DataRate oldRate = q->m_rate;

        bool clamp = true;
        if (!m_EcnClampTgtRate) {
            if (q->mlx.m_rpTimeStage == 0) clamp = false;
        }
        if (clamp) {
            q->mlx.m_targetRate = q->m_rate;
        }
        q->m_rate = std::max(m_minRate, q->m_rate * (1 - q->mlx.m_alpha / 2));
        // reset rate increase related things
        q->mlx.m_rpTimeStage = 0;
        q->mlx.m_decrease_cnp_arrived = false;
        Simulator::Cancel(q->mlx.m_rpTimer);
        q->mlx.m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset),
                                               &RdmaHw::RateIncEventTimerMlx, this, q);
        // if(m_node->GetId() == 0)
        // {
        //     std::cout << std::fixed << std::setprecision(3) // 设置后续浮点数格式
        //           << Simulator::Now().GetTimeStep()
        //           << " [Rate Decrease] QP(" << q->sport << "->" << q->dport << "): "
        //           << "Before: " << oldRate.GetBitRate() * 1e-9 << " Gbps, "
        //           << "After: " << q->m_rate.GetBitRate() * 1e-9 << " Gbps, "
        //           << "Alpha: " << std::setprecision(4) << q->mlx.m_alpha // Alpha精度设为4位
        //           << std::endl;
        // }
#if PRINT_LOG
        printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9,
               q->m_rate.GetBitRate() * 1e-9);
#endif
    }
}
void RdmaHw::ScheduleDecreaseRateMlx(Ptr<RdmaQueuePair> q, uint32_t delta) {
    q->mlx.m_eventDecreaseRate =
        Simulator::Schedule(MicroSeconds(m_rateDecreaseInterval) + NanoSeconds(delta),
                            &RdmaHw::CheckRateDecreaseMlx, this, q);
}

void RdmaHw::RateIncEventTimerMlx(Ptr<RdmaQueuePair> q) {
    q->mlx.m_rpTimer =
        Simulator::Schedule(MicroSeconds(m_rpgTimeReset), &RdmaHw::RateIncEventTimerMlx, this, q);
    RateIncEventMlx(q);
    q->mlx.m_rpTimeStage++;
}
void RdmaHw::RateIncEventMlx(Ptr<RdmaQueuePair> q) {
    // check which increase phase: fast recovery, active increase, hyper increase
    if (q->mlx.m_rpTimeStage < m_rpgThreshold) {  // fast recovery
        FastRecoveryMlx(q);
    } else if (q->mlx.m_rpTimeStage == m_rpgThreshold) {  // active increase
        ActiveIncreaseMlx(q);
    } else {  // hyper increase
        HyperIncreaseMlx(q);
    }
}

void RdmaHw::FastRecoveryMlx(Ptr<RdmaQueuePair> q) {
#if PRINT_LOG
    printf("%lu fast recovery: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(),
           q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
    // DataRate oldRate = q->m_rate;

    q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);
    // if(m_node->GetId() == 0)
    // {
    //     std::cout << std::fixed << std::setprecision(3)
    //           << Simulator::Now().GetTimeStep()
    //           << " [Fast Recovery] QP(" << q->sport << "->" << q->dport << "): "
    //           << "Before: " << oldRate.GetBitRate() * 1e-9 << " Gbps, "
    //           << "After: " << q->m_rate.GetBitRate() * 1e-9 << " Gbps, "
    //           << "Target: " << q->mlx.m_targetRate.GetBitRate() * 1e-9 << " Gbps"
    //           << std::endl;
    // }
#if PRINT_LOG
    printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
}
void RdmaHw::ActiveIncreaseMlx(Ptr<RdmaQueuePair> q) {
#if PRINT_LOG
    printf("%lu active inc: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(),
           q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
    // DataRate oldRate = q->m_rate;
    // DataRate oldTargetRate = q->mlx.m_targetRate;
    // get NIC
    uint32_t nic_idx = GetNicIdxOfQp(q);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;
    // increate rate
    q->mlx.m_targetRate += m_rai;
    if (q->mlx.m_targetRate > dev->GetDataRate()) q->mlx.m_targetRate = dev->GetDataRate();
    q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);
    // if(m_node->GetId() == 0)
    // {
    //     std::cout << std::fixed << std::setprecision(3)
    //           << Simulator::Now().GetTimeStep()
    //           << " [Active Increase] QP(" << q->sport << "->" << q->dport << "): "
    //           << "Rate Before: " << oldRate.GetBitRate() * 1e-9 << " -> "
    //           << "After: " << q->m_rate.GetBitRate() * 1e-9
    //           << " | Target Before: " << oldTargetRate.GetBitRate() * 1e-9 << " -> "
    //           << "After: " << q->mlx.m_targetRate.GetBitRate() * 1e-9
    //           << std::endl;
    // }
#if PRINT_LOG
    printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
}
void RdmaHw::HyperIncreaseMlx(Ptr<RdmaQueuePair> q) {
#if PRINT_LOG
    printf("%lu hyper inc: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(),
           q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
    // DataRate oldRate = q->m_rate;
    // DataRate oldTargetRate = q->mlx.m_targetRate;
    // get NIC
    uint32_t nic_idx = GetNicIdxOfQp(q);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;
    // increate rate
    q->mlx.m_targetRate += m_rhai;
    if (q->mlx.m_targetRate > dev->GetDataRate()) q->mlx.m_targetRate = dev->GetDataRate();
    q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);
    // if(m_node->GetId() == 0)
    // {
    //     std::cout << std::fixed << std::setprecision(3)
    //           << Simulator::Now().GetTimeStep()
    //           << " [Hyper Increase] QP(" << q->sport << "->" << q->dport << "): "
    //           << "Rate Before: " << oldRate.GetBitRate() * 1e-9 << " -> "
    //           << "After: " << q->m_rate.GetBitRate() * 1e-9
    //           << " | Target Before: " << oldTargetRate.GetBitRate() * 1e-9 << " -> "
    //           << "After: " << q->mlx.m_targetRate.GetBitRate() * 1e-9
    //           << std::endl;
    // }
#if PRINT_LOG
    printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
}

/**
 * @brief Resets the congestion control state for DCQCN upon a timeout event.
 *
 * @param qp The Queue Pair that experienced the timeout.
 */
void RdmaHw::ResetDcqcnStateOnTimeout(Ptr<RdmaQueuePair> qp) {
    // Reset congestion control state for DCQCN (modes 1 and 2)
    if (m_cc_mode == 1) { // Per-QP DCQCN
        if(m_timeoutSlowStartMode == 1)
        {
            // 1. Reset rate to the configured minimum.
            qp->m_rate = m_minRate;
            qp->mlx.m_targetRate = m_minRate;
        }
        else if(m_timeoutSlowStartMode >= 2)
        {
            uint32_t slowStartFactor = m_timeoutSlowStartMode;
            DataRate rateBeforeTimeout = slowStartFactor > 64 ? qp->m_max_rate : qp->m_rate;
            DataRate newRate = std::max(rateBeforeTimeout / slowStartFactor, m_minRate);
            qp->m_rate = newRate;
            qp->mlx.m_targetRate = newRate;
        }
        else
        {
            NS_FATAL_ERROR("Invalid timeout slow start mode");
        }

        // 2. Reset alpha to its initial value to be sensitive to new CNPs.
        qp->mlx.m_alpha = 1.0; 

        // 3. Reset the shared rate increase logic.
        qp->mlx.m_rpTimeStage = 0;
        Simulator::Cancel(qp->mlx.m_rpTimer);
        qp->mlx.m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset),
                                               &RdmaHw::RateIncEventTimerMlx, this, qp);
        qp->mlx.m_first_cnp = false; // Treat timeout as the first congestion signal.
    } else if (m_cc_mode == 2 && qp->m_destDcqcnState) { // Per-Destination DCQCN
        Ptr<DestDcqcnState> destState = qp->m_destDcqcnState;
        
        // 1. Reset the shared destination rate to the minimum.
        if(m_timeoutSlowStartMode == 1)
        {
            // Reset rate to the configured minimum.
            destState->m_rate = m_minRate;
            destState->m_targetRate = m_minRate;
        }
        else if(m_timeoutSlowStartMode == 2)
        {
            // Reset rate to /2.
            DataRate oldRate = destState->m_rate;
            DataRate newRate = std::max(oldRate / 2, m_minRate);
            destState->m_rate = newRate;
            destState->m_targetRate = std::max(oldRate / 2, m_minRate);
        }
        else
        {
            NS_FATAL_ERROR("Invalid timeout slow start mode");
        }

        // 2. Reset the shared alpha to its initial value.
        destState->m_alpha = 1.0;

        // 3. Reset the shared rate increase logic.
        destState->m_rpTimeStage = 0;
        Simulator::Cancel(destState->m_rpTimer);
        destState->m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset),
                                                   &RdmaHw::RateIncEventTimerMlx_Dest, this, destState);
        destState->m_first_cnp = false;
    } else if (m_cc_mode == 5 && qp->m_laneDcqcnState) { // Per-Lane DCQCN
        Ptr<LaneDcqcnState> laneState = qp->m_laneDcqcnState;

        // 1. Reset the lane rate based on timeout slow start mode
        if (m_timeoutSlowStartMode == 1) {
            // Reset rate to the configured minimum.
            laneState->m_rate = m_minRate;
            laneState->m_targetRate = m_minRate;
        } else if (m_timeoutSlowStartMode >= 2) {
            // Reset rate by dividing by slow start factor
            uint32_t slowStartFactor = m_timeoutSlowStartMode;
            DataRate oldRate = laneState->m_rate;
            DataRate newRate = std::max(oldRate / slowStartFactor, m_minRate);
            laneState->m_rate = newRate;
            laneState->m_targetRate = newRate;
        } else {
            NS_FATAL_ERROR("Invalid timeout slow start mode");
        }

        // 2. Reset the lane's alpha to its initial value
        laneState->m_alpha = 1.0;

        // 3. Reset the lane's rate increase logic
        laneState->m_rpTimeStage = 0;
        Simulator::Cancel(laneState->m_rpTimer);
        laneState->m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset),
                                                   &RdmaHw::RateIncEventTimerMlx_Lane, this, laneState);
        laneState->m_first_cnp = false;
    }
}

/****************************************************************
 * Mellanox's DCQCN - Per-Destination Implementation (Mode 2)
 ****************************************************************/

// NOTE: All calls to UpdateDestQpRates have been removed from these functions.

void RdmaHw::cnp_received_mlx_Dest(Ptr<RdmaQueuePair> q) {
    if (!q) return;  // Safety check
    Ptr<DestDcqcnState> destState = q->m_destDcqcnState;
    if (!destState) return;

    destState->m_alpha_cnp_arrived = true;
    destState->m_decrease_cnp_arrived = true;
    if (destState->m_first_cnp) {
        destState->m_alpha = 1;
        destState->m_alpha_cnp_arrived = false;
        ScheduleUpdateAlphaMlx_Dest(destState);
        ScheduleDecreaseRateMlx_Dest(destState, 1);
        DataRate newRate = m_rateOnFirstCNP * destState->m_rate;
        destState->m_targetRate = newRate;
        destState->m_rate = newRate;
        destState->m_first_cnp = false;
    }
}

void RdmaHw::UpdateAlphaMlx_Dest(Ptr<DestDcqcnState> destState) {
    if (destState->m_alpha_cnp_arrived) {
        destState->m_alpha = (1 - m_g) * destState->m_alpha + m_g;
    } else {
        destState->m_alpha = (1 - m_g) * destState->m_alpha;
    }
    destState->m_alpha_cnp_arrived = false;
    ScheduleUpdateAlphaMlx_Dest(destState);
}

void RdmaHw::ScheduleUpdateAlphaMlx_Dest(Ptr<DestDcqcnState> destState) {
    destState->m_eventUpdateAlpha = Simulator::Schedule(MicroSeconds(m_alpha_resume_interval),
                                                        &RdmaHw::UpdateAlphaMlx_Dest, this, destState);
}

void RdmaHw::CheckRateDecreaseMlx_Dest(Ptr<DestDcqcnState> destState) {
    ScheduleDecreaseRateMlx_Dest(destState, 0);
    if (destState->m_decrease_cnp_arrived) {
        bool clamp = !m_EcnClampTgtRate ? (destState->m_rpTimeStage != 0) : true;
        if (clamp) {
            destState->m_targetRate = destState->m_rate;
        }
        destState->m_rate = std::max(m_minRate, destState->m_rate * (1 - destState->m_alpha / 2));
        
        destState->m_rpTimeStage = 0;
        destState->m_decrease_cnp_arrived = false;
        Simulator::Cancel(destState->m_rpTimer);
        destState->m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset),
                                                   &RdmaHw::RateIncEventTimerMlx_Dest, this, destState);
    }
}

void RdmaHw::ScheduleDecreaseRateMlx_Dest(Ptr<DestDcqcnState> destState, uint32_t delta) {
    destState->m_eventDecreaseRate =
        Simulator::Schedule(MicroSeconds(m_rateDecreaseInterval) + NanoSeconds(delta),
                            &RdmaHw::CheckRateDecreaseMlx_Dest, this, destState);
}

void RdmaHw::RateIncEventTimerMlx_Dest(Ptr<DestDcqcnState> destState) {
    destState->m_rpTimer =
        Simulator::Schedule(MicroSeconds(m_rpgTimeReset), &RdmaHw::RateIncEventTimerMlx_Dest, this, destState);
    RateIncEventMlx_Dest(destState);
    destState->m_rpTimeStage++;
}

void RdmaHw::RateIncEventMlx_Dest(Ptr<DestDcqcnState> destState) {
    if (destState->m_rpTimeStage < m_rpgThreshold) {
        FastRecoveryMlx_Dest(destState);
    } else if (destState->m_rpTimeStage == m_rpgThreshold) {
        ActiveIncreaseMlx_Dest(destState);
    } else {
        HyperIncreaseMlx_Dest(destState);
    }
}

void RdmaHw::FastRecoveryMlx_Dest(Ptr<DestDcqcnState> destState) {
    destState->m_rate = (destState->m_rate / 2) + (destState->m_targetRate / 2);
}

void RdmaHw::ActiveIncreaseMlx_Dest(Ptr<DestDcqcnState> destState) {
    if (destState->qps.empty()) return;
    Ptr<RdmaQueuePair> q = destState->qps.front();
    uint32_t nic_idx = GetNicIdxOfQp(q);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    destState->m_targetRate += m_rai;
    if (destState->m_targetRate > dev->GetDataRate()) destState->m_targetRate = dev->GetDataRate();
    destState->m_rate = (destState->m_rate / 2) + (destState->m_targetRate / 2);
}

void RdmaHw::HyperIncreaseMlx_Dest(Ptr<DestDcqcnState> destState) {
    if (destState->qps.empty()) return;
    Ptr<RdmaQueuePair> q = destState->qps.front();
    uint32_t nic_idx = GetNicIdxOfQp(q);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    destState->m_targetRate += m_rhai;
    if (destState->m_targetRate > dev->GetDataRate()) destState->m_targetRate = dev->GetDataRate();
    destState->m_rate = (destState->m_rate / 2) + (destState->m_targetRate / 2);
}


/***********************
 * High Precision CC
 ***********************/
void RdmaHw::HandleAckHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {
    uint32_t ack_seq = ch.ack.seq;
    // update rate
    if (ack_seq > qp->hp.m_lastUpdateSeq) {  // if full RTT feedback is ready, do full update
        UpdateRateHp(qp, p, ch, false);
    } else {  // do fast react
        FastReactHp(qp, p, ch);
    }
}

void RdmaHw::UpdateRateHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool fast_react) {
    uint32_t next_seq = qp->snd_nxt;
    bool print = !fast_react || true;
    if (qp->hp.m_lastUpdateSeq == 0) {  // first RTT
        qp->hp.m_lastUpdateSeq = next_seq;
        // store INT
        IntHeader &ih = ch.ack.ih;
        NS_ASSERT(ih.nhop <= IntHeader::maxHop);
        for (uint32_t i = 0; i < ih.nhop; i++) qp->hp.hop[i] = ih.hop[i];
#if PRINT_LOG
        if (print) {
            printf("%lu %s %08x %08x %u %u [%u,%u,%u]", Simulator::Now().GetTimeStep(),
                   fast_react ? "fast" : "update", qp->sip.Get(), qp->dip.Get(), qp->sport,
                   qp->dport, qp->hp.m_lastUpdateSeq, ch.ack.seq, next_seq);
            for (uint32_t i = 0; i < ih.nhop; i++)
                printf(" %u %lu %lu", ih.hop[i].GetQlen(), ih.hop[i].GetBytes(),
                       ih.hop[i].GetTime());
            printf("\n");
        }
#endif
    } else {
        // check packet INT
        IntHeader &ih = ch.ack.ih;
        if (ih.nhop <= IntHeader::maxHop) {
            double max_c = 0;
            bool inStable = false;
#if PRINT_LOG
            if (print)
                printf("%lu %s %08x %08x %u %u [%u,%u,%u]", Simulator::Now().GetTimeStep(),
                       fast_react ? "fast" : "update", qp->sip.Get(), qp->dip.Get(), qp->sport,
                       qp->dport, qp->hp.m_lastUpdateSeq, ch.ack.seq, next_seq);
#endif
            // check each hop
            double U = 0;
            uint64_t dt = 0;
            bool updated[IntHeader::maxHop] = {false}, updated_any = false;
            NS_ASSERT(ih.nhop <= IntHeader::maxHop);
            for (uint32_t i = 0; i < ih.nhop; i++) {
                if (m_sampleFeedback) {
                    if (ih.hop[i].GetQlen() == 0 and fast_react) continue;
                }
                updated[i] = updated_any = true;
#if PRINT_LOG
                if (print)
                    printf(" %u(%u) %lu(%lu) %lu(%lu)", ih.hop[i].GetQlen(),
                           qp->hp.hop[i].GetQlen(), ih.hop[i].GetBytes(), qp->hp.hop[i].GetBytes(),
                           ih.hop[i].GetTime(), qp->hp.hop[i].GetTime());
#endif
                uint64_t tau = ih.hop[i].GetTimeDelta(qp->hp.hop[i]);
                ;
                double duration = tau * 1e-9;
                double txRate = (ih.hop[i].GetBytesDelta(qp->hp.hop[i])) * 8 / duration;
                double u = txRate / ih.hop[i].GetLineRate() +
                           (double)std::min(ih.hop[i].GetQlen(), qp->hp.hop[i].GetQlen()) *
                               qp->m_max_rate.GetBitRate() / ih.hop[i].GetLineRate() / qp->m_win;
#if PRINT_LOG
                if (print) printf(" %.3lf %.3lf", txRate, u);
#endif
                if (!m_multipleRate) {
                    // for aggregate (single R)
                    if (u > U) {
                        U = u;
                        dt = tau;
                    }
                } else {
                    // for per hop (per hop R)
                    if (tau > qp->m_baseRtt) tau = qp->m_baseRtt;
                    qp->hp.hopState[i].u =
                        (qp->hp.hopState[i].u * (qp->m_baseRtt - tau) + u * tau) /
                        double(qp->m_baseRtt);
                }
                qp->hp.hop[i] = ih.hop[i];
            }

            DataRate new_rate;
            int32_t new_incStage;
            DataRate new_rate_per_hop[IntHeader::maxHop];
            int32_t new_incStage_per_hop[IntHeader::maxHop];
            if (!m_multipleRate) {
                // for aggregate (single R)
                if (updated_any) {
                    if (dt > qp->m_baseRtt) dt = qp->m_baseRtt;
                    qp->hp.u = (qp->hp.u * (qp->m_baseRtt - dt) + U * dt) / double(qp->m_baseRtt);
                    max_c = qp->hp.u / m_targetUtil;

                    if (max_c >= 1 || qp->hp.m_incStage >= m_miThresh) {
                        new_rate = qp->hp.m_curRate / max_c + m_rai;
                        new_incStage = 0;
                    } else {
                        new_rate = qp->hp.m_curRate + m_rai;
                        new_incStage = qp->hp.m_incStage + 1;
                    }
                    if (new_rate < m_minRate) new_rate = m_minRate;
                    if (new_rate > qp->m_max_rate) new_rate = qp->m_max_rate;
#if PRINT_LOG
                    if (print) printf(" u=%.6lf U=%.3lf dt=%u max_c=%.3lf", qp->hp.u, U, dt, max_c);
#endif
#if PRINT_LOG
                    if (print)
                        printf(" rate:%.3lf->%.3lf\n", qp->hp.m_curRate.GetBitRate() * 1e-9,
                               new_rate.GetBitRate() * 1e-9);
#endif
                }
            } else {
                // for per hop (per hop R)
                new_rate = qp->m_max_rate;
                for (uint32_t i = 0; i < ih.nhop; i++) {
                    if (updated[i]) {
                        double c = qp->hp.hopState[i].u / m_targetUtil;
                        if (c >= 1 || qp->hp.hopState[i].incStage >= m_miThresh) {
                            new_rate_per_hop[i] = qp->hp.hopState[i].Rc / c + m_rai;
                            new_incStage_per_hop[i] = 0;
                        } else {
                            new_rate_per_hop[i] = qp->hp.hopState[i].Rc + m_rai;
                            new_incStage_per_hop[i] = qp->hp.hopState[i].incStage + 1;
                        }
                        // bound rate
                        if (new_rate_per_hop[i] < m_minRate) new_rate_per_hop[i] = m_minRate;
                        if (new_rate_per_hop[i] > qp->m_max_rate)
                            new_rate_per_hop[i] = qp->m_max_rate;
                        // find min new_rate
                        if (new_rate_per_hop[i] < new_rate) new_rate = new_rate_per_hop[i];
#if PRINT_LOG
                        if (print) printf(" [%u]u=%.6lf c=%.3lf", i, qp->hp.hopState[i].u, c);
#endif
#if PRINT_LOG
                        if (print)
                            printf(" %.3lf->%.3lf", qp->hp.hopState[i].Rc.GetBitRate() * 1e-9,
                                   new_rate.GetBitRate() * 1e-9);
#endif
                    } else {
                        if (qp->hp.hopState[i].Rc < new_rate) new_rate = qp->hp.hopState[i].Rc;
                    }
                }
#if PRINT_LOG
                printf("\n");
#endif
            }
            if (updated_any) ChangeRate(qp, new_rate);
            if (!fast_react) {
                if (updated_any) {
                    qp->hp.m_curRate = new_rate;
                    qp->hp.m_incStage = new_incStage;
                }
                if (m_multipleRate) {
                    // for per hop (per hop R)
                    for (uint32_t i = 0; i < ih.nhop; i++) {
                        if (updated[i]) {
                            qp->hp.hopState[i].Rc = new_rate_per_hop[i];
                            qp->hp.hopState[i].incStage = new_incStage_per_hop[i];
                        }
                    }
                }
            }
        }
        if (!fast_react) {
            if (next_seq > qp->hp.m_lastUpdateSeq)
                qp->hp.m_lastUpdateSeq = next_seq;  //+ rand() % 2 * m_mtu;
        }
    }
}

void RdmaHw::FastReactHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {
    if (m_fast_react) UpdateRateHp(qp, p, ch, true);
}

/**********************
 * TIMELY
 *********************/
void RdmaHw::HandleAckTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {
    uint32_t ack_seq = ch.ack.seq;
    // update rate
    if (ack_seq > qp->tmly.m_lastUpdateSeq) {  // if full RTT feedback is ready, do full update
        UpdateRateTimely(qp, p, ch, false);
    } else {  // do fast react
        FastReactTimely(qp, p, ch);
    }
}
void RdmaHw::UpdateRateTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool us) {
    uint32_t next_seq = qp->snd_nxt;
    uint64_t rtt = Simulator::Now().GetTimeStep() - ch.ack.ih.ts;
    bool print = !us;
    if (qp->tmly.m_lastUpdateSeq != 0) {  // not first RTT
        int64_t new_rtt_diff = (int64_t)rtt - (int64_t)qp->tmly.lastRtt;
        double rtt_diff = (1 - m_tmly_alpha) * qp->tmly.rttDiff + m_tmly_alpha * new_rtt_diff;
        double gradient = rtt_diff / m_tmly_minRtt;
        bool inc = false;
        double c = 0;
#if PRINT_LOG
        if (print)
            printf("%lu node:%u rtt:%lu rttDiff:%.0lf gradient:%.3lf rate:%.3lf",
                   Simulator::Now().GetTimeStep(), m_node->GetId(), rtt, rtt_diff, gradient,
                   qp->tmly.m_curRate.GetBitRate() * 1e-9);
#endif
        if (rtt < m_tmly_TLow) {
            inc = true;
        } else if (rtt > m_tmly_THigh) {
            c = 1 - m_tmly_beta * (1 - (double)m_tmly_THigh / rtt);
            inc = false;
        } else if (gradient <= 0) {
            inc = true;
        } else {
            c = 1 - m_tmly_beta * gradient;
            if (c < 0) c = 0;
            inc = false;
        }
        if (inc) {
            if (qp->tmly.m_incStage < 5) {
                qp->m_rate = qp->tmly.m_curRate + m_rai;
            } else {
                qp->m_rate = qp->tmly.m_curRate + m_rhai;
            }
            if (qp->m_rate > qp->m_max_rate) qp->m_rate = qp->m_max_rate;
            if (!us) {
                qp->tmly.m_curRate = qp->m_rate;
                qp->tmly.m_incStage++;
                qp->tmly.rttDiff = rtt_diff;
            }
        } else {
            qp->m_rate = std::max(m_minRate, qp->tmly.m_curRate * c);
            if (!us) {
                qp->tmly.m_curRate = qp->m_rate;
                qp->tmly.m_incStage = 0;
                qp->tmly.rttDiff = rtt_diff;
            }
        }
#if PRINT_LOG
        if (print) {
            printf(" %c %.3lf\n", inc ? '^' : 'v', qp->m_rate.GetBitRate() * 1e-9);
        }
#endif
    }
    if (!us && next_seq > qp->tmly.m_lastUpdateSeq) {
        qp->tmly.m_lastUpdateSeq = next_seq;
        // update
        qp->tmly.lastRtt = rtt;
    }
}
void RdmaHw::FastReactTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {}

/**********************
 * DCTCP
 *********************/
void RdmaHw::HandleAckDctcp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {
    uint32_t ack_seq = ch.ack.seq;
    uint8_t cnp = (ch.ack.flags >> qbbHeader::FLAG_CNP) & 1;
    bool new_batch = false;

    // update alpha
    qp->dctcp.m_ecnCnt += (cnp > 0);
    if (ack_seq > qp->dctcp.m_lastUpdateSeq) {  // if full RTT feedback is ready, do alpha update
#if PRINT_LOG
        printf("%lu %s %08x %08x %u %u [%u,%u,%u] %.3lf->", Simulator::Now().GetTimeStep(), "alpha",
               qp->sip.Get(), qp->dip.Get(), qp->sport, qp->dport, qp->dctcp.m_lastUpdateSeq,
               ch.ack.seq, qp->snd_nxt, qp->dctcp.m_alpha);
#endif
        new_batch = true;
        if (qp->dctcp.m_lastUpdateSeq == 0) {  // first RTT
            qp->dctcp.m_lastUpdateSeq = qp->snd_nxt;
            qp->dctcp.m_batchSizeOfAlpha = qp->snd_nxt / m_mtu + 1;
        } else {
            double frac = std::min(1.0, double(qp->dctcp.m_ecnCnt) / qp->dctcp.m_batchSizeOfAlpha);
            qp->dctcp.m_alpha = (1 - m_g) * qp->dctcp.m_alpha + m_g * frac;
            qp->dctcp.m_lastUpdateSeq = qp->snd_nxt;
            qp->dctcp.m_ecnCnt = 0;
            qp->dctcp.m_batchSizeOfAlpha = (qp->snd_nxt - ack_seq) / m_mtu + 1;
#if PRINT_LOG
            printf("%.3lf F:%.3lf", qp->dctcp.m_alpha, frac);
#endif
        }
#if PRINT_LOG
        printf("\n");
#endif
    }

    // check cwr exit
    if (qp->dctcp.m_caState == 1) {
        if (ack_seq > qp->dctcp.m_highSeq) qp->dctcp.m_caState = 0;
    }

    // check if need to reduce rate: ECN and not in CWR
    if (cnp && qp->dctcp.m_caState == 0) {
#if PRINT_LOG
        printf("%lu %s %08x %08x %u %u %.3lf->", Simulator::Now().GetTimeStep(), "rate",
               qp->sip.Get(), qp->dip.Get(), qp->sport, qp->dport, qp->m_rate.GetBitRate() * 1e-9);
#endif
        qp->m_rate = std::max(m_minRate, qp->m_rate * (1 - qp->dctcp.m_alpha / 2));
#if PRINT_LOG
        printf("%.3lf\n", qp->m_rate.GetBitRate() * 1e-9);
#endif
        qp->dctcp.m_caState = 1;
        qp->dctcp.m_highSeq = qp->snd_nxt;
    }

    // additive inc
    if (qp->dctcp.m_caState == 0 && new_batch)
        qp->m_rate = std::min(qp->m_max_rate, qp->m_rate + m_dctcp_rai);
}

/****************************************************************
 * Per-Lane DCQCN Implementation (Mode 5)
 ****************************************************************/

/**
 * @brief Wakes up the next QP in a lane's waiting queue
 *
 * Called when the current running QP completes. If there are waiting QPs,
 * the first one in the queue is removed and set as the running QP.
 *
 * @param laneState The lane state
 */
void RdmaHw::WakeupNextQpInLane(Ptr<LaneDcqcnState> laneState) {
    if (!laneState->m_waitingQueue.empty()) {
        // Get the next QP from the waiting queue
        Ptr<RdmaQueuePair> nextQp = laneState->m_waitingQueue.front();
        laneState->m_waitingQueue.pop_front();

        if (!nextQp) {
            laneState->m_runningQp = nullptr;
            return;
        }
        // Set it as the running QP
        laneState->m_runningQp = nextQp;
        nextQp->startTime = Simulator::Now();

        // Notify the NIC to start sending packets for this QP
        uint32_t nic_idx = GetNicIdxOfQp(nextQp);
        m_nic[nic_idx].dev->NewQp(nextQp);
    }
}

void RdmaHw::cnp_received_mlx_Lane(Ptr<RdmaQueuePair> q) {
    if (!q) return;

    Ptr<LaneDcqcnState> laneState = q->m_laneDcqcnState;
    if (!laneState) return;

    laneState->m_alpha_cnp_arrived = true;
    laneState->m_decrease_cnp_arrived = true;
    if (laneState->m_first_cnp) {
        laneState->m_alpha = 1;
        laneState->m_alpha_cnp_arrived = false;
        ScheduleUpdateAlphaMlx_Lane(laneState);
        ScheduleDecreaseRateMlx_Lane(laneState, 1);
        DataRate newRate = m_rateOnFirstCNP * laneState->m_rate;
        laneState->m_targetRate = newRate;
        laneState->m_rate = newRate;
        laneState->m_first_cnp = false;
    }
}

void RdmaHw::UpdateAlphaMlx_Lane(Ptr<LaneDcqcnState> laneState) {
    if (laneState->m_alpha_cnp_arrived) {
        laneState->m_alpha = (1 - m_g) * laneState->m_alpha + m_g;
    } else {
        laneState->m_alpha = (1 - m_g) * laneState->m_alpha;
    }
    laneState->m_alpha_cnp_arrived = false;
    ScheduleUpdateAlphaMlx_Lane(laneState);
}

void RdmaHw::ScheduleUpdateAlphaMlx_Lane(Ptr<LaneDcqcnState> laneState) {
    laneState->m_eventUpdateAlpha = Simulator::Schedule(MicroSeconds(m_alpha_resume_interval),
                                                        &RdmaHw::UpdateAlphaMlx_Lane, this, laneState);
}

void RdmaHw::CheckRateDecreaseMlx_Lane(Ptr<LaneDcqcnState> laneState) {
    ScheduleDecreaseRateMlx_Lane(laneState, 0);
    if (laneState->m_decrease_cnp_arrived) {
        bool clamp = !m_EcnClampTgtRate ? (laneState->m_rpTimeStage != 0) : true;
        if (clamp) {
            laneState->m_targetRate = laneState->m_rate;
        }
        laneState->m_rate = std::max(m_minRate, laneState->m_rate * (1 - laneState->m_alpha / 2));

        laneState->m_rpTimeStage = 0;
        laneState->m_decrease_cnp_arrived = false;
        Simulator::Cancel(laneState->m_rpTimer);
        laneState->m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset),
                                                   &RdmaHw::RateIncEventTimerMlx_Lane, this, laneState);
    }
}

void RdmaHw::ScheduleDecreaseRateMlx_Lane(Ptr<LaneDcqcnState> laneState, uint32_t delta) {
    laneState->m_eventDecreaseRate =
        Simulator::Schedule(MicroSeconds(m_rateDecreaseInterval) + NanoSeconds(delta),
                            &RdmaHw::CheckRateDecreaseMlx_Lane, this, laneState);
}

void RdmaHw::RateIncEventTimerMlx_Lane(Ptr<LaneDcqcnState> laneState) {
    laneState->m_rpTimer =
        Simulator::Schedule(MicroSeconds(m_rpgTimeReset), &RdmaHw::RateIncEventTimerMlx_Lane, this, laneState);
    RateIncEventMlx_Lane(laneState);
    laneState->m_rpTimeStage++;
}

void RdmaHw::RateIncEventMlx_Lane(Ptr<LaneDcqcnState> laneState) {
    if (laneState->m_rpTimeStage < m_rpgThreshold) {
        FastRecoveryMlx_Lane(laneState);
    } else if (laneState->m_rpTimeStage == m_rpgThreshold) {
        ActiveIncreaseMlx_Lane(laneState);
    } else {
        HyperIncreaseMlx_Lane(laneState);
    }
}

void RdmaHw::FastRecoveryMlx_Lane(Ptr<LaneDcqcnState> laneState) {
    laneState->m_rate = (laneState->m_rate / 2) + (laneState->m_targetRate / 2);
}

void RdmaHw::ActiveIncreaseMlx_Lane(Ptr<LaneDcqcnState> laneState) {
    // Use the running QP to get NIC device
    if (!laneState->m_runningQp) return;
    Ptr<RdmaQueuePair> q = laneState->m_runningQp;
    uint32_t nic_idx = GetNicIdxOfQp(q);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    laneState->m_targetRate += m_rai;
    if (laneState->m_targetRate > dev->GetDataRate()) laneState->m_targetRate = dev->GetDataRate();
    laneState->m_rate = (laneState->m_rate / 2) + (laneState->m_targetRate / 2);
}

void RdmaHw::HyperIncreaseMlx_Lane(Ptr<LaneDcqcnState> laneState) {
    // Use the running QP to get NIC device
    if (!laneState->m_runningQp) return;
    Ptr<RdmaQueuePair> q = laneState->m_runningQp;
    uint32_t nic_idx = GetNicIdxOfQp(q);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    laneState->m_targetRate += m_rhai;
    if (laneState->m_targetRate > dev->GetDataRate()) laneState->m_targetRate = dev->GetDataRate();
    laneState->m_rate = (laneState->m_rate / 2) + (laneState->m_targetRate / 2);
}

}  // namespace ns3
