"""Finite measured-state mapping and explicitly defined numerical effects."""
import hashlib
import json
import math
import numpy as np


def map_weights(weights, states, method='fixed_reference'):
    """Map output-by-input weights to measured states, preserving source order ties."""
    w = np.asarray(weights, dtype=np.float64)
    gs = np.asarray([s['conductance_s'] for s in states], dtype=np.float64)
    if not np.isfinite(w).all() or not np.isfinite(gs).all() or np.any(gs <= 0):
        raise ValueError('Weights must be finite and measured conductances positive finite')
    if len(np.unique(gs)) < 2:
        raise ValueError('Pool requires two distinct measured conductances')
    if method not in ('fixed_reference', 'pair_search'):
        raise ValueError('Unsupported mapping')
    low = int(np.argmin(gs)); high = float(np.max(gs)); span = high - float(gs[low])
    peak = float(np.max(np.abs(w))); scale = peak / span
    plus = np.full(w.shape, low, dtype=np.int64); minus = plus.copy()
    if peak:
        target = np.abs(w) / scale
        if method == 'fixed_reference':
            order = np.argsort(gs, kind='stable')
            values, first = np.unique(gs[order], return_index=True)
            ids = order[first]; desired = gs[low] + target
            right = np.clip(np.searchsorted(values, desired), 0, len(values)-1)
            left = np.maximum(right-1, 0)
            pick = np.where(np.abs(values[left]-desired) <= np.abs(values[right]-desired), left, right)
            plus = ids[pick]
        else:
            # At most 512 measured states in the prescribed pulse acquisition.
            # ponytail: enumerate finite pairs; replace with bounded search for much larger pools.
            pi, ni = np.where(gs[:, None] >= gs[None, :])
            diffs = gs[pi] - gs[ni]; sums = gs[pi] + gs[ni]
            order = np.lexsort((ni, pi, sums, diffs))
            diffs, first = np.unique(diffs[order], return_index=True)
            best = order[first]; pi = pi[best]; ni = ni[best]; sums = sums[best]
            right = np.clip(np.searchsorted(diffs, target), 0, len(diffs)-1)
            left = np.maximum(right-1, 0)
            le = np.abs(diffs[left]-target); re = np.abs(diffs[right]-target)
            tied = le == re
            earlier = (pi[left] < pi[right]) | ((pi[left] == pi[right]) & (ni[left] <= ni[right]))
            choose_left = (le < re) | (tied & ((sums[left] < sums[right]) | ((sums[left] == sums[right]) & earlier)))
            pick = np.where(choose_left, left, right)
            plus = pi[pick]; minus = ni[pick]
        plus, minus = np.where(w < 0, minus, plus), np.where(w < 0, plus, minus)
        plus = np.where(w == 0, low, plus); minus = np.where(w == 0, low, minus)
    gp = gs[plus]; gm = gs[minus]; restored = scale*(gp-gm); error = restored-w
    return dict(g_plus=gp, g_minus=gm, plus_index=plus, minus_index=minus,
                scale=scale, weights=restored, states=states, g_min_s=float(gs[low]), g_max_s=high,
                errors=dict(mae=float(np.mean(np.abs(error))), rmse=float(np.sqrt(np.mean(error**2))), max_error=float(np.max(np.abs(error)))))


def d2d_factors(shape, cv, root_seed, profile_hash, array_index, layer_name, polarity):
    if cv is None or not math.isfinite(cv) or cv < 0:
        raise ValueError('D2D requires a finite nonnegative measured CV; null is unavailable')
    key = [root_seed, profile_hash, array_index, layer_name, polarity]
    encoded = json.dumps(key, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    seed = int.from_bytes(hashlib.sha256(encoded).digest()[:8], 'big')
    sigma = np.sqrt(np.log(1+cv*cv))
    if not np.isfinite(sigma):
        raise ValueError('D2D CV is too large for a finite lognormal distribution')
    z = np.random.Generator(np.random.PCG64(seed)).standard_normal(shape)
    factors = np.exp(-sigma*sigma/2 + sigma*z)
    if not np.isfinite(factors).all() or np.any(factors <= 0):
        raise ValueError('D2D realization produced nonpositive or nonfinite factors')
    return factors, dict(seed_key=key, seed=seed, generator='PCG64', numpy_version=np.__version__, order='row-major')


def retention_ratio(fit, years):
    if not isinstance(years, (int, float)) or not math.isfinite(years) or years < 0:
        raise ValueError('Retention years must be finite and nonnegative')
    target = 10. + years*365.25*86400
    base = float(fit['a']) + float(fit['b'])
    current = float(fit['a']) + float(fit['b'])*math.log10(target)
    result = dict(years=years, t_ref_s=10., target_time_s=target, reference_current_a=base if math.isfinite(base) else None,
                  target_current_a=current if math.isfinite(current) else None,
                  extrapolated=target > float(fit['time_max_s']) or target < float(fit['time_min_s']),
                  ratio=None, status='invalid', reason=None)
    if not all(math.isfinite(v) and v > 0 for v in (base, current)):
        result['reason'] = 'nonpositive_or_nonfinite_fit_current'
        return result
    ratio = 1. if years == 0 else current/base
    if not math.isfinite(ratio) or ratio <= 0:
        result['reason'] = 'nonpositive_or_nonfinite_retention_ratio'
        return result
    result.update(ratio=ratio, status='valid')
    if result['extrapolated']:
        result['warning'] = 'Extrapolation sensitivity scenario; not long-term measured accuracy'
    return result


def quantize(values, bound, bits):
    if not math.isfinite(bound) or bound < 0 or not isinstance(bits, int) or not 3 <= bits <= 8:
        raise ValueError('ADC requires a finite nonnegative bound and 3..8 bits')
    y = np.asarray(values)
    if not np.isfinite(y).all():
        raise ValueError('Nonfinite ADC input')
    clipped = np.clip(y, -bound, bound)
    if bound == 0:
        output = np.zeros_like(y)
    else:
        levels = 2**bits
        q = np.floor((clipped+bound)*(levels-1)/(2*bound)+.5)
        output = -bound+2*bound*q/(levels-1)
    return output, dict(count=y.size, clipped_count=int(np.count_nonzero(np.abs(y)>bound)),
                        clip_abs_error_sum=float(np.sum(np.abs(y-clipped))),
                        quantization_abs_error_sum=float(np.sum(np.abs(output-clipped))))


def tiled_linear(x, weight, bias, *, tile_size=None, bits=None, bound=None):
    x, weight, bias = np.asarray(x), np.asarray(weight), np.asarray(bias)
    if bits is None:
        return x @ weight.T + bias, dict(count=0, clipped_count=0, clip_abs_error_sum=0., quantization_abs_error_sum=0.)
    if not isinstance(tile_size, int) or tile_size < 1:
        raise ValueError('ADC requires positive tile size')
    output = np.zeros((len(x), len(weight)), dtype=np.result_type(x,weight))
    stats = dict(count=0, clipped_count=0, clip_abs_error_sum=0., quantization_abs_error_sum=0.)
    for col in range(0, weight.shape[0], tile_size):
        for row in range(0, weight.shape[1], tile_size):
            part = x[:,row:row+tile_size] @ weight[col:col+tile_size,row:row+tile_size].T
            q, diag = quantize(part, bound, bits)
            output[:,col:col+tile_size] += q
            for key in stats: stats[key] += diag[key]
    return output+bias, stats


def summarize(values):
    a = np.asarray(values, dtype=float)
    if not np.isfinite(a).all():
        raise ValueError('Summary only accepts valid finite accuracies')
    return dict(n=len(a), mean=float(a.mean()) if len(a) else None,
                std=float(a.std(ddof=1)) if len(a)>1 else None,
                p05=float(np.quantile(a,.05)) if len(a) else None,
                p50=float(np.quantile(a,.5)) if len(a) else None,
                p95=float(np.quantile(a,.95)) if len(a) else None, values=a.tolist(),
                interpretation='distribution across seeded arrays, not a confidence interval')
