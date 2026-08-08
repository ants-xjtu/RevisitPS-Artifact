import os

import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd


def read_stats_with_cache(xmlfile, cachedir='.cache'):
    ''' Read xml files with cache speedup
    Reading and parsing xml files can be very slow.
    To speed up, this function stores the parsed data into a cache file
    so that the xml file does not needed to be parsed again.

    Args:
        xmlfile: the file name of ns-3 flow monitor logs (including path)
        cachedir: cache directory name (not including path)
            The cache directory is put into the same directory as the xml file

    Returns:
        XmlParser.stats_df
    '''
    cachedir = os.path.join(os.path.dirname(xmlfile), cachedir)
    if not os.path.exists(cachedir):
        os.mkdir(cachedir)
    cachefile = os.path.basename(xmlfile)
    cachefile = os.path.splitext(cachefile)[0]
    cachefile = '{}.csv'.format(cachefile)
    cachefile = os.path.join(cachedir, cachefile)
    if (not os.path.exists(cachefile) or
            os.path.getmtime(cachefile) < os.path.getmtime(xmlfile)):
        parser = XmlParser(xmlfile)
        df = parser.stats_df
        df['packetLossRate'] = df['lostPackets'] / df['txPackets']
        df.to_csv(cachefile, index=False)
    df = pd.read_csv(cachefile)
    return df


def xmltime2floatsec(strtime):
    ''' Converting a string format time in xml to a floating number in seconds
    In the flow monitor, the time format is like '+23232.232ns'.
    This function converts the string time with above format to
    a floating number in unit of seconds

    Args:
        strtime: A string representing time
    Returns:
        A floating number representing the time in seconds
    '''
    assert strtime[-2:] == 'ns'
    return float(strtime[:-2])/1e9


def get_fct_breakdown(flow_stats):
    ''' Get Statistics of FCT across different flow sizes

    Args:
        flow_stats: A DataFrame containing flow statistics data
            This is usually from XmlParser.stats_df

    Returns:
        A dictionary contains FCT breakdown
    '''
    df = flow_stats
    small_df = df[df.rxBytes <= (100 << 10)]
    median_df = df[
        (df.rxBytes > (100 << 10)) & (df.rxBytes <= (10 << 20))
    ]
    large_df = df[df.rxBytes > (10 << 20)]
    fct_breakdown = {
        'overall_avg': df['fct'].mean(),
        'small_avg': small_df['fct'].mean(),
        'small_tail': small_df['fct'].quantile(
            0.99, interpolation='lower',
        ),
        'median_avg': median_df['fct'].mean(),
        'large_avg': large_df['fct'].mean(),
    }
    return fct_breakdown


def get_stat_flowsize(flow_stats, stat_name, n_groups=20):
    ''' Get statistics across different flow sizes
    Args:
        flow_stats: A DataFrame containing flow statistics data
            This is usually from XmlParser.stats_df
        stat_name: Name of flow statistics (e.g., fct)
        n_groups: divide all stats into n_groups

    Returns:
        A DataFrame contains statistics vs. flow_size
    '''
    stats = []
    flow_stats = flow_stats.sort_values(by=['rxBytes'])
    length = len(flow_stats)
    step = 100/n_groups
    for i in np.arange(0, 100, step):
        sidx = int(i * length / 100)
        eidx = int((i + step) * length / 100)
        sub_stats = flow_stats.iloc[sidx:eidx]
        stats.append({
            'flowsize': sub_stats['rxBytes'].median(),
            'avg': sub_stats[stat_name].mean(),
            'median': sub_stats[stat_name].median(),
            '90th': sub_stats[stat_name].quantile(0.9, interpolation='lower'),
            '99th': sub_stats[stat_name].quantile(0.99, interpolation='lower'),
        })
    stats_df = pd.DataFrame(stats)

    def flowsize2str(item):
        if item['flowsize'] < 1024:
            return '{}B'.format(item['flowsize'])
        elif item['flowsize'] < 1024*1024:
            return '{:.1f}K'.format(item['flowsize']/1024)
        elif item['flowsize'] < 1024*1024*1024:
            return '{:.1f}M'.format(item['flowsize']/1024/1024)
        elif item['flowsize'] < 1024*1024*1024*1024:
            return '{:.1f}G'.format(item['flowsize']/1024/1024/1024)

    stats_df['flowsize_label'] = stats_df.apply(flowsize2str, axis=1)
    return stats_df


def get_fct_flowsize(flow_stats, n_groups=20):
    ''' Get statistics across different flow sizes
    Args:
        flow_stats: A DataFrame containing flow statistics data
            This is usually from XmlParser.stats_df
        n_groups: divide all stats into n_groups

    Returns:
        A DataFrame contains statistics vs. flow_size
    '''
    return get_stat_flowsize(flow_stats, 'fct', n_groups)


def get_fctslowdown_flowsize(flow_stats, n_groups=20):
    ''' Get statistics across different flow sizes
    Args:
        flow_stats: A DataFrame containing flow statistics data
            This is usually from XmlParser.stats_df
        n_groups: divide all stats into n_groups

    Returns:
        A DataFrame contains statistics vs. flow_size
    '''
    return get_stat_flowsize(flow_stats, 'fctSlowdown', n_groups)


class XmlParser(object):
    ''' Parse xml file containing flow monitor results

    Attributes:
        fname: The name of xml file
        stats_df: A DataFrame containing flow statistics data
        all_stats_df: A DataFrame containing all flow statistics data,
                      including reversed flow.
        fid2tuples: A dictionary mapping flow id to five tuple
        small_df: A DataFrame containing small flow statistics
        median_df: A DataFrame containing median flow statistics
        large_df: A DataFrame containing large flow statistics
        fct_breakdown: A Dictionary containing breakdown dct statistics
        fct_flowsize_df: A DataFrame containing fct vs. flowsize
    TODO:
        Mapping flow id to five tuple
    '''

    def __init__(self, fname):
        self.fname = fname
        self.parse()

    def parse(self):
        ''' Parsing a xml format file
        Getting flow stat data from the xml file.
        The result is stored in a DataFrame named "self.stats_df",
        in which the index is flow id and columns are flow stats.
        '''
        self.get_classifier()
        flow_stats = {}
        tree = ET.parse(self.fname)
        root = tree.getroot()
        for child in root.findall('FlowStats/Flow'):
            fid = int(child.get('flowId'))
            stats = {}
            for name, value in child.items():
                if value[-2:] == 'ns':
                    stats[name] = xmltime2floatsec(value)
                elif name == 'flowId':
                    continue
                else:
                    stats[name] = int(value)
            flow_stats[fid] = stats
            flow_stats[fid].update(self.fid2tuples[fid])
        df = pd.DataFrame.from_dict(flow_stats, orient='index')
        df['fct'] = df['timeLastRxPacket'] - df['timeFirstTxPacket']
        df['throughput'] = df['rxBytes'] * 8.0 / df['fct']
        self.all_stats_df = df.copy()
        # Delete reverse flows that only containing ACKs
        # Approach 1: too slow
        # isackflow = (df.txPackets < 0)
        # for index, row in df.iterrows():
        #     print(index)
        #     if isackflow[index]:
        #         continue
        #     isreverseflow = (
        #         (df.srcaddr == row.dstaddr)
        #         & (df.dstaddr == row.srcaddr)
        #         & (df.srcport == row.dstport)
        #         & (df.dstport == row.srcport)
        #     )
        #     reverserow = df[isreverseflow]
        #     # there should be only 1 reversed flow
        #     assert len(reverserow) == 1
        #     reverseindex = reverserow.index[0]
        #     reverserow = reverserow.iloc[0]
        #     if isackflow[reverseindex]:
        #         continue
        #     if row.timeFirstTxPacket < reverserow.timeFirstTxPacket:
        #         isackflow[reverseindex] = True
        #     else:
        #         isackflow[index] = True
        # self.stats_df = df[~isackflow].copy()

        # Approach 2:
        self.stats_df = df[df.txBytes / df.txPackets > 80].copy()
        return self.stats_df

    def get_fct_breakdown(self):
        ''' Statistics of different flow sizes
        '''
        self.fct_breakdown = get_fct_breakdown(self.stats_df.copy())
        return self.fct_breakdown

    def get_fct_flowsize(self):
        ''' FCT statistics of different flow sizes
        '''
        self.fct_flowsize_df = get_fct_flowsize(self.stats_df.copy())
        return self.fct_flowsize_df

    def get_classifier(self):
        ''' Get the flow classifier from xml file
        The flow classifier is stored into fid2tuples
        '''
        tree = ET.parse(self.fname)
        root = tree.getroot()
        self.fid2tuples = {}
        for child in root.findall('Ipv4FlowClassifier/Flow'):
            fid = int(child.get('flowId'))
            self.fid2tuples[fid] = {
                'srcaddr': child.get('sourceAddress'),
                'dstaddr': child.get('destinationAddress'),
                'protocol': int(child.get('protocol')),
                'srcport': int(child.get('sourcePort')),
                'dstport': int(child.get('destinationPort')),
            }
        return self.fid2tuples
