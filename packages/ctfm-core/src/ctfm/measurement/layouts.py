"""Readers for the two instrument-export layouts that ``parse_table`` deliberately refuses.

* IV sweep sheets: one sheet holding several repeated ``Vg, Id, Ig`` triplets (one triplet per sweep amplitude).
* Retention sheets: Erase and Program columns with independent time axes.

Nothing here guesses a selection. A caller names the block and segment (IV) or the four columns (retention);
the readers only make the structure visible and turn an explicit choice into datasets for ``analyze``.
"""
from __future__ import annotations

import math
import re

from . import _load_raw

IV_TRIPLET = ('Vg', 'Id', 'Ig')
RETENTION_ROLES = ('erase_time_s', 'erase_id_a', 'program_time_s', 'program_id_a')


def _finite(value, label):
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        raise ValueError(f'{label}: a finite number is required')
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label}: a finite number is required') from exc
    if not math.isfinite(number):
        raise ValueError(f'{label}: a finite number is required')
    return number


def _header_cells(row):
    cells = [None if v is None else str(v).strip() for v in row]
    while cells and not cells[-1]:
        cells.pop()
    return cells


def _select_sheet(data, filename, sheet):
    raw, sheets, warnings, selected = _load_raw(data, filename, sheet)
    if not raw:
        raise ValueError('Select a worksheet explicitly: ' + ', '.join(sheets))
    return raw, sheets, warnings, selected


def _segments(vg, first_source_row):
    """Monotone runs of the gate voltage; a turning row belongs to both neighbours."""
    segments, start, direction = [], 0, 0
    for i in range(1, len(vg)):
        step = (vg[i] > vg[i - 1]) - (vg[i] < vg[i - 1])
        if step and direction and step != direction:
            segments.append((start, i - 1, direction))
            start = i - 1
        if step:
            direction = step
    segments.append((start, len(vg) - 1, direction))
    return [dict(index=k, direction='increasing' if d > 0 else 'decreasing', start_offset=a, end_offset=b, points=b - a + 1,
                 source_row_start=first_source_row + a, source_row_end=first_source_row + b, vg_start=vg[a], vg_end=vg[b])
            for k, (a, b, d) in enumerate(segments)]


def _iv_columns(raw):
    """Split the header into blocks: every complete ``Vg, Id, Ig`` triplet is a block; a run of cells that does not form
    one (a header or column that is missing) becomes an unusable block with its exact columns and reason.

    Nothing is re-aligned or reconstructed: an orphan block's missing column is not inferred from its neighbours."""
    header = _header_cells(raw[0])
    blocks, i = [], 0
    while i < len(header):
        if tuple(header[i:i + 3]) == IV_TRIPLET:
            blocks.append(dict(columns=[i, i + 1, i + 2], error=None))
            i += 3
            continue
        j = i
        while j < len(header) and tuple(header[j:j + 3]) != IV_TRIPLET:
            j += 1
        cols = list(range(i, j))
        blocks.append(dict(columns=cols, error='columns C%d-C%d are labelled %s, which is not a Vg/Id/Ig triplet; the block '
                           'cannot be read without guessing which column is the gate voltage'
                           % (cols[0], cols[-1], [header[c] for c in cols])))
        i = j
    if not any(b['error'] is None for b in blocks):
        raise ValueError('Not a repeated Vg/Id/Ig block layout: ' + str(header[:6]))
    return blocks


def _block_series(raw, columns, label):
    vg, idd, ig, ended = [], [], [], False
    for offset, row in enumerate(raw[1:]):
        cells = [row[c] if len(row) > c else None for c in columns]
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in cells):
            ended = True
            continue
        if ended:
            raise ValueError(f'Block {label}: data resumes after a blank row at sheet row {offset + 2}')
        n = offset + 2
        vg.append(_finite(cells[0], f'block {label} Vg row {n}'))
        idd.append(_finite(cells[1], f'block {label} Id row {n}'))
        ig.append(_finite(cells[2], f'block {label} Ig row {n}'))
    if len(vg) < 2:
        raise ValueError(f'Block {label} has fewer than two samples')
    return vg, idd, ig


def read_iv_blocks(data: bytes, filename: str, sheet: str | None = None) -> dict:
    """Describe every Vg/Id/Ig block and its monotone Vg segments (no selection is made)."""
    raw, sheets, warnings, selected = _select_sheet(data, filename, sheet)
    split = _iv_columns(raw)
    count = len(split)
    blocks = []
    for block, entry in enumerate(split):
        columns = entry['columns']
        if entry['error']:
            blocks.append(dict(index=block, columns=columns, status='invalid', error=entry['error']))
            continue
        try:
            vg, idd, _ig = _block_series(raw, columns, block)
        except ValueError as exc:  # one damaged block must not hide the intact ones
            blocks.append(dict(index=block, columns=columns, status='invalid', error=str(exc)))
            continue
        blocks.append(dict(index=block, columns=columns, status='ok', points=len(vg),
                           source_row_first=2, source_row_last=1 + len(vg), vg_min=min(vg), vg_max=max(vg),
                           id_min=min(idd), id_max=max(idd), proposed_amplitude_v=max(abs(v) for v in vg),
                           segments=_segments(vg, 2)))
    return dict(sheet=selected, sheets=sheets, header=list(IV_TRIPLET), block_count=count, blocks=blocks, warnings=warnings)


def iv_dataset(data: bytes, filename: str, *, block: int, segment: int, branch: str, sweep_amplitude_v: float,
               device_id: str, condition_id: str, file_id: str, sha256: str, sheet: str | None = None,
               units: dict, vds_v: float = 0.1, read_vgs_v: float = 0.0) -> dict:
    """Turn an explicit (block, segment) choice into one dataset for ``analyze('iv'|'d2d', ...)``.

    branch must agree with the segment direction (increasing = erase, decreasing = program) and the stated sweep
    amplitude must match the block's largest |Vg|; both are refused rather than corrected."""
    layout = read_iv_blocks(data, filename, sheet)
    if not 0 <= block < layout['block_count']:
        raise ValueError(f'block must be in 0..{layout["block_count"] - 1}')
    info = layout['blocks'][block]
    if info['status'] != 'ok':
        raise ValueError(f'block {block} is not usable: {info["error"]}')
    if not 0 <= segment < len(info['segments']):
        raise ValueError(f'segment must be in 0..{len(info["segments"]) - 1} for block {block}')
    seg = info['segments'][segment]
    expected = 'increasing' if branch == 'erase' else 'decreasing' if branch == 'program' else None
    if expected is None or seg['direction'] != expected:
        raise ValueError(f'branch {branch!r} needs a {expected or "program/erase"} segment; segment {segment} is {seg["direction"]}')
    if not math.isclose(float(sweep_amplitude_v), info['proposed_amplitude_v'], abs_tol=1e-9):
        raise ValueError(f'sweep_amplitude_v {sweep_amplitude_v} does not match block {block} (max |Vg| = {info["proposed_amplitude_v"]})')
    raw = _select_sheet(data, filename, sheet)[0]
    vg, idd, _ig = _block_series(raw, info['columns'], block)
    lo, hi = seg['start_offset'], seg['end_offset']
    labels = dict(vgs_v=f'Vg[block {block}]', id_a=f'Id[block {block}]')
    rows = [{labels['vgs_v']: vg[i], labels['id_a']: idd[i]} for i in range(lo, hi + 1)]
    return dict(file_id=file_id, sha256=sha256, filename=filename, sheet=layout['sheet'], device_id=device_id,
                condition_id=condition_id, branch=branch, sweep_amplitude_v=float(sweep_amplitude_v), vds_v=vds_v, read_vgs_v=read_vgs_v,
                column_mapping=labels, units=dict(units), rows=rows,
                source_rows=[seg['source_row_start'] + k for k in range(hi - lo + 1)],
                block=dict(index=block, segment=segment, columns=info['columns']))


# ---------------------------------------------------------------- retention

_BIAS = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s*V', re.I)
_PAREN = re.compile(r'\((\d+)\)')


def read_retention_layout(data: bytes, filename: str, sheet: str = 'Raw Data') -> dict:
    """Show the raw sheet columns (header text, first values) and any source names embedded elsewhere in the workbook.

    Embedded names (the ``Normalized Data`` headers) are provenance evidence only; they never select or exclude."""
    raw, sheets, warnings, selected = _select_sheet(data, filename, sheet)
    header = [None if v is None else str(v) for v in raw[0]]
    columns = []
    for c, label in enumerate(header):
        values = [row[c] for row in raw[1:] if len(row) > c and row[c] is not None]
        columns.append(dict(index=c, header=label, non_empty=len(values), first=values[:3]))
    evidence = []
    for other in sheets:
        if other == selected:
            continue
        other_raw = _select_sheet(data, filename, other)[0]
        for cell in other_raw[0]:
            if isinstance(cell, str) and re.search(r'\.csv|retention', cell, re.I):
                evidence.append(dict(sheet=other, header=cell, read_bias_v=[float(b) for b in _BIAS.findall(cell)[:1]],
                                     embedded_numbers=[int(n) for n in _PAREN.findall(cell)]))
    return dict(sheet=selected, sheets=sheets, columns=columns, embedded_source_headers=evidence, warnings=warnings)


def retention_dataset(data: bytes, filename: str, *, columns: dict, condition_id: str, device_id: str, file_id: str,
                      sha256: str, source_label: str, sheet: str = 'Raw Data', units: dict,
                      read_vgs_v: float | None = None, header_read_vgs_v: float | None = None, vds_v: float = 0.1) -> dict:
    """Explicit four-column selection (0-based indices for erase_time_s, erase_id_a, program_time_s, program_id_a).

    Rows that are entirely empty are skipped and reported; a partly empty row is an error. Row alignment is the sheet
    row: erase and program keep their own time values."""
    if set(columns) != set(RETENTION_ROLES) or len(set(columns.values())) != 4:
        raise ValueError('columns must map each of ' + ', '.join(RETENTION_ROLES) + ' to a distinct column index')
    raw = _select_sheet(data, filename, sheet)[0]
    rows, source_rows, skipped = [], [], []
    for offset, row in enumerate(raw[1:]):
        n = offset + 2
        cells = {role: (row[idx] if len(row) > idx else None) for role, idx in columns.items()}
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in cells.values()):
            skipped.append(n)
            continue
        rows.append({role: _finite(v, f'{filename} row {n} {role}') for role, v in cells.items()})
        source_rows.append(n)
    if not rows:
        raise ValueError('No data rows found in the selected columns')
    return dict(file_id=file_id, sha256=sha256, filename=filename, sheet=sheet, device_id=device_id, condition_id=condition_id,
                source_label=source_label, current_basis='raw', vds_v=vds_v,
                read_vgs_v=read_vgs_v, header_read_vgs_v=header_read_vgs_v,
                time_axes='per_direction', column_mapping={r: r for r in RETENTION_ROLES}, units=dict(units),
                rows=rows, source_rows=source_rows, skipped_blank_rows=skipped,
                selected_columns={r: dict(index=i, header=None if i >= len(raw[0]) or raw[0][i] is None else str(raw[0][i]))
                                  for r, i in columns.items()})
