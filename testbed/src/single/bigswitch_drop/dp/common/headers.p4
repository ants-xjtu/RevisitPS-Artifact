/*******************************************************************************
 *  Copyright (C) 2024 Intel Corporation
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *  http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing,
 *  software distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions
 *  and limitations under the License.
 *
 *
 *  SPDX-License-Identifier: Apache-2.0
 ******************************************************************************/

#ifndef _HEADERS_
#define _HEADERS_

#include <core.p4>
#if __TARGET_TOFINO__ == 3
#include <t3na.p4>
#elif __TARGET_TOFINO__ == 2
#include <t2na.p4>
#else
#include <tna.p4>
#endif

typedef bit<48> mac_addr_t;
typedef bit<32> ipv4_addr_t;
typedef bit<128> ipv6_addr_t;
typedef bit<12> vlan_id_t;

typedef bit<16> ether_type_t;
const ether_type_t ETHERTYPE_IPV4 = 16w0x0800;
const ether_type_t ETHERTYPE_ARP = 16w0x0806;
const ether_type_t ETHERTYPE_IPV6 = 16w0x86dd;
const ether_type_t ETHERTYPE_VLAN = 16w0x8100;

typedef bit<8> ip_protocol_t;
const ip_protocol_t IP_PROTOCOLS_ICMP = 1;
const ip_protocol_t IP_PROTOCOLS_TCP = 6;
const ip_protocol_t IP_PROTOCOLS_UDP = 17;

header ethernet_h {
    mac_addr_t dst_addr;
    mac_addr_t src_addr;
    bit<16> ether_type;
}

header vlan_tag_h {
    bit<3> pcp;
    bit<1> cfi;
    vlan_id_t vid;
    bit<16> ether_type;
}

header mpls_h {
    bit<20> label;
    bit<3> exp;
    bit<1> bos;
    bit<8> ttl;
}

header ipv4_h {
    bit<4> version;
    bit<4> ihl;
    bit<8> diffserv;
    bit<16> total_len;
    bit<16> identification;
    bit<3> flags;
    bit<13> frag_offset;
    bit<8> ttl;
    bit<8> protocol;
    bit<16> hdr_checksum;
    ipv4_addr_t src_addr;
    ipv4_addr_t dst_addr;
}

header ipv6_h {
    bit<4> version;
    bit<8> traffic_class;
    bit<20> flow_label;
    bit<16> payload_len;
    bit<8> next_hdr;
    bit<8> hop_limit;
    ipv6_addr_t src_addr;
    ipv6_addr_t dst_addr;
}

header tcp_h {
    bit<16> src_port;
    bit<16> dst_port;
    bit<32> seq_no;
    bit<32> ack_no;
    bit<4> data_offset;
    bit<4> res;
    bit<8> flags;
    bit<16> window;
    bit<16> checksum;
    bit<16> urgent_ptr;
}

header udp_h {
    bit<16> src_port;
    bit<16> dst_port;
    bit<16> hdr_length;
    bit<16> checksum;
}

header icmp_h {
    bit<8> type_;
    bit<8> code;
    bit<16> hdr_checksum;
}

// Address Resolution Protocol -- RFC 6747
header arp_h {
    bit<16> hw_type;
    bit<16> proto_type;
    bit<8> hw_addr_len;
    bit<8> proto_addr_len;
    bit<16> opcode;
    // ...
}

// Segment Routing Extension (SRH) -- IETFv7
header ipv6_srh_h {
    bit<8> next_hdr;
    bit<8> hdr_ext_len;
    bit<8> routing_type;
    bit<8> seg_left;
    bit<8> last_entry;
    bit<8> flags;
    bit<16> tag;
}

// VXLAN -- RFC 7348
header vxlan_h {
    bit<8> flags;
    bit<24> reserved;
    bit<24> vni;
    bit<8> reserved2;
}

// Generic Routing Encapsulation (GRE) -- RFC 1701
header gre_h {
    bit<1> C;
    bit<1> R;
    bit<1> K;
    bit<1> S;
    bit<1> s;
    bit<3> recurse;
    bit<5> flags;
    bit<3> version;
    bit<16> proto;
}

// UDP-specific types;
typedef bit<16> udp_port_t;

const udp_port_t UDP_PORT_ROCEV2        =   4791;

// IB/RoCE-specific types:
typedef bit<128> ib_gid_t;
typedef bit<24> sequence_number_t;
typedef bit<24> queue_pair_t;
typedef bit<32> rkey_t;
typedef bit<64> addr_t;

// UC opcodes
enum bit<8> ib_opcode_t {
    RC_SEND_FIRST = 8w0b00000000,
    RC_SEND_MIDDLE = 8w0b00000001,
    RC_SEND_LAST = 8w0b00000010,
    RC_SEND_LAST_IMMEDIATE = 8w0b00000011,
    RC_SEND_ONLY = 8w0b000100,
    RC_SEND_ONLY_IMMEDIATE = 8w0b00000101,
    RC_RDMA_WRITE_FIRST = 8w0b00000110,
    RC_RDMA_WRITE_MIDDLE = 8w0b00000111,
    RC_RDMA_WRITE_LAST = 8w0b00001000,
    RC_RDMA_WRITE_LAST_IMMEDIATE = 8w0b00001001,
    RC_RDMA_WRITE_ONLY = 8w0b00001010,
    RC_RDMA_WRITE_ONLY_IMMEDIATE = 8w0b00001011,
    RC_RDMA_ACK = 8w0b00010001
}

// InfiniBand-RoCE Base Transport Header
header ib_bth_h {
    ib_opcode_t       opcode;
    bit<1>            se;
    bit<1>            migration_req;
    bit<2>            pad_count;
    bit<4>            transport_version;
    bit<16>           partition_key;
    bit<1>            f_res1;
    bit<1>            b_res1;
    bit<6>            reserved;
    queue_pair_t      dst_qp;
    bit<1>            ack_req;
    bit<7>            reserved2;
    sequence_number_t psn;
}

@pa_container_size("ingress", "hdr.ib_bth.psn", 32)

// InfiniBand-RoCE RDMA Extended Transport Header
header ib_reth_h {
    bit<64> addr;
    bit<32> r_key;
    bit<32> len;
}

// InfiniBand-RoCE Immediate Header
header ib_immediate_h {
    bit<32> immediate;
}

// InfiniBand-RoCE ICRC Header
header ib_icrc_h {
    bit<32> icrc;
}

header ib_aeth_h {
    bit<1> reserved;
    bit<2> opcode;      // (0: ACK, 3: NACK)
    bit<5> error_code;  // (PSN SEQ ERROR)
    bit<8> msg_seq_number;
}

header recir_h {
    bit<8> flag;
    bit<8> cnt;
}

struct header_t {
    ethernet_h ethernet;
    vlan_tag_h vlan_tag;
    arp_h arp;
    ipv4_h ipv4;
    ipv6_h ipv6;
    tcp_h tcp;
    udp_h udp;
    ib_bth_h       ib_bth;
    ib_reth_h      ib_reth;
    ib_immediate_h ib_immediate;
    ib_aeth_h      ib_aeth;
}

struct empty_header_t {}

struct empty_metadata_t {}

#endif /* _HEADERS_ */
