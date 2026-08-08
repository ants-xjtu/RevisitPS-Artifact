#!/usr/bin/python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("group_fct_split_by_lb_recovery.py")


class GroupFctSplitByLbRecoveryTest(unittest.TestCase):
    def test_groups_series_by_lb_and_recovery_across_buffer_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            input_dir = tmpdir / "input"
            output_dir = tmpdir / "output"
            input_dir.mkdir()

            self._write_json(
                input_dir / "topoA__bufsz_0.31.json",
                buffer_size="0.31",
                series=[
                    {
                        "config_id": "1",
                        "load_balancing_mode": "ECMP",
                        "recovery_mechanism": "NAK+GBN",
                        "buffer_size": "0.31",
                    },
                    {
                        "config_id": "2",
                        "load_balancing_mode": "LetFlow",
                        "recovery_mechanism": "NAK+SR",
                        "buffer_size": "0.31",
                    },
                ],
            )
            self._write_json(
                input_dir / "topoA__bufsz_0.50.json",
                buffer_size="0.50",
                series=[
                    {
                        "config_id": "3",
                        "load_balancing_mode": "ECMP",
                        "recovery_mechanism": "NAK+GBN",
                        "buffer_size": "0.50",
                    }
                ],
            )

            subprocess.run(
                [sys.executable, str(SCRIPT), "--input-dir", str(input_dir), "--output-dir", str(output_dir)],
                check=True,
                capture_output=True,
                text=True,
            )

            ecmp_file = output_dir / "ECMP__NAK_GBN.json"
            letflow_file = output_dir / "LetFlow__NAK_SR.json"
            self.assertTrue(ecmp_file.exists())
            self.assertTrue(letflow_file.exists())

            ecmp_data = json.loads(ecmp_file.read_text())
            self.assertEqual(ecmp_data["group"]["load_balancing_mode"], "ECMP")
            self.assertEqual(ecmp_data["group"]["recovery_mechanism"], "NAK+GBN")
            self.assertEqual(ecmp_data["buffer_sizes"], ["0.31", "0.50"])
            self.assertEqual(len(ecmp_data["variants"]), 2)
            self.assertEqual(ecmp_data["variants"][0]["data_series"][0]["config_id"], "1")
            self.assertEqual(ecmp_data["variants"][1]["data_series"][0]["config_id"], "3")

            letflow_data = json.loads(letflow_file.read_text())
            self.assertEqual(letflow_data["buffer_sizes"], ["0.31"])
            self.assertEqual(letflow_data["variants"][0]["data_series"][0]["config_id"], "2")

    @staticmethod
    def _write_json(path: Path, buffer_size: str, series):
        payload = {
            "metadata": {
                "topology": "topoA",
                "buffer_size": buffer_size,
                "source": path.name.replace(".json", ".txt"),
                "num_runs": len(series),
            },
            "x_axis_percentiles": [50.0, 100.0],
            "data_series": series,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
