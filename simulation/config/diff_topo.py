import os
import argparse

def read_topo_file(filename):
    with open(filename, "r") as f:
        lines = f.readlines()

    # 过滤掉空行或注释行（非以数字开头的）
    lines = [line.strip() for line in lines if line.strip() and line[0].isdigit()]

    if len(lines) < 2:
        raise ValueError(f"File {filename} seems malformed or missing topology info.")

    header = lines[0].split()
    num_nodes, num_switches, num_links = map(int, header)

    switch_ids = list(map(int, lines[1].split()))

    links = set()
    for line in lines[2:]:
        parts = line.split()
        if len(parts) >= 2:
            try:
                src, dst = int(parts[0]), int(parts[1])
                links.add((src, dst))
            except ValueError:
                continue  # 忽略非数字开头的意外行

    return {
        "filename": filename,
        "num_nodes": num_nodes,
        "num_switches": num_switches,
        "num_links": num_links,
        "switch_ids": set(switch_ids),
        "links": links,
    }

def compare_topos(file1, file2):
    topo1 = read_topo_file(file1)
    topo2 = read_topo_file(file2)

    print(f"Comparing:\n  {file1}\n  {file2}\n")

    if topo1["num_nodes"] != topo2["num_nodes"]:
        print(f"⚠️  Node count mismatch: {topo1['num_nodes']} vs {topo2['num_nodes']}")
    if topo1["num_switches"] != topo2["num_switches"]:
        print(f"⚠️  Switch count mismatch: {topo1['num_switches']} vs {topo2['num_switches']}")
    if topo1["num_links"] != topo2["num_links"]:
        print(f"⚠️  Link count mismatch: {topo1['num_links']} vs {topo2['num_links']}")

    # Switch ID difference
    only_in_1 = topo1["switch_ids"] - topo2["switch_ids"]
    only_in_2 = topo2["switch_ids"] - topo1["switch_ids"]
    if only_in_1 or only_in_2:
        print("⚠️  Switch IDs differ:")
        if only_in_1:
            print(f"  Only in {file1}: {sorted(only_in_1)}")
        if only_in_2:
            print(f"  Only in {file2}: {sorted(only_in_2)}")

    # Link difference
    link_diff_1 = topo1["links"] - topo2["links"]
    link_diff_2 = topo2["links"] - topo1["links"]
    if link_diff_1 or link_diff_2:
        print("⚠️  Link entries differ:")
        if link_diff_1:
            print(f"  Present in {file1} only: {sorted(link_diff_1)}")
        if link_diff_2:
            print(f"  Present in {file2} only: {sorted(link_diff_2)}")
    else:
        print("✅ Topologies are identical in terms of link entries.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two topology files.")
    parser.add_argument("file1", nargs="?", default=os.path.join(os.path.dirname(__file__), "leaf_spine_128_100G_OS2.txt"))
    parser.add_argument("file2", nargs="?", default=os.path.join(os.path.dirname(__file__), "leaf_spine_128_100G_OS2.txt"))
    args = parser.parse_args()
    compare_topos(args.file1, args.file2)
