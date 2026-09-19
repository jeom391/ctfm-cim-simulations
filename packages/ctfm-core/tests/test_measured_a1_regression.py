"""The A1 acceptance regression from docs/spec/05-implementation.md (P1).

The original measurement file has never been supplied, so this suite skips
rather than silently not existing. Point CTFM_A1_FILE at the real A1 workbook
and it runs; the expected numbers come from the spec's acceptance criteria, not
from whatever the parser happens to produce.

    CTFM_A1_FILE=/path/to/A1.xlsx uv run --locked pytest -q \
        packages/ctfm-core/tests/test_measured_a1_regression.py

Optional overrides for sheet and column names are read from the environment so
no guess about the workbook's layout is baked into the test.
"""
import hashlib
import json
import os
import unittest
from pathlib import Path

from ctfm.measurement import DEFAULTS, analyze, parse_table

A1_FILE = os.environ.get("CTFM_A1_FILE")
A1_SHEET = os.environ.get("CTFM_A1_SHEET") or None
A1_DEVICE = os.environ.get("CTFM_A1_DEVICE", "A1-DEVICE")

# docs/spec/05-implementation.md P1: "전환 1024 → 읽기 1022", "1.15e-5 A → 115 µS".
EXPECTED_TRANSITIONS = 1024
EXPECTED_READ_STATES = 1022
EXPECTED_LTD_ID_A = 1.15e-5
EXPECTED_LTD_G_S = 115e-6
VDS_V = DEFAULTS["vds_v"]


@unittest.skipUnless(A1_FILE, "Set CTFM_A1_FILE to the original A1 measurement file")
class MeasuredA1RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(A1_FILE)
        if not path.is_file():
            raise unittest.SkipTest("CTFM_A1_FILE does not exist: %s" % path)
        cls.raw = path.read_bytes()
        cls.sha256 = hashlib.sha256(cls.raw).hexdigest()
        cls.table = parse_table(cls.raw, path.name, sheet=A1_SHEET)

    def columns(self):
        """Explicit mapping only; the spec forbids inferring it from the file."""
        mapping = os.environ.get("CTFM_A1_COLUMNS")
        if mapping:
            return json.loads(mapping)
        headers = {str(h).strip().lower(): h for h in (self.table.get("columns") or [])}
        guess = {}
        for key, names in (("time_s", ("time", "time (s)", "t")),
                           ("vgs_v", ("vgs", "vg", "gate")),
                           ("id_a", ("id", "current", "drain current"))):
            for name in names:
                if name in headers:
                    guess[key] = headers[name]
                    break
        if len(guess) != 3:
            raise unittest.SkipTest(
                "Set CTFM_A1_COLUMNS to a JSON column mapping; detected only %s from %s"
                % (sorted(guess), sorted(headers)))
        return guess

    def analysis(self, direction):
        dataset = dict(file_id="a1", sha256=self.sha256, filename=Path(A1_FILE).name,
                       sheet=A1_SHEET, device_id=A1_DEVICE, condition_id="A1",
                       columns=self.columns(), units=dict(time_s="s", vgs_v="V", id_a="A"),
                       read_vgs_v=DEFAULTS["read_vgs_v"], vds_v=VDS_V, direction=direction,
                       rows=self.table["rows"])
        return analyze("pulse_states", [dataset], {})

    def test_transition_and_read_state_counts_match_the_acceptance_criteria(self):
        states = []
        for direction in ("ltp", "ltd"):
            states.extend(self.analysis(direction)["states"])
        transitions = len({s["transition_row"] for s in states})
        self.assertEqual(transitions, EXPECTED_TRANSITIONS,
                         "expected %d write transitions" % EXPECTED_TRANSITIONS)
        self.assertEqual(len(states), EXPECTED_READ_STATES,
                         "expected %d extracted read states" % EXPECTED_READ_STATES)

    def test_absolute_read_current_converts_to_conductance_without_baseline_subtraction(self):
        states = self.analysis("ltd")["states"]
        matches = [s for s in states
                   if abs(s["id_a"] - EXPECTED_LTD_ID_A) <= 1e-9]
        self.assertTrue(matches, "no LTD state near %g A" % EXPECTED_LTD_ID_A)
        for state in matches:
            self.assertAlmostEqual(state["conductance_s"], state["id_a"] / VDS_V, places=12)
            self.assertAlmostEqual(state["conductance_s"], EXPECTED_LTD_G_S, delta=1e-9)

    def test_provenance_keeps_the_original_hash_and_row_numbers(self):
        result = self.analysis("ltp")
        self.assertEqual(result["provenance"][0]["sha256"], self.sha256)
        for state in result["states"]:
            self.assertIsInstance(state["source_row"], int)
            self.assertGreater(state["source_row"], 0)


if __name__ == "__main__":
    unittest.main()
