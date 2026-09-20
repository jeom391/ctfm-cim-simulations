"""Shared contracts. The experiment JSON Schema is the v1.2.0 source of truth.

v1.1.0 requests are rejected with ``schema_migration_required`` rather than
reinterpreted: 1.2.0 made tile_size explicit with the ADC off and added
adc_order, so no automatic reading of an old request is both faithful and
complete. Results recorded under 1.1.0 keep their original meaning.
"""
