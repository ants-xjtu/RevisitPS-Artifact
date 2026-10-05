"""Figure 3-style CCT summaries; minimum group/repeat mean, actual byte budget."""
import csv
import json
import math
from pathlib import Path

WORKLOADS = [('ring_allreduce', 'AllR'), ('alltoall', 'A2A'), ('alltoallv', 'A2Av')]
ALGORITHMS = ('ECMP', 'RPS', 'BigSwitch')
# Effective bandwidth used by the original testbed Figure 3 plotting script.
OPTIMAL_BW_BPS = 98 * 10**9


def collect(run_dir):
    run_dir = Path(run_dir)
    rows = json.loads((run_dir / 'parsed/jct.json').read_text())
    tasks = json.loads((run_dir / 'status.json').read_text())['tasks']
    selected = {}
    capacities = {}
    for row in rows:
        task = tasks[row['task_id']]
        if task['status'] != 'completed':
            raise ValueError('Parsed result is not completed: ' + row['task_id'])
        config = json.loads((run_dir / task['attempt'] / 'configs/ai.json').read_text())
        size = config['parameters']['target_recv_bytes']
        mean = float(row['mean_us'])
        if not isinstance(size, int) or size <= 0 or not math.isfinite(mean) or mean <= 0:
            raise ValueError('Invalid byte budget or mean: ' + row['task_id'])
        fabric, workload, algorithm = row['network_mode'], row['workload'], row['algorithm']
        if fabric not in ('lossless', 'lossy') or workload not in dict(WORKLOADS) or algorithm not in ALGORITHMS:
            raise ValueError('Unsupported AI series: ' + row['task_id'])
        # Do not silently compare different experiment sizes in one category.
        category = (fabric, workload)
        if capacities.setdefault(category, size) != size:
            raise ValueError('Mixed byte budgets for ' + str(category))
        ideal = size * 8 / OPTIMAL_BW_BPS * 1e6
        point = dict(network_mode=fabric, workload=workload, algorithm=algorithm,
                     task_id=row['task_id'], group=row['group'], repeat=row['repeat'],
                     mean_us=mean, target_recv_bytes=size, ideal_cct_us=ideal,
                     normalized_cct=mean / ideal)
        key = (fabric, workload, algorithm)
        # Match the supplied script: retain the smaller mean for duplicate series.
        if key not in selected or mean < selected[key]['mean_us']:
            selected[key] = point
    if not selected:
        raise ValueError('No completed AI results to plot')
    return list(selected.values())


def plot_results(run_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    run_dir = Path(run_dir)
    points = collect(run_dir)
    output = run_dir / 'figures'
    output.mkdir(exist_ok=True)
    with (output / 'cct-source.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(points[0]))
        writer.writeheader()
        writer.writerows(points)
    styles = [dict(color='#a00000'), dict(color='#A0A0A0'),
              dict(facecolor='none', edgecolor='#00a000', hatch='////')]
    with plt.rc_context({'text.usetex': False, 'font.family': 'DejaVu Sans',
                         'font.size': 16, 'axes.axisbelow': True}):
        for fabric in ('lossless', 'lossy'):
            subset = [p for p in points if p['network_mode'] == fabric]
            if not subset:
                continue
            values = {(p['workload'], p['algorithm']): p['normalized_cct'] for p in subset}
            workloads = [(w, label) for w, label in WORKLOADS if any(p['workload'] == w for p in subset)]
            fig, ax = plt.subplots(figsize=(8, 5))
            try:
                width = .24
                for index, algorithm in enumerate(ALGORITHMS):
                    # Missing results remain blank rather than appearing as zero CCT.
                    heights = [values.get((w, algorithm), float('nan')) for w, _ in workloads]
                    if all(math.isnan(v) for v in heights):
                        continue
                    ax.bar([x + (index - 1) * width for x in range(len(workloads))],
                           heights, width=width * .9, label=algorithm,
                           linewidth=1.2, **styles[index])
                ax.set_xticks(range(len(workloads)), [label for _, label in workloads])
                ax.set_ylabel('Normalized CCT')
                ax.set_title(fabric.capitalize())
                ax.set_ylim(0, max(4, max(p['normalized_cct'] for p in subset) * 1.12))
                ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
                ax.grid(False, axis='x')
                ax.grid(True, axis='y', linestyle=':', color='0.7')
                ax.legend(loc='best', frameon=True, facecolor='white', framealpha=1)
                fig.tight_layout()
                for suffix in ('pdf', 'svg', 'png'):
                    fig.savefig(output / f'cct-{fabric}.{suffix}', dpi=180)
            finally:
                plt.close(fig)
