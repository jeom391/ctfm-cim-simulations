"""Optional ideal AIHWKit support, gated by a real float32 parity probe."""
from functools import lru_cache
from importlib.metadata import version, PackageNotFoundError


def _neurosim_capability():
    """Report the engine build separately from the CTFM preset decision.

    ``available`` stays False while no validated CTFM equivalent-circuit preset
    exists, but a built binary is still reported, so "the engine is missing" and
    "the preset is missing" are never confused for one another.
    """
    from ctfm.adapters.neurosim import engine_status
    status = engine_status()
    reason = 'No validated CTFM equivalent-circuit preset; first-release PPA is off'
    # Carried in reason rather than a new field, so the published Capability
    # contract is unchanged while the two causes stay distinguishable.
    reason += ('. Engine binary built at commit ' + str(status['commit'])
               if status['available'] else '. Engine not built: ' + str(status['reason']))
    return {'available': False, 'version': None, 'reason': reason}


@lru_cache(maxsize=1)
def engine_capabilities():
    result = {'torch_reference': {'available': False, 'version': None, 'reason': None},
              'aihwkit_ideal': {'available': False, 'version': None, 'reason': None},
              'neurosim': _neurosim_capability()}
    try:
        import torch
        result['torch_reference'].update(available=True, version=str(torch.__version__))
    except (ImportError, OSError) as exc:
        result['torch_reference']['reason'] = 'PyTorch could not load ('+type(exc).__name__+')'
        result['aihwkit_ideal']['reason'] = 'PyTorch unavailable'
        return result
    try:
        from aihwkit.nn import AnalogLinear
        from aihwkit.simulator.configs import FloatingPointRPUConfig
        result['aihwkit_ideal']['version'] = version('aihwkit')
        x = torch.tensor([[0., .2, 1., -.5], [1., -1., .7, .1]], dtype=torch.float32)
        w = torch.tensor([[.1,-.2,.3,.7],[-.3,.8,.1,-.4],[.2,.1,-.5,.9]], dtype=torch.float32)
        layer = AnalogLinear(4, 3, bias=False, rpu_config=FloatingPointRPUConfig())
        layer.set_weights(w); layer.eval()
        with torch.no_grad(): actual = layer(x)
        expected = torch.nn.functional.linear(x, w)
        if not torch.allclose(actual, expected, atol=1e-5, rtol=1e-4):
            raise RuntimeError('AIHWKit ideal float32 logits parity failed')
        result['aihwkit_ideal'].update(available=True, reason=None,
            parity={'atol':1e-5, 'rtol':1e-4, 'max_abs_error':float((actual-expected).abs().max()), 'fixture':'fixed_cpu_float32_2x4x3'},
            config='FloatingPointRPUConfig; project row-tile/bipolar ADC wrapper; digital bias')
    except (ImportError, OSError, RuntimeError, PackageNotFoundError, AttributeError, TypeError) as exc:
        result['aihwkit_ideal']['reason'] = 'AIHWKit import or ideal parity probe failed ('+type(exc).__name__+')'
    return result


def make_linear(weight, engine):
    """Bind one finite restored weight block; no programming noise/converter."""
    import torch
    if engine == 'torch_reference':
        return lambda x: torch.nn.functional.linear(x, weight)
    if engine != 'aihwkit_ideal' or not engine_capabilities()['aihwkit_ideal']['available']:
        raise ValueError('Requested accuracy engine is unavailable')
    from aihwkit.nn import AnalogLinear
    from aihwkit.simulator.configs import FloatingPointRPUConfig
    layer = AnalogLinear(weight.shape[1], weight.shape[0], bias=False, rpu_config=FloatingPointRPUConfig())
    layer.set_weights(weight.detach().clone()); layer.eval()
    # Inference-only binding: AnalogLinear keeps its tile weights as grad-requiring
    # parameters, so without this every caller outside inference_mode would get a
    # grad-tracking output where torch_reference returns a plain tensor.
    for parameter in layer.parameters(): parameter.requires_grad_(False)
    return layer
