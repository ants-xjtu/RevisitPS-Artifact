#include <core.p4>
#if __TARGET_TOFINO__ == 2
#include <t2na.p4>
#else
#include <tna.p4>
#endif
#include "common/headers.p4"
#include "common/util.p4"

#define MCAST_GRP_ID (1)

struct ig_metadata_t {
    bit<12> nexthop_id;
    bit<8> switch_id;
}

struct eg_metadata_t {
    bit<1> exceeded_ecn_marking_threshold;
    bit<8> dcqcn_random_number;
    bit<8> dcqcn_prob_output;
}

parser SwitchIngressParser(
        packet_in pkt,
        out header_t hdr,
        out ig_metadata_t ig_md,
        out ingress_intrinsic_metadata_t ig_intr_md) {
    TofinoIngressParser() tofino_parser;
    
    state start {
      tofino_parser.apply(pkt, ig_intr_md);
      ig_md.nexthop_id = 12w0xFFF;
      ig_md.switch_id = 8w0xFF;
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
            default: accept;
        }
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
        
        pkt.emit(hdr.ethernet);
        pkt.emit(hdr.ipv4);
        pkt.emit(hdr.arp);
        pkt.emit(hdr.tcp);
        pkt.emit(hdr.udp);
    }
}

control SwitchIngress(
        inout header_t hdr,
        inout ig_metadata_t ig_md,
        in ingress_intrinsic_metadata_t ig_intr_md,
        in ingress_intrinsic_metadata_from_parser_t ig_intr_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md) {
    action nop(){}
    action drop(bit<3> drop_bits) {
        ig_intr_dprsr_md.drop_ctl = drop_bits;
    }

    action set_port(PortId_t port) {
        ig_intr_tm_md.ucast_egress_port = port;
    }
    action write_switch_id(bit<8> switch_id) { 
      ig_md.switch_id = switch_id; 
    }
    table get_switch_id {
        key = {
            ig_intr_md.ingress_port: exact;
        }
        actions = {
            write_switch_id;
            @defaultonly nop;
        }
        const default_action = nop();
        size = 1024;
    }

    action write_nexthop_id(bit<12> nexthop_id) { 
        ig_md.nexthop_id = nexthop_id;
    }
    table get_nexthop_id {
        key = { 
            ig_md.switch_id: 	exact;
            hdr.ipv4.dst_addr:  exact;
        }
        actions = { write_nexthop_id; @defaultonly nop; }
        const default_action = nop();
        size = 2048;
    }

    Hash<bit<16>> (HashAlgorithm_t.CRC16) 	lag_ecmp_hash;
    ActionProfile(size = 2048) 		lag_ecmp;
    ActionSelector(
        action_profile = lag_ecmp /* profile */,
        hash           = lag_ecmp_hash /* hash */,
        mode           = SelectorMode_t.FAIR /* fair */,
        max_group_size = 32,
        num_groups     = 256) lag_ecmp_sel /* selector */;

    @selector_enable_scramble(1) /* enable non-linear hash */
    table nexthop {
        key = {
            ig_md.nexthop_id : 			exact;
            hdr.ipv4.src_addr : 		selector;
            hdr.ipv4.dst_addr :			selector;
            hdr.udp.src_port : 		    selector;
        }
        actions = { set_port; drop; }
        const default_action = drop(0x1);
        size = 2048;
        implementation = lag_ecmp_sel;
    }
    apply {
      if (hdr.ethernet.ether_type == ETHERTYPE_ARP) {
        ig_intr_tm_md.mcast_grp_a = MCAST_GRP_ID;
      } else {
        if (hdr.ethernet.ether_type == ETHERTYPE_IPV4) {
            get_switch_id.apply();
        // if (hdr.ipv4.isValid()) {
          get_nexthop_id.apply();
          nexthop.apply();
        // } else {
        //   drop(1);
        // }
        } else {
            drop(1);
        }
        
      }
      
    }
}

parser SwitchEgressParser(
        packet_in pkt,
        out header_t hdr,
        out eg_metadata_t eg_md,
        out egress_intrinsic_metadata_t eg_intr_md) {
    TofinoEgressParser() tofino_parser;
    
    state start {
      tofino_parser.apply(pkt, eg_intr_md);
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
            default: accept;
        }
    }
}

control SwitchEgressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in eg_metadata_t eg_md,
        in egress_intrinsic_metadata_for_deparser_t ig_intr_dprs_md) {
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
        
        pkt.emit(hdr.ethernet);
        pkt.emit(hdr.ipv4);
        pkt.emit(hdr.arp);
        pkt.emit(hdr.tcp);
        pkt.emit(hdr.udp);
    }
}

control SwitchEgress(
        inout header_t hdr,
        inout eg_metadata_t eg_md,
        in egress_intrinsic_metadata_t eg_intr_md,
        in egress_intrinsic_metadata_from_parser_t eg_intr_md_from_prsr,
        inout egress_intrinsic_metadata_for_deparser_t ig_intr_dprs_md,
        inout egress_intrinsic_metadata_for_output_port_t eg_intr_oport_md) {

    action nop() {}

    action dcqcn_mark_probability(bit<8> value) {
		eg_md.dcqcn_prob_output = value;
	}

    table dcqcn_get_ecn_probability {
		key = {
			eg_intr_md.deq_qdepth : range; // 19 bits
		}
		actions = {
			dcqcn_mark_probability;
		}
		const default_action = dcqcn_mark_probability(0); // default: no ecn mark
		size = 1024;
	}

    action dcqcn_check_ecn_marking() {
		eg_md.exceeded_ecn_marking_threshold = (bit<1>)1;
	}

    table dcqcn_compare_probability {
		key = {
			eg_md.dcqcn_prob_output : exact;
			eg_md.dcqcn_random_number : exact;
		}
		actions = {
			dcqcn_check_ecn_marking;
			@defaultonly nop;
		}
		const default_action = nop();
		size = 65536;
	}

    Random<bit<8>>() random;  // random seed for sampling
	action dcqcn_get_random_number(){
		eg_md.dcqcn_random_number = random.get();
	}

    action mark_ecn_ce_codepoint(){
		hdr.ipv4.diffserv[1:0] = 0b11;
	}

    apply {
        // default dcqcn
        if (hdr.ipv4.diffserv[1:0] == 0b01 || hdr.ipv4.diffserv[1:0] == 0b10) {
            dcqcn_get_ecn_probability.apply(); // get probability to ecn-mark
			dcqcn_get_random_number(); // get random number for sampling
			dcqcn_compare_probability.apply();
        }
        if (eg_md.exceeded_ecn_marking_threshold == 1){
			mark_ecn_ce_codepoint();
		}
    }
}

Pipeline(SwitchIngressParser(),
         SwitchIngress(),
         SwitchIngressDeparser(),
         SwitchEgressParser(),
         SwitchEgress(),
         SwitchEgressDeparser()
         ) pipe;

Switch(pipe) main;
