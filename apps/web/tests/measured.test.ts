// Measured C2C, explicit IV/Retention layout selections and measured C2C experiment references.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildExperiment, buildAnalysis, suggestRetentionColumns, ivAmplitudeV} from '../src/lib/payload.ts';

const caps = {engines: {torch_reference: {available: true}}, effects: {adc: {available: true}}, hardware: {adc_orders: ['subtract_then_adc', 'adc_then_subtract'], validated_combinations: [{tile_size: 64, adc_bits: 6, adc_order: 'subtract_then_adc'}]}};
const base = {profileKeys: [], pools: ['combined'], mappings: ['fixed_reference'], d2d: false, retention: false, adc: false, c2c: false, nReprogram: 1, c2cCv: {}, arrays: 1, years: '0', seed: 20260917, tileSize: 64, adcBits: 6, adcOrder: 'subtract_then_adc', engine: 'torch_reference', checkpoint: ''};

const c2cDataset = {file_id: 'f', sheet: 'Origin_data', column_mapping: {}, units: {}, device_id: 'dev-A', condition_id: 'A3', confirmed: true, row_start: '', row_end: '', conditions: {}};
const c2c = (conditions, extra = {}) => buildAnalysis({kind: 'c2c_detrended', datasets: [{...c2cDataset, conditions, ...extra}], settings: {}});

test('measured C2C sends only stated conditions, keeps signs and zero, and never invents the missing ones', () => {
  const r = c2c({program_voltage_v: '10', erase_voltage_v: '-10', read_voltage_v: '0', program_pulse_width_s: '0.01', read_terminal_meaning: ' gate ', vds_v: ''});
  assert.deepEqual(r.inputs[0].measurement_conditions, {program_voltage_v: 10, erase_voltage_v: -10, read_voltage_v: 0, program_pulse_width_s: 0.01, read_terminal_meaning: 'gate'});
  assert.equal(r.inputs[0].sheet, 'Origin_data');
  assert.equal('column_mapping' in r.inputs[0], false);
  assert.deepEqual(r.settings, {});
  assert.deepEqual(c2c({}).inputs[0].measurement_conditions, {});
});

test('measured C2C refuses non-numeric, non-finite and non-positive conditions and needs confirmation and ids', () => {
  for (const bad of [{vds_v: 'abc'}, {program_voltage_v: 'Infinity'}, {read_time_s: '0'}, {erase_pulse_width_s: '-1'}]) assert.throws(() => c2c(bad));
  assert.throws(() => c2c({}, {confirmed: false}));
  assert.throws(() => c2c({}, {device_id: ' '}));
  assert.throws(() => c2c({}, {condition_id: ''}));
  assert.throws(() => buildAnalysis({kind: 'c2c_detrended', datasets: [c2cDataset, c2cDataset], settings: {}}));
});

const segment = (index, direction, start, end, points) => ({index, direction, points, source_row_start: 2, source_row_end: 1 + points, vg_start: start, vg_end: end});
const ivLayout = {file_id: 'f', sheet: 'Sheet', sheets: ['Sheet'], block_count: 2, blocks: [
  {index: 0, columns: [0, 1, 2], status: 'invalid', error: 'block 0 Vg row 4: a finite number is required'},
  {index: 1, columns: [3, 4, 5], status: 'ok', points: 501, proposed_amplitude_v: 15, segments: [segment(0, 'decreasing', 0, -15, 101), segment(1, 'increasing', -15, 15, 201), segment(2, 'decreasing', 15, -15, 201)]}]};
const ivBlock = {file_id: 'f', sheet: 'Sheet', filename: 'iv.xlsx', column_mapping: {}, units: {vgs_v: 'V', id_a: 'A'}, device_id: 'd1', condition_id: 'A3', branch: 'erase', sweep_amplitude_v: 15, confirmed: true, row_start: '', row_end: '', layoutKind: 'iv_block', ivLayout, block: '1', segment: '1'};

test('an IV block selection is explicit: block, segment, branch and amplitude all reach the request', () => {
  for (const kind of ['iv', 'd2d']) {
    const r = buildAnalysis({kind, datasets: [ivBlock], settings: {}});
    assert.deepEqual(r.inputs[0].selection, {type: 'iv_block', block: 1, segment: 1});
    assert.equal(r.inputs[0].branch, 'erase');
    assert.equal(r.inputs[0].sweep_amplitude_v, 15);
    assert.deepEqual(r.inputs[0].units, {vgs_v: 'V', id_a: 'A'});
    assert.equal('column_mapping' in r.inputs[0], false);
    assert.equal('row_start' in r.inputs[0], false);
  }
  const program = buildAnalysis({kind: 'iv', datasets: [{...ivBlock, branch: 'program', segment: '2'}], settings: {}});
  assert.equal(program.inputs[0].selection.segment, 2);
});

test('IV block selections never guess: damaged block, wrong direction, wrong amplitude and missing choices are refused', () => {
  for (const patch of [{block: '0'}, {block: ''}, {segment: ''}, {segment: '9'}, {branch: 'program'}, {branch: ''}, {segment: '0'}, {sweep_amplitude_v: 14}, {sweep_amplitude_v: ''}, {units: {vgs_v: 'V'}}, {row_start: '2'}, {sheet: null}])
    assert.throws(() => buildAnalysis({kind: 'iv', datasets: [{...ivBlock, ...patch}], settings: {}}), undefined, JSON.stringify(patch));
  assert.throws(() => buildAnalysis({kind: 'pulse_states', datasets: [{...ivBlock, direction: 'ltp'}], settings: {}}));
  assert.throws(() => buildAnalysis({kind: 'retention', datasets: [ivBlock], settings: {}}));
});

const retentionLayout = {file_id: 'r', sheet: 'Raw Data', sheets: ['Raw Data', 'Normalized Data'], columns: [0, 1, 2, 3].map(i => ({index: i, header: 'c' + i, non_empty: 100, first: [1]})), embedded_source_headers: []};
const ret = {file_id: 'r', sheet: 'Raw Data', filename: 'ret.xlsx', column_mapping: {}, units: {erase_time_s: 's', program_time_s: 's', erase_id_a: 'A', program_id_a: 'A'}, device_id: 'd', condition_id: 'A1', source_label: 'R1', read_vgs_v: 0, vds_v: 0.1, confirmed: true, row_start: '', row_end: '', layoutKind: 'retention_columns', retentionLayout, retentionColumns: {erase_time_s: '0', erase_id_a: '1', program_time_s: '2', program_id_a: '3'}};

test('retention column selection keeps two independent time axes and the explicit source label', () => {
  const r = buildAnalysis({kind: 'retention', datasets: [ret], settings: {}});
  assert.deepEqual(r.inputs[0].selection, {type: 'retention_columns', columns: {erase_time_s: 0, erase_id_a: 1, program_time_s: 2, program_id_a: 3}});
  assert.equal(r.inputs[0].source_label, 'R1');
  assert.equal(r.inputs[0].sheet, 'Raw Data');
  assert.equal(r.inputs[0].units.program_time_s, 's');
  for (const patch of [{retentionColumns: {erase_time_s: '0', erase_id_a: '1', program_time_s: '2'}}, {retentionColumns: {erase_time_s: '0', erase_id_a: '1', program_time_s: '1', program_id_a: '3'}}, {source_label: ''}, {vds_v: ''}, {read_vgs_v: ''}, {units: {erase_time_s: 's'}}, {sheet: null}, {row_end: '5'}])
    assert.throws(() => buildAnalysis({kind: 'retention', datasets: [{...ret, ...patch}], settings: {}}), undefined, JSON.stringify(patch));
});

test('retention columns are suggested only when the header identifies exactly one column', () => {
  assert.deepEqual(suggestRetentionColumns(['Erase_-15V_time', 'Erase_-15V_전류', 'Programing_15V_time', 'Programing_15V_전류']), {erase_time_s: '0', erase_id_a: '1', program_time_s: '2', program_id_a: '3'});
  assert.deepEqual(suggestRetentionColumns(['Erase_-15V_time', 'Erase_-15V_전류 ', 'Programing_15V', 'Programing_15V']), {erase_time_s: '0', erase_id_a: '1'});
  assert.deepEqual(suggestRetentionColumns(['a', 'b', 'c', 'd']), {});
});

const published = (id, condition) => ({profile_id: id, revision: 1, status: 'published', condition_id: condition, display_name: condition, d2d: {status: 'unavailable'}, retention: {status: 'unavailable'}});
const A1 = published('a133d601-5313-4598-979f-9bfac834912f', 'A1');
const A3 = published('c133d601-5313-4598-979f-9bfac834912f', 'A3');
const analysis = {analysis_id: '11111111-2222-4333-8444-555555555555', kind: 'c2c_detrended', status: 'succeeded', condition_id: 'A3',
  program: {status: 'ok', primary: {relative_residual_std_percent: 0.0477667, residual_lag1_correlation: 0.615}, degree4_vs_degree3_change_percent: -1.1, raw_statistics: {relative_std_percent: 2.4}},
  erase: {status: 'ok', primary: {relative_residual_std_percent: 0.0518, residual_lag1_correlation: 0.745}, degree4_vs_degree3_change_percent: -17, raw_statistics: {relative_std_percent: 1.6}}};
const k3 = A3.profile_id + ':1';
const k1 = A1.profile_id + ':1';
const mform = over => ({...base, profileKeys: [k3], c2c: true, nReprogram: 2, c2cSource: {[k3]: 'measured'}, c2cAnalysis: {[k3]: analysis.analysis_id}, c2cApproved: {[k3]: true}, c2cCross: {}, ...over});

test('a measured C2C reference names the analysis and approval only: schema 1.4.0 and no client-supplied number', () => {
  const r = buildExperiment(mform(), [A3], caps, [analysis]);
  assert.equal(r.schema_version, '1.4.0');
  assert.equal(r.effects.c2c, true);
  assert.equal(r.n_reprogram, 2);
  assert.deepEqual(r.profile_refs[0].c2c, {source: 'measured_detrended', analysis_id: analysis.analysis_id, approved_assumption: true});
  assert.equal('cv_percent' in r.profile_refs[0].c2c, false);
  assert.equal('provenance' in r.profile_refs[0].c2c, false);
});

test('measured C2C needs a succeeded usable analysis and the explicit approval, and cross-condition use is acknowledged', () => {
  assert.throws(() => buildExperiment(mform({c2cApproved: {}}), [A3], caps, [analysis]));
  assert.throws(() => buildExperiment(mform({c2cAnalysis: {}}), [A3], caps, [analysis]));
  assert.throws(() => buildExperiment(mform(), [A3], caps, []));
  assert.throws(() => buildExperiment(mform(), [A3], caps, [{...analysis, status: 'running'}]));
  assert.throws(() => buildExperiment(mform(), [A3], caps, [{...analysis, kind: 'pulse_states'}]));
  assert.throws(() => buildExperiment(mform(), [A3], caps, [{...analysis, program: {...analysis.program, status: 'blocked'}}]));
  const onA1 = {profileKeys: [k1], c2cSource: {[k1]: 'measured'}, c2cAnalysis: {[k1]: analysis.analysis_id}, c2cApproved: {[k1]: true}, c2cCross: {}};
  assert.throws(() => buildExperiment(mform(onA1), [A1], caps, [analysis]), /다릅니다/);
  const acknowledged = buildExperiment(mform({...onA1, c2cCross: {[k1]: true}}), [A1], caps, [analysis]);
  assert.deepEqual(acknowledged.profile_refs[0].c2c, {source: 'measured_detrended', analysis_id: analysis.analysis_id, approved_assumption: true, cross_condition_acknowledged: true});
});

test('manual and measured references stay separate per profile revision, and manual-only requests stay 1.3.0', () => {
  const mixed = buildExperiment(mform({profileKeys: [k1, k3], c2cSource: {[k1]: 'manual', [k3]: 'measured'}, c2cCv: {[k1]: '5'}}), [A1, A3], caps, [analysis]);
  assert.equal(mixed.schema_version, '1.4.0');
  assert.deepEqual(mixed.profile_refs[0].c2c, {cv_percent: 5, source: 'manual_assumption'});
  assert.equal(mixed.profile_refs[1].c2c.source, 'measured_detrended');
  assert.throws(() => buildExperiment(mform({profileKeys: [k1, k3], c2cSource: {[k1]: 'manual', [k3]: 'measured'}, c2cCv: {}}), [A1, A3], caps, [analysis]));
  const manual = buildExperiment({...base, profileKeys: [k1], c2c: true, nReprogram: 2, c2cCv: {[k1]: '5'}}, [A1], caps, [analysis]);
  assert.equal(manual.schema_version, '1.3.0');
  assert.deepEqual(manual.profile_refs[0].c2c, {cv_percent: 5, source: 'manual_assumption'});
  const off = buildExperiment({...mform(), c2c: false, nReprogram: 1}, [A3], caps, [analysis]);
  assert.equal(off.schema_version, '1.2.0');
  assert.equal('c2c' in off.profile_refs[0], false);
});


test('IV millivolt block amplitude is converted to volts before request validation', () => {
  const layout = {...ivLayout, blocks: ivLayout.blocks.map(b => b.status === 'ok' ? {...b, proposed_amplitude_v: 15000} : b)};
  const d = {...ivBlock, ivLayout: layout, units: {vgs_v:'mV',id_a:'A'}, sweep_amplitude_v:ivAmplitudeV(15000,'mV')};
  assert.equal(d.sweep_amplitude_v,15);
  assert.equal(buildAnalysis({kind:'iv',datasets:[d],settings:{}}).inputs[0].sweep_amplitude_v,15);
  assert.throws(() => buildAnalysis({kind:'iv',datasets:[{...d,sweep_amplitude_v:15000}],settings:{}}));
});
