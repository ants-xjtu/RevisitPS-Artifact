#!/usr/bin/python3

import os
import unittest
from pathlib import Path

from analysis.optimal_jct_analyzer import NetworkTopology, TreeAllReduceAnalyzer


SIMULATION_ROOT = Path(__file__).resolve().parents[1]


class NetworkTopologyTest(unittest.TestCase):
    def test_reads_link_bandwidth_from_ns3_topology_files(self):
        previous_cwd = Path.cwd()
        try:
            os.chdir(SIMULATION_ROOT)
            topology_400g = NetworkTopology("leaf_spine_L8_S16_400G_OS1")
            topology_100g = NetworkTopology("leaf_spine_L8_S16_100G_OS1")
        finally:
            os.chdir(previous_cwd)

        self.assertEqual(topology_400g.num_servers, 128)
        self.assertEqual(topology_400g.get_bottleneck_bandwidth(), 400)
        self.assertEqual(topology_100g.get_bottleneck_bandwidth(), 100)

    def test_ring_allreduce_uses_reduce_scatter_and_allgather_steps(self):
        previous_cwd = Path.cwd()
        try:
            os.chdir(SIMULATION_ROOT)
            topology = NetworkTopology("leaf_spine_L8_S16_400G_OS1")
        finally:
            os.chdir(previous_cwd)
        analyzer = TreeAllReduceAnalyzer(topology)

        result = analyzer.calculate_ring_allreduce_jct(11234742, 8)

        self.assertEqual(result["total_steps"], 14)
        self.assertAlmostEqual(result["ideal_jct_ms"] * 1000, 3145.72776)


if __name__ == "__main__":
    unittest.main()
