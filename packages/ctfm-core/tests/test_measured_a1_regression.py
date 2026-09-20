"""The A1 acceptance regression from docs/spec/05-implementation.md (P1).

The original measurement file has never been supplied, so this suite skips
rather than silently not existing. Point CTFM_A1_FILE at the real A1 workbook
and it runs; the expected relations come from the spec's acceptance criteria,
not from whatever the parser happens to produce.

    CTFM_A1_FILE=/path/to/A1.xlsx uv run --locked pytest -q \
        packages/ctfm-core/tests/test_measured_a1_regression.py

Per-file counts are provenance, not a rule, so they are asserted only when
CTFM_A1_EXPECTED_TRANSITIONS / CTFM_A1_EXPECTED_READ_STATES are set for the
file actually being run.

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
# One sheet cannot hold both pulse polarities: the analyzer rejects an LTD run
# over negative pulses and vice versa. Which directions this sheet carries is a
# property of the file, so the operator states it instead of the test assuming.
A1_DIRECTIONS = tuple(d.strip() for d in
                      os.environ.get("CTFM_A1_DIRECTIONS", "ltp,ltd").split(",") if d.strip())

# docs/spec/08-hardware-baseline.md acceptance 1: the rule under test is the row
# NUMBER relation -- the read state for a transition at source row j comes from
# row j-2, so "transition 1024 -> read 1022" means source_row == transition_row-2,
# not "1024 transitions and 1022 states". The counts belong to the one workbook
# the spec was written against; a re-measured file has its own provenance, so
# they are only asserted when the operator states them.
TRANSITION_TO_READ_ROW_OFFSET = 2
NAMED_TRANSITION_ROW = 1024
NAMED_READ_ROW = 1022


def _expected_count(name):
    raw = os.environ.get(name)
    return int(raw) if raw else None


EXPECTED_TRANSITIONS = _expected_count("CTFM_A1_EXPECTED_TRANSITIONS")
EXPECTED_READ_STATES = _expected_count("CTFM_A1_EXPECTED_READ_STATES")
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
                       column_mapping=self.columns(),
                       units=dict(time_s="s", vgs_v="V", id_a="A"),
                       read_vgs_v=DEFAULTS["read_vgs_v"], vds_v=VDS_V, direction=direction,
                       rows=self.table["rows"], source_rows=self.table["source_rows"])
        return analyze("pulse_states", [dataset], {})

    def all_states(self):
        states = []
        for direction in A1_DIRECTIONS:
            states.extend(self.analysis(direction)["states"])
        self.assertTrue(states, "no read states extracted from the A1 workbook")
        return states

    def test_each_read_state_comes_from_the_row_two_above_its_transition(self):
        """The j-2 rule, checked on original row numbers rather than on counts."""
        for state in self.all_states():
            self.assertEqual(state["transition_row"] - state["source_row"],
                             TRANSITION_TO_READ_ROW_OFFSET,
                             "transition row %s must read row %s, got %s"
                             % (state["transition_row"],
                                state["transition_row"] - TRANSITION_TO_READ_ROW_OFFSET,
                                state["source_row"]))

    def test_the_named_transition_row_reads_the_named_source_row(self):
        """docs/spec/08 acceptance 1: transition at row 1024 reads row 1022."""
        named = [s for s in self.all_states()
                 if s["transition_row"] == NAMED_TRANSITION_ROW]
        if not named:
            self.skipTest("This workbook has no transition at row %d; supply the "
                          "expected rows for the new file's provenance"
                          % NAMED_TRANSITION_ROW)
        for state in named:
            self.assertEqual(state["source_row"], NAMED_READ_ROW)

    def test_counts_match_when_the_operator_states_them_for_this_file(self):
        states = self.all_states()
        transitions = len({s["transition_row"] for s in states})
        if EXPECTED_TRANSITIONS is None and EXPECTED_READ_STATES is None:
            self.skipTest("Set CTFM_A1_EXPECTED_TRANSITIONS / "
                          "CTFM_A1_EXPECTED_READ_STATES for this file; counts are "
                          "per-file provenance, not a general acceptance rule "
                          "(this file: %d transitions, %d states)"
                          % (transitions, len(states)))
        if EXPECTED_TRANSITIONS is not None:
            self.assertEqual(transitions, EXPECTED_TRANSITIONS)
        if EXPECTED_READ_STATES is not None:
            self.assertEqual(len(states), EXPECTED_READ_STATES)

    def test_absolute_read_current_converts_to_conductance_without_baseline_subtraction(self):
        states = self.analysis(A1_DIRECTIONS[-1])["states"]
        matches = [s for s in states
                   if abs(s["id_a"] - EXPECTED_LTD_ID_A) <= 1e-9]
        self.assertTrue(matches, "no LTD state near %g A" % EXPECTED_LTD_ID_A)
        for state in matches:
            self.assertAlmostEqual(state["conductance_s"], state["id_a"] / VDS_V, places=12)
            self.assertAlmostEqual(state["conductance_s"], EXPECTED_LTD_G_S, delta=1e-9)

    def test_provenance_keeps_the_original_hash_and_row_numbers(self):
        result = self.analysis(A1_DIRECTIONS[0])
        self.assertEqual(result["provenance"][0]["sha256"], self.sha256)
        for state in result["states"]:
            self.assertIsInstance(state["source_row"], int)
            self.assertGreater(state["source_row"], 0)


if __name__ == "__main__":
    unittest.main()
