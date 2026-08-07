from .normal_controller import NormalController


class MirrorConfigController(NormalController):
  def __init__(self, target, gc, bfrt_info):
    super().__init__(target, gc)
    self.tables = [bfrt_info.table_get('$mirror.cfg')]
    self.mirror_cfg_table = self.tables[0]
    # self._clear()
  
  def add_normal_ucast_entry(self, sid, direction, port, valid, enable):
    try:
      self.mirror_cfg_table.entry_del(self.target,
                                  [self.mirror_cfg_table.make_key([self.gc.KeyTuple('$sid', sid)])]
                                   )
    except Exception as e:
      print(e)
    self.mirror_cfg_table.entry_add(self.target,
      [self.mirror_cfg_table.make_key([self.gc.KeyTuple('$sid', sid)])],
      [self.mirror_cfg_table.make_data([self.gc.DataTuple('$direction', str_val=direction),
                                   self.gc.DataTuple('$ucast_egress_port', port),
                                   self.gc.DataTuple('$ucast_egress_port_valid', bool_val=valid),
                                   self.gc.DataTuple('$session_enable', bool_val=enable)],
                                  '$normal')]
    )