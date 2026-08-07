from bfrt_helper.normal_controller import NormalController

class CheckController(NormalController):
  def __init__(self, target, gc, bfrt_info):
    super().__init__(target, gc)
    self.port_cfg_table = bfrt_info.table_get('tf1.tm.port.cfg')
    
  def get_pg_id_and_pg_queue(self, dev_port, queue_id):
    entry = self.port_cfg_table.entry_get(self.target, [
        self.port_cfg_table.make_key([self.gc.KeyTuple('dev_port', dev_port)])
    ], {'print_ents': False})
    info = next(entry)[0].to_dict()
    pg_id = info['pg_id']
    pg_queue = info['egress_qid_queues'][queue_id]
    return (pg_id, pg_queue)