from bfrt_helper.normal_controller import NormalController
import math

class ForwardController(NormalController):
  def __init__(self, target, gc, bfrt_info):
    super(ForwardController, self).__init__(target, gc)
    
    self.tables = [
      bfrt_info.table_get('pipe.SwitchIngress.forward')
    ]
    self.table = self.tables[0]
    
    self._clear()
    
  def add_entry(self, src_dev_port, dst_dev_port):
    self.table.entry_add(self.target, [
        self.table.make_key(
            [self.gc.KeyTuple('ig_intr_md.ingress_port', src_dev_port)]
        )
    ], [
        self.table.make_data(
            [self.gc.DataTuple('egress_port', dst_dev_port)],
            'SwitchIngress.set_port'
        )
    ])
  
  def add_entries(self, entry_list):
    for (src_dev_port, dst_dev_port) in entry_list:
      self.add_entry(src_dev_port=src_dev_port, dst_dev_port=dst_dev_port)
      
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