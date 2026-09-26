"""Measured (detrended Program) C2C reaching the simulation core: same numerical path as manual, distinct provenance.

Synthetic profile and mocked MNIST like test_simulation_experiment.py; the CV values here are fixtures, not measurements."""
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from test_simulation_experiment import c2c_configuration, configuration, synthetic_data, synthetic_profile

from ctfm.simulation import run_experiment
from ctfm.simulation.torch_runner import create_model

ANALYSIS_ID = '11111111-2222-4333-8444-555555555555'


def provenance(cv, analysis_id=ANALYSIS_ID):
    return dict(analysis_id=analysis_id, analysis_result_sha256='b' * 64, source_file_sha256='c' * 64, analysis_version='1.0.0',
                method='cubic_ols_detrended_relative_deviation', cycle_min=1, cycle_max=1000, cycle_count=1000,
                program_relative_std_percent=cv, unit='uA', condition_id='SYNTHETIC',
                measurement_conditions={'program_voltage_v': dict(value=10.0, confirmed=True)}, warnings=['not iid'])


def measured_config(p, cv=5.0, **kw):
    config = c2c_configuration(p, cv_percent=cv, **kw)
    config['schema_version'] = '1.4.0'
    config['profile_refs'][0]['c2c'] = dict(source='measured_detrended', analysis_id=ANALYSIS_ID, approved_assumption=True,
                                            cv_percent=cv, provenance=provenance(cv))
    return config


class MeasuredC2CTests(unittest.TestCase):
    def _run(self, config, p, directory, name='run'):
        with patch('ctfm.simulation.load_mnist', return_value=synthetic_data()), \
             patch('ctfm.simulation.train_model', return_value=(create_model(), [])):
            return run_experiment(config, [p], Path(directory) / name, cache_dir=Path(directory) / 'cache')

    def test_measured_source_is_pinned_in_results_records_and_assumptions(self):
        p = synthetic_profile()
        config = measured_config(p, cv=4.0, n_reprogram=2, arrays=1, d2d=False)
        with tempfile.TemporaryDirectory() as directory:
            r = self._run(config, p, directory)
            candidate = r['effective_config']['candidates'][0]['c2c']
            self.assertEqual(candidate['source'], 'measured_detrended')
            self.assertEqual(candidate['analysis_id'], ANALYSIS_ID)
            self.assertEqual(candidate['provenance']['analysis_result_sha256'], 'b' * 64)
            self.assertAlmostEqual(candidate['cv_ratio'], 0.04)
            ids = [a['id'] for a in r['assumptions']]
            self.assertIn('measured_detrended_c2c', ids)
            self.assertNotIn('manual_lognormal_c2c', ids)
            record = json.loads((Path(directory) / 'run' / 'candidate-1-array-0-record-0.json').read_text(encoding='utf-8'))
            self.assertEqual((record['source'], record['analysis_id']), ('measured_detrended', ANALYSIS_ID))
            self.assertEqual(r['requested_config']['profile_refs'][0]['c2c']['analysis_id'], ANALYSIS_ID)

    def test_measured_and_manual_with_the_same_number_use_the_same_numerical_path(self):
        p = synthetic_profile()
        manual = c2c_configuration(p, cv_percent=6.0, n_reprogram=2, arrays=1, d2d=False)
        measured = measured_config(p, cv=6.0, n_reprogram=2, arrays=1, d2d=False)
        with tempfile.TemporaryDirectory() as directory:
            a = self._run(manual, p, directory, 'manual')
            b = self._run(measured, p, directory, 'measured')
            runs_a = [x for x in a['runs'] if x['kind'] == 'ALL']
            runs_b = [x for x in b['runs'] if x['kind'] == 'ALL']
            self.assertEqual([x['c2c_diagnostics'] for x in runs_a], [x['c2c_diagnostics'] for x in runs_b])
            self.assertEqual([x['accuracy'] for x in runs_a], [x['accuracy'] for x in runs_b])
            self.assertIn('manual_lognormal_c2c', [x['id'] for x in a['assumptions']])
            self.assertNotIn('measured_detrended_c2c', [x['id'] for x in a['assumptions']])

    def test_off_zero_and_measured_are_distinguishable_and_zero_measured_equals_off(self):
        p = synthetic_profile()
        with tempfile.TemporaryDirectory() as directory:
            off = self._run(configuration(p, False), p, directory, 'off')
            zero = self._run(measured_config(p, cv=0.0, n_reprogram=2, arrays=1, d2d=False), p, directory, 'zero')
            big = self._run(measured_config(p, cv=30.0, n_reprogram=2, arrays=1, d2d=False), p, directory, 'big')
            base = [x for x in off['runs'] if x['kind'] == 'ALL'][0]['accuracy']
            for x in (x for x in zero['runs'] if x['kind'] == 'ALL'):
                self.assertEqual(x['accuracy'], base)
            self.assertIsNone(off['effective_config']['candidates'][0]['c2c'])
            self.assertEqual(zero['effective_config']['candidates'][0]['c2c']['source'], 'measured_detrended')
            factors = [x['c2c_diagnostics'] for x in big['runs'] if x['kind'] == 'ALL']
            self.assertTrue(all(v['factor_std'] > 0 for d in factors for v in d.values()))

    def test_measured_ref_is_rejected_unless_it_is_a_consistent_server_pin(self):
        p = synthetic_profile()
        good = measured_config(p, cv=5.0, n_reprogram=1, arrays=1, d2d=False)
        cases = {}
        c = deepcopy(good); c['schema_version'] = '1.3.0'; cases['requires 1.4.0'] = (c, 'requires schema_version 1.4.0')
        c = deepcopy(good); c['profile_refs'][0]['c2c']['approved_assumption'] = False; cases['approval'] = (c, 'explicit user approval')
        c = deepcopy(good); del c['profile_refs'][0]['c2c']['provenance']; cases['provenance'] = (c, 'server-resolved analysis provenance')
        c = deepcopy(good); c['profile_refs'][0]['c2c']['provenance'].pop('analysis_result_sha256'); cases['pin hash'] = (c, 'server-resolved analysis provenance')
        c = deepcopy(good); c['profile_refs'][0]['c2c']['cv_percent'] = 9.0; cases['cv mismatch'] = (c, 'does not equal the pinned')
        c = deepcopy(good); c['profile_refs'][0]['c2c']['analysis_id'] = '99999999-2222-4333-8444-555555555555'; cases['id mismatch'] = (c, 'differs from the reference')
        c = deepcopy(good); c['profile_refs'][0]['c2c']['source'] = 'measured'; cases['unknown source'] = (c, 'manual_assumption or measured_detrended')
        for name, (config, message) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, message):
                with patch('ctfm.simulation.load_mnist', side_effect=AssertionError('must fail before data download')):
                    run_experiment(config, [p], Path(tempfile.mkdtemp()) / 'x', cache_dir=Path(tempfile.mkdtemp()))

    def test_manual_1_3_0_requests_keep_their_exact_meaning(self):
        p = synthetic_profile()
        with tempfile.TemporaryDirectory() as directory:
            r = self._run(c2c_configuration(p, cv_percent=5, n_reprogram=2, arrays=1, d2d=False), p, directory)
            candidate = r['effective_config']['candidates'][0]['c2c']
            self.assertEqual(set(candidate), {'cv_percent', 'cv_ratio', 'source'})
            self.assertEqual(candidate['source'], 'manual_assumption')
            self.assertEqual(r['schema_version'], '1.3.0')


if __name__ == '__main__':
    unittest.main()


class DiagnosticNameTests(unittest.TestCase):
    """mapping_metrics/adc_metrics are the official names; the legacy aliases carry identical content and nothing is invented."""

    def test_official_names_mirror_legacy_and_absent_diagnostics_stay_absent(self):
        p = synthetic_profile()
        with tempfile.TemporaryDirectory() as directory:
            with patch('ctfm.simulation.load_mnist', return_value=synthetic_data()), \
                 patch('ctfm.simulation.train_model', return_value=(create_model(), [])):
                off = run_experiment(configuration(p, False), [p], Path(directory) / 'a', cache_dir=Path(directory) / 'cache')
                on = run_experiment(configuration(p, True), [p], Path(directory) / 'b', cache_dir=Path(directory) / 'cache')
            for run in off['runs']:
                if run.get('mapping_errors') is not None:
                    self.assertEqual(run['mapping_metrics'], run['mapping_errors'])
                else:
                    self.assertNotIn('mapping_metrics', run)
                self.assertNotIn('adc_metrics', run)  # ADC off produced no diagnostics: no empty success value
            with_adc = [r for r in on['runs'] if r.get('adc') is not None]
            self.assertTrue(with_adc)
            for run in with_adc:
                self.assertEqual(run['adc_metrics'], run['adc'])
