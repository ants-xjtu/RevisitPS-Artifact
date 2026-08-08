import os
import sys

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd

import lib.py.plot.plot as myplot


def example_cdf(fname=None):
    if fname is None:
        data = np.geomspace(1, 100, 10000)
    else:
        data = np.loadtxt(fname)
    cp = myplot.CDFPlot()
    cp.plot(data, label='line1')
    plt.show()

def example():
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    data_fname = os.path.join(cur_dir, 'data.csv')
    df = pd.read_csv(data_fname, sep=r'\s+', header=None)
    lpp = myplot.LinePointPlot()
    idx = 1
    while idx < df.shape[1]:
        lpp.plot(df.iloc[:, 0], df.iloc[:, idx])
        idx += 1
    plt.show()


if __name__ == '__main__':
    usage = 'USAGE: %s [cdf [FILE] | broken-axis]' % sys.argv[0]
    if len(sys.argv) == 1:
        example()
    elif len(sys.argv) >= 2 and sys.argv[1] == 'cdf':
        if len(sys.argv) == 2:
            example_cdf(None)
        else:
            example_cdf(sys.argv[2])
    else:
        print(usage)
