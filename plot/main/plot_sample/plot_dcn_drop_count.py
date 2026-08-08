import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import glob

# Import the project's custom plotting library
# Assuming plot.py is in lib/py/plot/plot.py relative to the script's location
import lib.py.plot.plot as plot

# --- Helper function to escape LaTeX special characters ---
def escape_latex(s):
    """Escape LaTeX special characters in a string."""
    if not isinstance(s, str):
        s = str(s)
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\^{}",
        "\\": r"\textbackslash{}",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s

desired_order = [
    "AR\n(DCP)",
    "ECMP\n(NAK+SR)",
    "LetFlow\n(NAK+SR)",
    "CONGA\n(NAK+SR)",
    "ConWeave\n(NAK+SR)",
    "AR\n(RTO+GBN)",
    "AR\n(IdealTrimming)",
    "AR\n(Ideal)",
    "AR\n(RTO+GBN+slowstart)",
    "AR\n(IdealTrimming+slowstart)",
    "AR\n(Ideal+slowstart)",
]


def draw_drop_plot(json_path, output_path):
    """
    Generates a grouped and stacked bar chart of packet drop counts from a JSON file,
    using the styling templates from the custom plot.py library.
    """
    # Enable LaTeX rendering for high-quality labels
    plt.rcParams['text.usetex'] = True

    # --- Load JSON ---
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Error reading or parsing {json_path}: {e}")
        return

    metadata = data.get("metadata", {})
    data_series_list = data.get("data_series", [])
    if not data_series_list:
        print(f"⚠️ No 'data_series' found in {json_path}. Skipping.")
        return

    # --- Prepare Data ---
    group_labels = []
    tor_up_counts = []
    tor_down_counts = []
    spine_up_counts = []
    spine_down_counts = []
    core_counts = []

    for series in data_series_list:
        lb_mode = escape_latex(series.get('load_balancing_mode', 'N/A'))
        recovery = escape_latex(series.get('recovery_mechanism', 'N/A'))
        label = f"{lb_mode}\n({recovery})"
        group_labels.append(label)

        drops = series.get('drop_counts', {})
        tor_up_counts.append(drops.get('tor_drops_up', 0))
        tor_down_counts.append(drops.get('tor_drops_down', 0))
        spine_up_counts.append(drops.get('spine_drops_up', 0))
        
        # Robustly handle potential key variations for spine downlink drops
        spine_down_val = drops.get('spine_drops_down', drops.get('spine_drops_down_down', 0))
        spine_down_counts.append(spine_down_val)

        core_counts.append(drops.get('core_drops', 0))
    series_dict = {}
    for i, label in enumerate(group_labels):
        series_dict[label] = {
            "tor_up": tor_up_counts[i],
            "tor_down": tor_down_counts[i],
            "spine_up": spine_up_counts[i],
            "spine_down": spine_down_counts[i],
            "core": core_counts[i],
        }

    # Reset and refill in desired order
    group_labels = []
    tor_up_counts = []
    tor_down_counts = []
    spine_up_counts = []
    spine_down_counts = []
    core_counts = []

    for label in desired_order:
        if label in series_dict:   # only keep labels that exist
            group_labels.append(label)
            tor_up_counts.append(series_dict[label]["tor_up"])
            tor_down_counts.append(series_dict[label]["tor_down"])
            spine_up_counts.append(series_dict[label]["spine_up"])
            spine_down_counts.append(series_dict[label]["spine_down"])
            core_counts.append(series_dict[label]["core"])

    total_drops = sum(tor_up_counts) + sum(tor_down_counts) + \
                  sum(spine_up_counts) + sum(spine_down_counts) + sum(core_counts)
    if total_drops == 0:
        print(f"ℹ️ No drops to plot for {json_path}. Skipping PDF generation.")
        return

    # --- Plotting Setup ---
    # Use BarPlot to leverage its styling capabilities ('fillstyles')
    p = plot.BarPlot()
    
    tor_up = np.array(tor_up_counts)
    tor_down = np.array(tor_down_counts)
    spine_up = np.array(spine_up_counts)
    spine_down = np.array(spine_down_counts)
    core = np.array(core_counts)

    n_groups = len(group_labels)
    
    # --- MODIFICATION: Add spacing between major groups ---
    group_spacing = 1.5  # Increase this value to add more space between groups
    x_indices = np.arange(n_groups) * group_spacing
    
    bar_width = 0.25
    group_gap = 0.1 # This is the small gap between bars within a group
    pos_spine = x_indices - bar_width - group_gap / 2
    pos_tor = x_indices
    pos_core = x_indices + bar_width + group_gap / 2
    
    # --- Get styles from plot.py template ---
    # We manually advance p.n_groups to cycle through the `fillstyles` list
    style_spine_down = p.get_plot_args()
    style_spine_down['label'] = 'Spine Downlink'
    p.n_groups += 1

    style_spine_up = p.get_plot_args()
    style_spine_up['label'] = 'Spine Uplink'
    p.n_groups += 1

    style_tor_down = p.get_plot_args()
    style_tor_down['label'] = 'ToR Downlink'
    p.n_groups += 1

    style_tor_up = p.get_plot_args()
    style_tor_up['label'] = 'ToR Uplink'
    p.n_groups += 1
    
    style_core = p.get_plot_args()
    style_core['label'] = 'Core'
    p.n_groups += 1

    # --- Draw Bars using styles from the template ---
    # 1. Spine Bar (Stacked) - Uplink at the bottom
    p.ax.bar(pos_spine, spine_up, width=bar_width, **style_spine_up)
    p.ax.bar(pos_spine, spine_down, bottom=spine_up, width=bar_width, **style_spine_down)

    # 2. ToR Bar (Stacked) - Uplink at the bottom
    p.ax.bar(pos_tor, tor_up, width=bar_width, **style_tor_up)
    p.ax.bar(pos_tor, tor_down, bottom=tor_up, width=bar_width, **style_tor_down)

    # 3. Core Bar (Single)
    p.ax.bar(pos_core, core, width=bar_width, **style_core)

    # --- Customize Plot ---
    p.ax.set_ylabel("Packet Drop Count", fontsize=20)
    
    p.ax.set_xticks(x_indices)
    p.ax.set_xticklabels(group_labels, rotation=30, ha='center', fontsize=10)


    p.ax.set_yscale('symlog', linthresh=1)
    p.ax.tick_params(axis='x', labelsize=10)   # x 轴刻度字体
    p.ax.tick_params(axis='y', labelsize=15)   # y 轴刻度字体
    
    # Create the legend and place it outside the plot area
    p.ax.legend(
        fontsize=10,
        loc='upper center',      # 放在上边中间
        bbox_to_anchor=(0.5, 1.15),  # 往图外上方挪一点
        ncol=5,                  # 图例排成一行（数字改成实际的 legend 个数）
        frameon=False            # 去掉边框（可选）
    )
        
    p.fig.tight_layout(rect=[0, 0.1, 0.85, 0.95])

    # --- Save ---
    plt.savefig(output_path)
    plt.close()
    print(f"✅ Grouped drop count chart saved to: {output_path}")


def main():
    """
    Main function to parse command-line arguments and process JSON files.
    """
    parser = argparse.ArgumentParser(
        description="Generate grouped, stacked bar charts for packet drop counts from JSON data."
    )
    parser.add_argument(
        "input_path",
        type=str,
        help="Input path: can be a single JSON file or a directory containing JSON files."
    )
    args = parser.parse_args()

    if os.path.isfile(args.input_path):
        json_file = args.input_path
        base_name = os.path.basename(json_file)
        output_name = os.path.splitext(base_name)[0].replace("DROPS_", "plot_drops_grouped_") + '.pdf'
        output_path = os.path.join(os.path.dirname(json_file), output_name)
        print(f"--- Processing single file: {json_file} ---")
        draw_drop_plot(json_file, output_path)

    elif os.path.isdir(args.input_path):
        json_files = glob.glob(os.path.join(args.input_path, '*.json'))
        if not json_files:
            print(f"⚠️ No .json files found in directory: {args.input_path}")
            return
            
        print(f"Found {len(json_files)} JSON files. Starting batch processing...")
        for json_file in json_files:
            base_name = os.path.basename(json_file)
            output_name = os.path.splitext(base_name)[0].replace("DROPS_", "plot_drops_grouped_") + '.pdf'
            output_path = os.path.join(args.input_path, output_name)
            print(f"--- Processing: {json_file} ---")
            draw_drop_plot(json_file, output_path)
        print("✅ All files processed!")

    else:
        print(f"❌ Error: The path '{args.input_path}' is not a valid file or directory.")
        return


if __name__ == '__main__':
    main()