#include <core.p4>
#include <tna.p4>
#include "common/headers.p4"
#include "common/util.p4"

struct ig_metadata_t {
  bit<32> cnt;
  bit<1>  is_ack;
}

parser SwitchIngressParser(
        packet_in pkt,
        out header_t hdr,
        out ig_metadata_t ig_md,
        out ingress_intrinsic_metadata_t ig_intr_md) {
    TofinoIngressParser() tofino_parser;
    
    state start {
      tofino_parser.apply(pkt, ig_intr_md);
      ig_md.cnt = 0;
      ig_md.is_ack = 0;
      transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select (hdr.ethernet.ether_type) {
            ETHERTYPE_IPV4 : parse_ipv4;
            ETHERTYPE_ARP : parse_arp;
            default : reject;
        }
    }

    state parse_arp {
        pkt.extract(hdr.arp);
        transition accept;
    }

    state parse_ipv4 {
        pkt.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            IP_PROTOCOLS_TCP : parse_tcp;
            IP_PROTOCOLS_UDP : parse_udp;
            default : accept;
        }
    }
    state parse_tcp {
        pkt.extract(hdr.tcp);
        transition select(hdr.ipv4.total_len) {
            default : accept;
        }
    }
    state parse_udp {
        pkt.extract(hdr.udp);
        transition select(hdr.udp.dst_port) {
            UDP_PORT_ROCEV2 : parse_ib_bth;
            default: accept;
        }
    }

    state parse_ib_bth {
        pkt.extract(hdr.ib_bth);
        transition select(hdr.ib_bth.opcode) {
            // include only UC operations here
            ib_opcode_t.RC_SEND_FIRST                : accept;
            ib_opcode_t.RC_SEND_MIDDLE               : accept;
            ib_opcode_t.RC_SEND_LAST                 : accept;
            ib_opcode_t.RC_SEND_LAST_IMMEDIATE       : parse_ib_immediate;
            ib_opcode_t.RC_SEND_ONLY                 : accept;
            ib_opcode_t.RC_SEND_ONLY_IMMEDIATE       : parse_ib_immediate;
            ib_opcode_t.RC_RDMA_WRITE_FIRST          : parse_ib_reth;
            ib_opcode_t.RC_RDMA_WRITE_MIDDLE         : accept;
            ib_opcode_t.RC_RDMA_WRITE_LAST           : accept;
            ib_opcode_t.RC_RDMA_WRITE_LAST_IMMEDIATE : parse_ib_immediate;
            ib_opcode_t.RC_RDMA_WRITE_ONLY           : parse_ib_reth;
            ib_opcode_t.RC_RDMA_WRITE_ONLY_IMMEDIATE : parse_ib_reth_immediate;
            ib_opcode_t.RC_RDMA_ACK                  : parse_ib_aeth;
            default: accept;
        }
    }

    state parse_ib_immediate {
        pkt.extract(hdr.ib_immediate);
        transition accept;
    }

    state parse_ib_reth {
        pkt.extract(hdr.ib_reth);
        transition accept;
    }

    state parse_ib_reth_immediate {
        pkt.extract(hdr.ib_reth);
        pkt.extract(hdr.ib_immediate);
        transition accept;
    }

    state parse_ib_aeth {
        ig_md.is_ack = 1;
        pkt.extract(hdr.ib_aeth);
        transition accept;
    }
}

control SwitchIngressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in ig_metadata_t ig_md,
        in ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md) {
    Checksum() ipv4_checksum;
    apply {
        hdr.ipv4.hdr_checksum = ipv4_checksum.update({
              hdr.ipv4.version,
              hdr.ipv4.ihl,
              hdr.ipv4.diffserv,
              hdr.ipv4.total_len,
              hdr.ipv4.identification,
              hdr.ipv4.flags,
              hdr.ipv4.frag_offset,
              hdr.ipv4.ttl,
              hdr.ipv4.protocol,
              hdr.ipv4.src_addr,
              hdr.ipv4.dst_addr
          });

        pkt.emit(hdr);
    }
}

control SwitchIngress(
        inout header_t hdr,
        inout ig_metadata_t ig_md,
        in ingress_intrinsic_metadata_t ig_intr_md,
        in ingress_intrinsic_metadata_from_parser_t ig_intr_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md) {
    action drop(bit<3> drop_bits) {
        ig_intr_dprsr_md.drop_ctl = drop_bits;
    }

    RegisterParam<bit<32>>(1) test_asn;
    Register<bit<32>, _>(1) reg_cnt;
    RegisterAction<bit<32>, _, bit<32>>(reg_cnt) reg_cnt_add_action = {
        void apply(inout bit<32> value, out bit<32> rv) {
            if (value > 1000) {
                value = 0;
            } else {
                value = value +1;
            }
            rv = value;
        }
    };

    action add_cnt() {
        ig_md.cnt = reg_cnt_add_action.execute(0);
    }
    action set_port(PortId_t egress_port) {
        ig_intr_tm_md.ucast_egress_port = egress_port;
        add_cnt();
    }

    table forward {
        key = {
            ig_intr_md.ingress_port : exact;
        }
        actions = {
            set_port;
        }
        size = 16;
    }
    
    apply {
        forward.apply();
        if (hdr.ipv4.isValid()) {
            hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        }
        ig_intr_tm_md.bypass_egress = 1;

        if (ig_md.cnt == 1000 && ig_md.is_ack == 0) {
            drop(0x1);
        }
    }
}

Pipeline(SwitchIngressParser(),
         SwitchIngress(),
         SwitchIngressDeparser(),
         EmptyEgressParser(),
         EmptyEgress(),
         EmptyEgressDeparser()
         ) pipe;

Switch(pipe) main;