from bfrt_helper.normal_controller import NormalController
import math

class NexthopController(NormalController):
  def __init__(self, target, gc, bfrt_info):
    super(NexthopController, self).__init__(target, gc)
    
    self.get_nexthop_id_table = bfrt_info.table_get('pipe.SwitchIngress.get_nexthop_id')
    
    self.nexthop_sel_max_group_size = 32
    self.nexthop_sel_group_id_list = []
    self.tables = [
      bfrt_info.table_get('pipe.SwitchIngress.get_nexthop_id'),
      bfrt_info.table_get('pipe.SwitchIngress.nexthop'),
      bfrt_info.table_get('pipe.SwitchIngress.lag_ecmp_sel'),
      bfrt_info.table_get('pipe.SwitchIngress.lag_ecmp'),
    ]
    self.nexthop_ap = bfrt_info.table_get('pipe.SwitchIngress.lag_ecmp')
    self.nexthop_sel = bfrt_info.table_get('pipe.SwitchIngress.lag_ecmp_sel')
    self.nexthop_table = bfrt_info.table_get('pipe.SwitchIngress.nexthop')
    
    # get_nexthop_id annotation
    self.get_nexthop_id_table.info.key_field_annotation_add('hdr.ipv4.dst_addr', 'ipv4')
    self._clear()
    
    
  def __add_write_nexthop_id_entry(self, dst_addr, nexthop_id):
    self.get_nexthop_id_table.entry_add(self.target, [
        self.get_nexthop_id_table.make_key([
            self.gc.KeyTuple('hdr.ipv4.dst_addr', dst_addr)
        ])
    ], [
        self.get_nexthop_id_table.make_data([self.gc.DataTuple('nexthop_id', nexthop_id)], 'SwitchIngress.write_nexthop_id')
    ])
    
  def __add_nexthop_table_entry(self, nexthop_id, group_id):
    self.nexthop_table.entry_add(self.target, [
        self.nexthop_table.make_key([
            self.gc.KeyTuple('ig_md.nexthop_id', nexthop_id),
        ])
    ], [
        self.nexthop_table.make_data([
            self.gc.DataTuple('$SELECTOR_GROUP_ID', group_id)
        ])
    ])
    
  def __add_nexthop_ap_entry(self, member_id, port):
    self.nexthop_ap.entry_add(self.target, [
        self.nexthop_ap.make_key([
          self.gc.KeyTuple('$ACTION_MEMBER_ID', member_id)
        ])
    ], [
        self.nexthop_ap.make_data([self.gc.DataTuple('port', port)], 'SwitchIngress.set_port')
    ])
    
  def __add_nexthop_sel_entry(self, group_id, member_id_list, member_status):
    self.nexthop_sel.entry_add(self.target, [
          self.nexthop_sel.make_key([
              self.gc.KeyTuple('$SELECTOR_GROUP_ID', group_id)
          ])
    ], [
          self.nexthop_sel.make_data([
              self.gc.DataTuple('$MAX_GROUP_SIZE', self.nexthop_sel_max_group_size),
              self.gc.DataTuple('$ACTION_MEMBER_ID', int_arr_val=member_id_list),
              self.gc.DataTuple('$ACTION_MEMBER_STATUS', bool_arr_val=member_status)
          ])
    ])
  
  def add_write_nexthop_id_entries(self, dst_addr_list, nexthop_id):
    for dst_addr in dst_addr_list:
      self.__add_write_nexthop_id_entry(dst_addr, nexthop_id)
      
  def add_nexthop_table_entries(self, nexthop_id, egress_port_list):
    # add entries into nexthop action profile, egress port -> member id
    member_id_list = []
    member_status = []
    for egress_port in egress_port_list:
      self.__add_nexthop_ap_entry(egress_port, egress_port)
      member_id_list.append(egress_port)
      member_status.append(True)
    # add members into nexthop action selector per group, nexthop id -> group id
    self.nexthop_sel_group_id_list.append(nexthop_id)
    self.__add_nexthop_sel_entry(nexthop_id, member_id_list, member_status)
    # add nexthop table
    self.__add_nexthop_table_entry(nexthop_id, nexthop_id)
    
class DCQCNController(NormalController):
  QDEPTH_RANGE_MAX = 2**19
  def __init__(self, target, gc, bfrt_info):
    super(DCQCNController, self).__init__(target, gc)
    
    self.tables = [
      bfrt_info.table_get('pipe.SwitchEgress.dcqcn_get_ecn_probability'),
      bfrt_info.table_get('pipe.SwitchEgress.dcqcn_compare_probability')
    ]
    self.dcqcn_get_ecn_probability_table = self.tables[0]
    self.dcqcn_compare_probability_table = self.tables[1]
    self._clear()
    
  def __add_dcqcn_get_ecn_probability_table_entry(self, deq_qdepth_start, deq_qdepth_end, value):
    self.dcqcn_get_ecn_probability_table.entry_add(self.target, [
        self.dcqcn_get_ecn_probability_table.make_key([
            self.gc.KeyTuple('eg_intr_md.deq_qdepth',
                              low=deq_qdepth_start,
                              high=deq_qdepth_end)
        ])
    ], [
        self.dcqcn_get_ecn_probability_table.make_data([self.gc.DataTuple('value', value)], 'SwitchEgress.dcqcn_mark_probability')
    ])
    
  def __add_dcqcn_compare_probability_table_entry(self, prob_output, random_number):
    self.dcqcn_compare_probability_table.entry_add(self.target, [
        self.dcqcn_compare_probability_table.make_key([
            self.gc.KeyTuple('eg_md.dcqcn_prob_output', prob_output),
            self.gc.KeyTuple('eg_md.dcqcn_random_number', random_number)
        ])
    ], [
        self.dcqcn_compare_probability_table.make_data([], 'SwitchEgress.dcqcn_check_ecn_marking')
    ])
    
  def add_entries(self, dcqcn_k_min, dcqcn_k_max, dcqcn_p_max, seed_range_max):
    seed_k_max = math.ceil(dcqcn_p_max * seed_range_max)
    qdepth_stepsize = math.floor((dcqcn_k_max - dcqcn_k_min) / seed_k_max)
    last_range = dcqcn_k_min
    
    # probability table
    # q_depth < k_min
    self.__add_dcqcn_get_ecn_probability_table_entry(deq_qdepth_start=0, deq_qdepth_end=dcqcn_k_min-1, value=0)
    
    # k_min < q_depth < k_max
    for i in range(1, seed_k_max):
      self.__add_dcqcn_get_ecn_probability_table_entry(deq_qdepth_start=last_range, deq_qdepth_end=last_range+qdepth_stepsize-1, value=i)
      last_range += qdepth_stepsize
    
    # q_depth > k_max
    self.__add_dcqcn_get_ecn_probability_table_entry(deq_qdepth_start=last_range, deq_qdepth_end=self.QDEPTH_RANGE_MAX-1, value=seed_range_max - 1)

    # comparison table
    # less than 100%
    for prob_output in range(1, seed_k_max): 
        for random_number in range(seed_range_max): # 0 ~ 255
            if random_number < prob_output:
              self.__add_dcqcn_compare_probability_table_entry(prob_output=prob_output, random_number=random_number)
              
    # 100% ECN Marking
    for random_number in range(seed_range_max):
      prob_output = seed_range_max - 1
      self.__add_dcqcn_compare_probability_table_entry(prob_output=prob_output, random_number=random_number)