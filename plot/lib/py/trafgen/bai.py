import pandas as pd


def get_qct_fname(prefix):
    return prefix + '_reqs.txt'


def parse_query_qct(fname):
    df = pd.read_csv(
        fname,
        names=('req_size', 'qct_us', 'dscp', 'rate', 'goodput_mbps', 'fanout', ),
        delim_whitespace=True,
    )
    df['qct'] = df['qct_us']/1e6
    return df


def parse_back_fct(fname):
    df = pd.read_csv(
        fname,
        names=('flow_size', 'fct_us', 'dscp', 'rate', 'goodput_mbps'),
        delim_whitespace=True,
    )
    df['fct'] = df['fct_us']/1e6
    return df

