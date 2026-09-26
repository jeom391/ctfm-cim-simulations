"""Response models must accept the diagnostics the core really produces (list-of-layer mapping errors, dict ADC)."""
from ctfm_api.results import RunResult

LAYERS = [dict(layer='fc1', shape=[128, 784], scale=1.0, g_min_s=1e-6, g_max_s=4e-5, errors=dict(mae=1e-3, max_error=2e-2, rmse=3e-3)),
          dict(layer='fc2', shape=[10, 128], scale=1.0, g_min_s=1e-6, g_max_s=4e-5, errors=dict(mae=1e-3, max_error=2e-2, rmse=3e-3))]
ADC = dict(fc1=dict(count=10, clipped_count=0), fc2=dict(count=10, clipped_count=0))


def test_run_result_accepts_layer_list_mapping_diagnostics_and_both_names():
    run = RunResult.model_validate(dict(kind='ALL', status='succeeded', accuracy=0.96, mapping_errors=LAYERS, mapping_metrics=LAYERS, adc=ADC, adc_metrics=ADC))
    dumped = run.model_dump()
    assert dumped['mapping_metrics'] == dumped['mapping_errors'] == LAYERS
    assert dumped['adc_metrics'] == dumped['adc'] == ADC


def test_absent_diagnostics_stay_none_not_empty_success_values():
    run = RunResult.model_validate(dict(kind='D0', status='succeeded', accuracy=0.96, mapping_errors=None, adc=None))
    assert run.mapping_errors is None and run.adc is None and run.mapping_metrics is None and run.adc_metrics is None
