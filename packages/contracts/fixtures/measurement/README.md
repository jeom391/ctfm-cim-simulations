# Synthetic measurements

These hand-constructed CSV files are software test fixtures, not CTFM measurements.
The first row is an explicit synthetic label; source data starts at row 3.
Pulse candidates use absolute currents at 6 s or later, with the j-2 read rule.
No claim about measured device accuracy or physical saturation follows from them.

Run the complete local HTTP smoke after starting the API and worker:
`uv run python scripts/smoke_workflow.py`.
