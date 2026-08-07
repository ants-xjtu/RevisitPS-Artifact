from bfrt_helper.normal_controller import NormalController

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