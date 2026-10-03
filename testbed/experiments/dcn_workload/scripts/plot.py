"""Render Figure 2 using the root plot library and its unmodified paper style."""
import csv
import hashlib
import json
from pathlib import Path
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'plot'))
from lib.py.plot.plot import LinePointPlot, colors, markerstyles
from experiments.dcn_workload.scripts.fct_statistics import ALGORITHMS, normalize

STYLE_INDEX = {'BigSwitch': 0, 'ECMP': 1, 'RPS': 2}


def format_size(value):
    if value < 10000:
        return f'{value / 1000:.1f}K'
    if value < 1e6:
        return f'{value / 1000:.0f}K'
    return f'{value / 1e6:.1f}M'


def draw_panel(plot, curves, fabric, axid=0):
    ax = plot.axes[axid]
    for algorithm in ALGORITHMS:
        rows = sorted((r for r in curves if r['group'] == fabric and r['algorithm'] == algorithm),
                      key=lambda r: r['bucket'])
        index = STYLE_INDEX[algorithm]
        x = [r['bucket'] for r in rows]
        plot.plot(x, [r['normalized_p99'] for r in rows], axid=axid,
                  label=algorithm, color=colors[index], **markerstyles[index])
        if rows[0]['repeats'] > 1:
            ax.fill_between(x, [r['repeat_min'] for r in rows], [r['repeat_max'] for r in rows],
                            color=colors[index], alpha=.12)
    labels = [format_size(r['size_max_bytes']) if i % 2 == 0 else '' for i, r in enumerate(rows)]
    ax.set_xticks(x, labels, rotation=45, ha='right')
    ax.tick_params(axis='x', labelbottom=True)
    ax.set_xlabel('Flow Size (Bytes)')
    ax.set_ylabel('Normalized P99 FCT')
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.margins(x=.025, y=.12)  # No fixed limits that could hide actual results.
    ax.legend(loc='best').set_zorder(200)


def save(plot, path):
    try:
        plot.fig.tight_layout(pad=1.0)
        for suffix in ('pdf', 'svg', 'png'):
            plot.fig.savefig(path.with_suffix('.' + suffix), dpi=180, pad_inches=.08)
    finally:
        plt.close(plot.fig)


def plot_results(run_dir):
    run_dir = Path(run_dir)
    source = run_dir / 'parsed/figure2-buckets.json'
    if not source.is_file():
        raise ValueError('Missing Figure 2 buckets; rerun --stage parse with the updated parser')
    curves = normalize(json.loads(source.read_text()))
    output = run_dir / 'figures'
    output.mkdir(exist_ok=True)
    with (output / 'figure2-source.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(curves[0]))
        writer.writeheader()
        writer.writerows(curves)
    fabrics = [f for f in ('lossless', 'lossy') if any(r['group'] == f for r in curves)]
    spec = dict(figure=dict(id='figure2', claim='Compare P99 FCT against BigSwitch across flow sizes.',
                           source_scale=3, target_width_inches=7, status='generated-awaiting-visual-review'),
                source_data=dict(path=str(source.resolve()), sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
                panels=fabrics, methods=list(ALGORITHMS),
                statistics=dict(buckets=19, membership='historical 09cf327: size order, FCT sort and 100-way interleave within each size',
                                fct='end - max(start, previous end); omit final physical line of each CSV',
                                bucket_p99='clamp FCT >= 1 us; sorted values[int(n * 0.99)]',
                                normalization='same fabric, repeat and complete input identity set; divide by BigSwitch bucket P99',
                                repeated_runs='equal mean of per-repeat ratios; band shows min/max',
                                boundary='Reproduces the original testbed scripts at 09cf327.'),
                style=dict(path='plot/lib/py/plot/paper.mplstyle', sha256=hashlib.sha256((ROOT/'plot/lib/py/plot/paper.mplstyle').read_bytes()).hexdigest(),
                           modified=False, renderer='LinePointPlot; original TeX and font settings'))
    (output / 'figure_spec.yaml').write_text(yaml.safe_dump(spec, sort_keys=False))
    with plt.rc_context():
        for fabric in fabrics:
            plot = LinePointPlot()
            plot.fig.set_size_inches(10.5, 8.4)
            draw_panel(plot, curves, fabric)
            save(plot, output / ('figure2' + ('a-' if fabric == 'lossless' else 'b-') + fabric))
        if len(fabrics) == 2:
            plot = LinePointPlot(nplots=2)
            plot.fig.set_size_inches(21, 8.4)
            # Independent X axes retain each fabric's own measured size labels.
            for ax in plot.axes:
                plot.fig.delaxes(ax)
            plot.axes = tuple(plot.fig.add_subplot(1, 2, i + 1) for i in range(2))
            plot.ax = plot.axes[0]
            plot.set_ax_style()
            low = min(r['repeat_min'] for r in curves)
            high = max(r['repeat_max'] for r in curves)
            margin = max((high - low) * .12, .025)
            for index, fabric in enumerate(fabrics):
                plot.axes[index].set_ylim(low - margin, high + margin)
                draw_panel(plot, curves, fabric, index)
                plot.axes[index].text(.5, -.36, '(a) Lossless' if index == 0 else '(b) Lossy',
                                      transform=plot.axes[index].transAxes, ha='center', fontsize=30)
            save(plot, output / 'figure2')
    (output / 'caption.md').write_text(
        'Normalized 99th percentile FCT for WebSearch at 80% offered load: '
        + ('(a) lossless and (b) lossy. ' if len(fabrics) == 2 else fabrics[0] + ' fabric. ')
        + 'Historical FCT uses end - max(start, previous end), omits the final CSV line, '
        + 'and uses the original 100-way interleaving and discrete bucket percentile. '
        + 'Within each flow-size rank, P99 FCT is normalized '
        'to BigSwitch using the same inputs and repeat. Lines show equal-weight means '
        'of per-repeat ratios; where multiple repeats exist, bands show their range.\n')
    print('Figure 2 outputs: ' + str(output))
