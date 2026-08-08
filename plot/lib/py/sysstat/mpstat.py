''' Parsing the mpstat outputs
'''
import json
from pprint import pprint
import copy
import pandas as pd


class MpstatJson(object):
    ''' Read and process the mpstat output

    Attributes:
        json_data: A dictionary contains json data
        log_date: A datetime.Date object representing the date of this log
    '''
    def __init__(self, fname):
        self.json_fname = fname
        with open(fname) as fp:
            self.json_data = json.load(fp)
            self.json_data = self.json_data['sysstat']['hosts'][0]
        self.read_meta()

    def read_meta(self):
        ''' Read the meta data from the mpstat log
        '''
        self.log_date = pd.to_datetime(self.json_data['date']).date()
        self.n_cpus = self.json_data['number-of-cpus']
        self.stats = self.json_data['statistics']

    def read_stat(self, stat_type, cpu_id=None):
        ''' Read the statistics from the mpstat log

        Args:
            stat_type:
                A string representing the type of statistics:
                    'cpu-load': cpu load
                    'sum-interrupts': rate of total interrupts (intr/s)
                    'individual-interrupts': rate of irqs (intr/s)
                    'soft-interrupts': rate of soft irqs (intr/s)
            cpu_id:
                A string representing the CPU ID.
                If cpu_id == "all", read the overall statistics of all CPUs.

        Returns:
            A pandas.DataFrame containing the statistics of all data
        '''
        records = []
        for intvl_item in self.stats:
            timestamp = pd.to_datetime(intvl_item['timestamp'])
            timestamp = pd.Timestamp.combine(self.log_date, timestamp.time())
            for cpu_item in intvl_item[stat_type]:
                cpu_item = copy.deepcopy(cpu_item)
                cpu_item['timestamp'] = timestamp
                # for individual interrupt stats, the values are
                # inside cpu_item['intr']
                if 'intr' in cpu_item:
                    total = 0
                    for int_item in cpu_item['intr']:
                        cpu_item[int_item['name']] = int_item['value']
                        total += int_item['value']
                    del cpu_item['intr']
                    cpu_item['total'] = total
                records.append(cpu_item)
        df = pd.DataFrame(records)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        # Make statistics of overall CPU overhead by
        # adding per-cpu staticstics up
        if 'all' not in df['cpu'].values:
            grouped = df.groupby('cpu')
            df_all = None
            for cid, df_cpu in grouped:
                df_cpu = df_cpu.set_index('timestamp')
                if df_all is None:
                    df_all = df_cpu
                else:
                    df_all = df_all.add(df_cpu)
            df_all['cpu'] = 'all'
            # Change the 'timestamp' index to a column
            df_all.reset_index(inplace=True)
            df = df.append(df_all)
            df.sort_values(by=['timestamp', 'cpu'], inplace=True)
            df.reset_index(inplace=True, drop=True)
        if cpu_id is not None:
            return df.groupby('cpu').get_group(str(cpu_id))
        else:
            return df

    def get_mean_cpu_load(self, cpu_id='all'):
        ''' Get mean load of a cpu from mpstat logs

        Args:
            cpu_id: id of cpu

        Returns:
            A floating number representing the mean cpu load
        '''
        df = self.read_stat('cpu-load')
        df['all'] = 100 - df['idle']
        mean_load = df.groupby('cpu').get_group(str(cpu_id))['all'].mean()
        return mean_load / 100.0

    def get_mean_sirq_rate(self, cpu_id='all'):
        ''' Get mean rate of software interrupt from mpstat logs

        Args:
            cpu_id: id of cpu

        Returns:
            A floating number representing the mean sirq rate
        '''
        df = self.read_stat('soft-interrupts')
        mean_rate = df.groupby('cpu').get_group(str(cpu_id))['total'].mean()
        return mean_rate
