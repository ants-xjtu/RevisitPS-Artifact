from .normal_controller import NormalController

class RegisterController(NormalController):
  def __init__(self, target, gc, bfrt_info, reg_name, reg_loc):
    super().__init__(target, gc)
    self.name = '{}.{}'.format(reg_loc, reg_name)
    self.table = bfrt_info.table_get(self.name)
    
  def read(self, reg_idx, pipe_id):
    resp = self.table.entry_get(self.target,
        [self.table.make_key([self.gc.KeyTuple('$REGISTER_INDEX', reg_idx)])],
        {'from_hw': True}
    )
    data, _ = next(resp)
    data_dict = data.to_dict()
    return data_dict['{}.f1'.format(self.name)][pipe_id]
    
  def write(self, reg_idx, value):
    self.table.entry_add(self.target,
          [self.table.make_key([self.gc.KeyTuple('$REGISTER_INDEX', reg_idx)])],
          [self.table.make_data(
                [self.gc.DataTuple('{}.f1'.format(self.name), value)])]
    )
    
  