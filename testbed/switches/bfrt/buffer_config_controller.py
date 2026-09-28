from .normal_controller import NormalController

class IngressBufferConfigController(NormalController):
  ICOS_TABLE = {
    0: 'icos_0',
    1: 'icos_1',
    2: 'icos_2',
    3: 'icos_3',
    4: 'icos_4',
    5: 'icos_5',
    6: 'icos_6',
    7: 'icos_7'
  }
  IG_POOL_TABLE = {
    0: 'IG_APP_POOL_0',
    1: 'IG_APP_POOL_1',
    2: 'IG_APP_POOL_2',
    3: 'IG_APP_POOL_3'
  }
  def __init__(self, target, gc, bfrt_info, arch):
    super().__init__(target, gc)
    self.tables = [
        bfrt_info.table_get('{}.tm.ppg.cfg'.format(arch)),
        bfrt_info.table_get('{}.tm.port.flowcontrol'.format(arch))
    ]
    self.ppg_cfg_table = self.tables[0]
    self.ppg_port_flowcontrol_table = self.tables[1]
    
  def add_ppg_cfg_table_entry(self, dev_port, ppg_id, icos=0, guaranteed_cells=0, pool_id=0, pool_max_cells=0, pfc_enable=False, pfc_skid_max_cells=0, dynamic_baf='50%'):
    self.ppg_cfg_table.entry_add(
        self.target,
        [self.ppg_cfg_table.make_key([self.gc.KeyTuple('ppg_id', ppg_id)])],
        [self.ppg_cfg_table.make_data([
            self.gc.DataTuple('dev_port', dev_port),
            self.gc.DataTuple(self.ICOS_TABLE[icos], bool_val=True),
            self.gc.DataTuple('guaranteed_cells', guaranteed_cells),
            self.gc.DataTuple('pfc_enable', bool_val=pfc_enable),
            self.gc.DataTuple('pfc_skid_max_cells', pfc_skid_max_cells),
            self.gc.DataTuple('pool_id', str_val=self.IG_POOL_TABLE[pool_id]),
            self.gc.DataTuple('pool_max_cells', pool_max_cells),
            self.gc.DataTuple('dynamic_baf', str_val=dynamic_baf)
        ], 'dev_port')]
    )
  
  def mod_ppg_cfg_table_entry(self, dev_port, ppg_id, icos=0, guaranteed_cells=0, pool_id=0, pool_max_cells=0, pfc_enable=False, pfc_skid_max_cells=0, dynamic_baf='DISABLE'):
    self.ppg_cfg_table.entry_mod(
        self.target,
        [self.ppg_cfg_table.make_key([self.gc.KeyTuple('ppg_id', ppg_id)])],
        [self.ppg_cfg_table.make_data([
            self.gc.DataTuple('dev_port', dev_port),
            self.gc.DataTuple(self.ICOS_TABLE[icos], bool_val=True),
            self.gc.DataTuple('guaranteed_cells', guaranteed_cells),
            self.gc.DataTuple('pfc_enable', bool_val=pfc_enable),
            self.gc.DataTuple('pfc_skid_max_cells', pfc_skid_max_cells),
            self.gc.DataTuple('pool_id', str_val=self.IG_POOL_TABLE[pool_id]),
            self.gc.DataTuple('pool_max_cells', pool_max_cells),
            self.gc.DataTuple('dynamic_baf', str_val=dynamic_baf)
        ], 'dev_port')]
    )
  
  def mod_port_flowcontrol_entry(self, dev_port, mode_rx, mode_tx):
    self.ppg_port_flowcontrol_table.entry_mod(
        self.target,
        [self.ppg_port_flowcontrol_table.make_key([self.gc.KeyTuple('dev_port', dev_port)])],
        [self.ppg_port_flowcontrol_table.make_data([
            self.gc.DataTuple('mode_rx', str_val=mode_rx),
            self.gc.DataTuple('mode_tx', str_val=mode_tx),
        ])]
    )
  
    
class EgressBufferConfigController(NormalController):
  EG_POOL_TABLE = {
    0: 'EG_APP_POOL_0',
    1: 'EG_APP_POOL_1',
    2: 'EG_APP_POOL_2',
    3: 'EG_APP_POOL_3'
  }
  def __init__(self, target, gc, bfrt_info, arch):
    super().__init__(target, gc)
    self.tables = [
        bfrt_info.table_get('{}.tm.pool.cfg'.format(arch)),
        bfrt_info.table_get('{}.tm.queue.buffer'.format(arch)),
        bfrt_info.table_get('{}.tm.queue.sched_cfg'.format(arch)),
        bfrt_info.table_get('{}.tm.queue.cfg'.format(arch)),
        bfrt_info.table_get('{}.tm.port.group'.format(arch))
    ]
    self.pool_cfg_table = self.tables[0]
    self.queue_buffer_table = self.tables[1]
    self.queue_sched_cfg_table = self.tables[2]
    self.queue_cfg_table = self.tables[3]
    self.port_group_table = self.tables[4]
    
  def mod_pool_cfg_table(self, pool, size_cells):
    self.pool_cfg_table.entry_mod(
        self.target,
        [self.pool_cfg_table.make_key([self.gc.KeyTuple('pool', self.EG_POOL_TABLE[pool])])],
        [self.pool_cfg_table.make_data([
            self.gc.DataTuple('size_cells', size_cells),
        ])]
    )
  
  def mod_queue_buffer_shared_pool_table(self, pg_id, pg_queue, guaranteed_cells, pool_id, pool_max_cells, dynamic_baf):
    self.queue_buffer_table.entry_mod(
        self.target,
        [self.queue_buffer_table.make_key([
            self.gc.KeyTuple('pg_id', pg_id),
            self.gc.KeyTuple('pg_queue', pg_queue)
        ])],
        [self.queue_buffer_table.make_data([
            self.gc.DataTuple('guaranteed_cells', guaranteed_cells),
            self.gc.DataTuple('pool_id', str_val=self.EG_POOL_TABLE[pool_id]),
            self.gc.DataTuple('pool_max_cells', pool_max_cells),
            self.gc.DataTuple('dynamic_baf', str_val=dynamic_baf)
        ], 'shared_pool')]
    )
    
  def mod_queue_sched_cfg_table(self, pg_id, pg_queue, min_priorty='LOW', min_rate_enable=False, dwrr_weight=0x03FF, max_priority='LOW', max_rate_enable=False, advanced_flow_control='CREDIT', scheduling_enable=True, pg_l1_node=0x00):
    self.queue_sched_cfg_table.entry_mod(
        self.target,
        [self.queue_sched_cfg_table.make_key([
            self.gc.KeyTuple('pg_id', pg_id),
            self.gc.KeyTuple('pg_queue', pg_queue)
        ])],
        [self.queue_sched_cfg_table.make_data([
            self.gc.DataTuple('min_priority', str_val=min_priorty),
            self.gc.DataTuple('min_rate_enable', bool_val=min_rate_enable),
            self.gc.DataTuple('dwrr_weight', dwrr_weight),
            self.gc.DataTuple('max_priority', str_val=max_priority),
            self.gc.DataTuple('max_rate_enable', bool_val=max_rate_enable),
            self.gc.DataTuple('scheduling_enable', bool_val=scheduling_enable),
        ])]
    )
    
  def mod_port_group_table_with_seq(self, pg_id, port_queue_count):
    self.port_group_table.entry_mod(
        self.target,
        [self.port_group_table.make_key([
            self.gc.KeyTuple('pg_id', pg_id),
        ])],
        [self.port_group_table.make_data([
            self.gc.DataTuple('port_queue_count', int_arr_val=port_queue_count),
        ], 'seq')]
    )