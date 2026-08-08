''' Parsing the sar outputs
'''
import pandas as pd

date_format = '%m/%d/%Y'
time_format = '%I:%M:%S %p'


class RawLog(object):
    ''' Read and process the raw log files for sysstat

    Attributes:
        fname: A string denoting log file name
        data: A dataframe contains data
        log_date: A datetime.Date object representing the date of this log
    '''
    def __init__(self, fname):
        self.fname = fname
        self.parse()

    def parse(self):
        with open(self.fname) as fp:
            metainfo = fp.readline()
            log_date = metainfo.split('\t')[1]
        self.log_date = pd.to_datetime(log_date)
        df = pd.read_csv(
            self.fname, header=1,
            delim_whitespace=True,
        )
        # Converse percentages to fractions
        # and Change the corresponding column names
        cols = []
        for col_name in df.columns:
            if col_name.lstrip()[0] == '%':
                df[col_name] /= 100.0
                cols.append(col_name.lstrip()[1:])
            else:
                cols.append(col_name)
        cols[0] = 'timestamp'
        df.columns = cols

        if df.iat[-1, 0] == 'Average:':
            avg = df.iloc[-1, :]
            df = df.iloc[:-1, :]
            newindex = []
            for index in avg.index:
                if index == 'PM' or index == 'AM':
                    continue
                newindex.append(index)
            avg = avg.dropna()
            avg.index = newindex
            self.average = avg

        df.timestamp = log_date + df.timestamp + df.iloc[:, 1]
        df.timestamp = pd.to_datetime(df.timestamp)
        self.data = df
