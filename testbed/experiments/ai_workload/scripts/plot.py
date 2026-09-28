"""Plot per-group, per-repeat means; do not pool samples across concurrent groups."""
import json


def plot_results(run_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows = json.loads((run_dir / 'parsed/jct.json').read_text())
    output = run_dir / 'figures'
    output.mkdir(exist_ok=True)
    for workload in sorted({r['workload'] for r in rows}):
        selected = [r for r in rows if r['workload'] == workload]
        labels = [f"{r['network_mode']} / {r['algorithm']}\n{r['group']} / r{r['repeat']}" for r in selected]
        fig, ax = plt.subplots(figsize=(max(8, len(selected) * .7), 4.5))
        ax.bar(range(len(selected)), [r['mean_us'] for r in selected])
        ax.set_xticks(range(len(selected)), labels, rotation=60, ha='right', fontsize=8)
        ax.set_ylabel('Mean JCT (µs)'); ax.set_title(workload)
        fig.tight_layout()
        for ext in ('png', 'pdf'):
            fig.savefig(output / f'{workload}.{ext}', dpi=180)
        plt.close(fig)
