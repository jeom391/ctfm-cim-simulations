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


def _mean_one_lognormal(shape, sigma, seed):
    """exp(-sigma^2/2 + sigma*Z), Z~N(0,1): the mean-1, positive lognormal
    sampler shared by d2d_factors and c2c_factors once their caller has
    already turned a relative CV into sigma=sqrt(log(1+cv^2)) and validated
    it. Pulling this out changes nothing about d2d_factors' behavior --
    same RNG calls in the same order -- it only avoids a second copy of the
    formula for c2c_factors."""
    z = np.random.Generator(np.random.PCG64(seed)).standard_normal(shape)
    return np.exp(-sigma*sigma/2 + sigma*z)


def d2d_factors(shape, cv, root_seed, profile_hash, array_index, layer_name, polarity):
    if cv is None or not math.isfinite(cv) or cv < 0:
        raise ValueError('D2D requires a finite nonnegative measured CV; null is unavailable')
    key = [root_seed, profile_hash, array_index, layer_name, polarity]
    encoded = json.dumps(key, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    seed = int.from_bytes(hashlib.sha256(encoded).digest()[:8], 'big')
    sigma = np.sqrt(np.log(1+cv*cv))
    if not np.isfinite(sigma):
        raise ValueError('D2D CV is too large for a finite lognormal distribution')
    factors = _mean_one_lognormal(shape, sigma, seed)
    if not np.isfinite(factors).all() or np.any(factors <= 0):
        raise ValueError('D2D realization produced nonpositive or nonfinite factors')
    return factors, dict(seed_key=key, seed=seed, generator='PCG64', numpy_version=np.__version__, order='row-major')


def c2c_relative_cv_percent_to_ratio(cv_percent):
    """Manual relative CV entered as a percent (5 means 5%) -> the unitless
    ratio c that c2c_factors takes. This is the ONLY place percent and ratio
    meet; c2c_factors and c2c_factor_statistics both take the ratio, never a
    percent, so a caller cannot accidentally pass '5' where '0.05' belongs."""
    if isinstance(cv_percent, bool) or cv_percent is None or not math.isfinite(cv_percent) or cv_percent < 0:
        raise ValueError('C2C relative CV must be a finite nonnegative percentage, not a boolean')
    return cv_percent / 100.


def _validate_c2c_shape(shape):
    dims = (shape,) if isinstance(shape, (int, np.integer)) and not isinstance(shape, bool) else tuple(shape)
    if not dims or any(isinstance(d, bool) or not isinstance(d, (int, np.integer)) or d <= 0 for d in dims):
        raise ValueError('C2C requires a nonempty shape of positive integers')
    return dims


def c2c_factors(shape, cv, root_seed, profile_hash, array_index, reprogram_index, layer_name, polarity):
    """Positive, mean-1 lognormal cycle-to-cycle (C2C) multiplicative factors
    for one record (one reprogram of one array's one layer/plane).

    A manual engineering assumption (docs/completion-plan-2026-09-21.md P2),
    not a measured CTFM distribution: c=cv (a ratio, see
    c2c_relative_cv_percent_to_ratio for the percent conversion),
    s=sqrt(log(1+c^2)), f=exp(-s^2/2+sZ), Z~N(0,1). G_program is then
    G_nominal * f_D2D * f_C2C (D2D from d2d_factors above; the multiply
    itself has no dedicated helper, same as the existing D2D call site).

    Unlike D2D -- fixed for the lifetime of one array -- C2C is redrawn every
    time a state is (re)written, so ``reprogram_index`` is part of the RNG
    key and ``array_index`` still is too (a fresh array reprograms its own
    cells independently of every other array). ``adc_order`` and ``years``
    are deliberately NOT part of the key: this function is pure and
    deterministic in its inputs, so calling it again with the same
    (root_seed, profile_hash, array_index, reprogram_index, layer_name,
    polarity) reproduces the exact same record for a second ADC order or a
    later retention timepoint -- there is no separate cache to manage, and a
    caller must never fold adc_order/years into these identifiers to "get a
    fresh draw," since that would silently break record reuse.
    """
    dims = _validate_c2c_shape(shape)
    if isinstance(cv, bool) or cv is None or not math.isfinite(cv) or cv < 0:
        raise ValueError('C2C requires a finite nonnegative relative CV, not a boolean; null is unavailable')
    key = [root_seed, profile_hash, array_index, reprogram_index, layer_name, polarity]
    encoded = json.dumps(key, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    seed = int.from_bytes(hashlib.sha256(encoded).digest()[:8], 'big')
    # log1p(cv*cv), not log(1+cv*cv): a manual CV can be entered as a very
    # small percentage, and 1+cv*cv rounds to exactly 1.0 in float64 once
    # cv is below ~1e-8, silently zeroing sigma (docs/completion-plan
    # review, 04_TASK step "매우 작은 CV에는 log1p 사용"). d2d_factors keeps
    # its original log(1+cv*cv) unchanged -- this does not touch D2D at all.
    sigma = np.sqrt(np.log1p(cv*cv))
    if not np.isfinite(sigma):
        raise ValueError('C2C CV is too large for a finite lognormal distribution')
    factors = _mean_one_lognormal(dims, sigma, seed)
    if not np.isfinite(factors).all() or np.any(factors <= 0):
        raise ValueError('C2C realization produced nonpositive or nonfinite factors')
    return factors, dict(seed_key=key, seed=seed, generator='PCG64', numpy_version=np.__version__, order='row-major')


def c2c_factor_statistics(factors):
    """Sample mean/std/empirical CV of the generated factors themselves.

    Deliberately takes the factor array, not G_program: G_program's spread
    also reflects each weight's distinct nominal conductance, so its raw CV
    is not the injected relative CV and must never be reported as one.
    """
    a = np.asarray(factors, dtype=np.float64)
    if a.size == 0 or not np.isfinite(a).all():
        raise ValueError('Factor statistics require a nonempty finite array')
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if a.size > 1 else None
    return dict(n=int(a.size), mean=mean, std=std,
                empirical_cv=(std / mean if std is not None and mean else None))


def observed_range_violation(g_program, g_min_s, g_max_s):
    """Fraction of programmed (G_nominal * factor) values that fall outside
    the profile's observed pool bounds. Reported only -- never used to clip;
    docs/spec/08-hardware-baseline.md section 3 prohibits automatic
    Gmin/Gmax clipping."""
    g = np.asarray(g_program, dtype=np.float64)
    if g.size == 0 or not np.isfinite(g).all():
        raise ValueError('Observed-range diagnostics require a nonempty finite array')
    if not (math.isfinite(g_min_s) and math.isfinite(g_max_s)) or g_min_s > g_max_s:
        raise ValueError('g_min_s/g_max_s must be finite with g_min_s <= g_max_s')
    outside = (g < g_min_s) | (g > g_max_s)
    return dict(outside_observed_fraction=float(np.mean(outside)), min_s=float(g.min()), max_s=float(g.max()))


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


INPUT_LEVELS = 255
INPUT_BITS = 8
ADC_ORDERS = ('subtract_then_adc', 'adc_then_subtract')


def quantize_input(x, input_range):
    """q=clip(floor(255*x/r+0.5),0,255) from docs/spec/08-hardware-baseline.md section 4.

    ``input_range`` is r: 1 for the [0,1] pixel layer, and the digital
    checkpoint's validation ReLU maximum for a hidden layer. r=0 gives q=0.
    Negative inputs are out of scope for this unsigned encoding.
    """
    values = np.asarray(x, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite activation cannot be quantized')
    if not isinstance(input_range, (int, float)) or not math.isfinite(input_range) or input_range < 0:
        raise ValueError('Input range must be finite and nonnegative')
    if values.size and values.min() < 0:
        raise ValueError('Unsigned 8 bit input encoding requires nonnegative activations')
    if input_range == 0:
        return np.zeros(values.shape, dtype=np.int64)
    return np.clip(np.floor(INPUT_LEVELS*values/input_range+.5), 0, INPUT_LEVELS).astype(np.int64)


def bit_planes(q, bits=INPUT_BITS):
    """LSB-first fixed-length bit schedule; an all-zero cycle is not skipped."""
    codes = np.asarray(q, dtype=np.int64)
    return np.stack([(codes >> k) & 1 for k in range(bits)], axis=0).astype(np.float64)


def quantize(values, bits, lower, upper):
    """Q(z)=L+clip(floor((z-L)/(U-L)*(2^b-1)+0.5),0,2^b-1)*(U-L)/(2^b-1).

    The grid is uniform over [lower, upper], so a bipolar range may not represent
    exact zero. An empty range quantizes everything to zero.
    """
    if not isinstance(bits, int) or isinstance(bits, bool) or not 3 <= bits <= 8:
        raise ValueError('ADC requires 3..8 bits')
    if not all(math.isfinite(v) for v in (lower, upper)) or upper < lower:
        raise ValueError('ADC requires a finite range with upper >= lower')
    y = np.asarray(values, dtype=np.float64)
    if not np.isfinite(y).all():
        raise ValueError('Nonfinite ADC input')
    clipped = np.clip(y, lower, upper)
    if upper == lower:
        output = np.zeros_like(y)
    else:
        steps = 2**bits-1
        code = np.clip(np.floor((clipped-lower)/(upper-lower)*steps+.5), 0, steps)
        output = lower+code*(upper-lower)/steps
    return output, dict(count=y.size, clipped_count=int(np.count_nonzero((y < lower) | (y > upper))),
                        clip_abs_error_sum=float(np.sum(np.abs(y-clipped))),
                        quantization_abs_error_sum=float(np.sum(np.abs(output-clipped))))


def _zero_stats():
    return dict(count=0, clipped_count=0, clip_abs_error_sum=0., quantization_abs_error_sum=0.)


def tiled_linear(x, weight, bias, *, tile_size=None, bits=None, bound=None):
    """Legacy single-plane bipolar path, kept for the v1.1 comparison only.

    The v1.2 accuracy model is :func:`differential_linear`. This one quantizes a
    completed MAC once, which docs/spec/08 section 4 says must not be treated as
    the same result as per-bit-plane quantization.
    """
    x, weight, bias = np.asarray(x), np.asarray(weight), np.asarray(bias)
    if bits is None:
        return x @ weight.T + bias, _zero_stats()
    if not isinstance(tile_size, int) or tile_size < 1:
        raise ValueError('ADC requires positive tile size')
    output = np.zeros((len(x), len(weight)), dtype=np.result_type(x, weight))
    stats = _zero_stats()
    for col in range(0, weight.shape[0], tile_size):
        for row in range(0, weight.shape[1], tile_size):
            part = x[:, row:row+tile_size] @ weight[col:col+tile_size, row:row+tile_size].T
            q, diag = quantize(part, bits, -bound, bound)
            output[:, col:col+tile_size] += q
            for key in stats: stats[key] += diag[key]
    return output+bias, stats


def differential_linear(x, g_plus, g_minus, bias, scale, input_range, *, tile_size,
                        adc_bits=None, bound=None, order=None, calibration=None,
                        input_bits=INPUT_BITS):
    """One layer of the v1.2 model: 8 bit serial input over a G+/G- cell pair.

    Independent NumPy reference for :class:`ctfm.simulation.torch_runner.Network`.
    Partial sums are conductance-domain (siemens x bit); physical current is that
    times VDS, which the caller records rather than folding in here.

    ``calibration`` collects the nominal ADC range for both orders in one pass
    over every tile and bit plane with the ADC bypassed, so a range is never
    derived from an already quantized signal.
    """
    g_plus = np.asarray(g_plus, dtype=np.float64)
    g_minus = np.asarray(g_minus, dtype=np.float64)
    bias = np.asarray(bias, dtype=np.float64)
    if g_plus.shape != g_minus.shape:
        raise ValueError('The two conductance planes must have the same shape')
    if not isinstance(tile_size, int) or isinstance(tile_size, bool) or tile_size < 1:
        raise ValueError('A positive physical tile size is required; it is meaningful with the ADC off too')
    codes = quantize_input(x, input_range)
    step = input_range/INPUT_LEVELS
    outputs, inputs = g_plus.shape
    if adc_bits is None and calibration is None:
        # The same sum as the bit serial loop; acceptance 2 checks the equality.
        return (codes*step) @ (scale*(g_plus-g_minus)).T + bias, _zero_stats()
    if adc_bits is not None and order not in ADC_ORDERS:
        raise ValueError('ADC requires an explicit order: '+', '.join(ADC_ORDERS))
    planes = bit_planes(codes, input_bits)
    significance = (2.**np.arange(input_bits)).reshape(-1, 1, 1)
    accumulated = np.zeros((len(codes), outputs), dtype=np.float64)
    stats = _zero_stats()
    for col in range(0, outputs, tile_size):
        for row in range(0, inputs, tile_size):
            block = planes[:, :, row:row+tile_size]
            plus = block @ g_plus[col:col+tile_size, row:row+tile_size].T
            minus = block @ g_minus[col:col+tile_size, row:row+tile_size].T
            if calibration is not None:
                calibration['subtract_then_adc'] = max(calibration.get('subtract_then_adc', 0.),
                                                       float(np.abs(plus-minus).max()))
                calibration['adc_then_subtract'] = max(calibration.get('adc_then_subtract', 0.),
                                                       float(plus.max()), float(minus.max()))
            if adc_bits is None:
                converted = plus-minus
            elif order == 'subtract_then_adc':
                converted, diag = quantize(plus-minus, adc_bits, -float(bound), float(bound))
                for key in stats: stats[key] += diag[key]
            else:
                high, diag_plus = quantize(plus, adc_bits, 0., float(bound))
                low, diag_minus = quantize(minus, adc_bits, 0., float(bound))
                converted = high-low
                for key in stats: stats[key] += diag_plus[key]+diag_minus[key]
            accumulated[:, col:col+converted.shape[2]] += (significance*converted).sum(axis=0)
    return accumulated*step*scale+bias, stats


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
