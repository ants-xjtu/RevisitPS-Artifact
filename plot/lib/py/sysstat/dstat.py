''' Parsing the dstat outputs
'''
import json
import pandas as pd
import copy


def read(fname):
    df = pd.read_csv(fname, skiprows=5)
    df['timestamp'] = pd.to_datetime(df['epoch'], unit='s')
    df['total'] = 100 - df['idl']
    return df
