#include <core.p4>
#include <tna.p4>
#include "common/headers.p4"
#include "common/util.p4"

struct eg_metadata_t {
    bit<1> exceeded_ecn_marking_threshold;
    bit<8> dcqcn_random_number;
    bit<8> dcqcn_prob_output;
}

parser SwitchIngressParser(
        packet_in pkt,
        out header_t hdr,
        out empty_metadata_t ig_md,
        out ingress_intrinsic_metadata_t ig_intr_md) {
    TofinoIngressParser() tofino_parser;
    
    state start {
      tofino_parser.apply(pkt, ig_intr_md);
      transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select (hdr.ethernet.ether_type) {
            ETHERTYPE_IPV4 : parse_ipv4;
            default : accept;
        }
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
        in empty_metadata_t ig_md,
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
        pkt.emit(hdr.tcp);
        pkt.emit(hdr.udp);
    }
}

control SwitchIngress(
        inout header_t hdr,
        inout empty_metadata_t ig_md,
        in ingress_intrinsic_metadata_t ig_intr_md,
        in ingress_intrinsic_metadata_from_parser_t ig_intr_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md) {

    action set_port(PortId_t egress_port) {
        ig_intr_tm_md.ucast_egress_port = egress_port;
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
            default : reject;
        }
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