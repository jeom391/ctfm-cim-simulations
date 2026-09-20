"""Synthetic torch fixture verifies the real inference wrapper, without downloading MNIST."""
import unittest
import numpy as np
import torch
from ctfm.simulation.torch_runner import Network, evaluate, calibrate, input_ranges
from ctfm.simulation.math import differential_linear, quantize_input, ADC_ORDERS
from ctfm.adapters import engine_capabilities

# One layer, two inputs, one output, hand-computable at every step.
#   x = [1.0, 0.0], r = 1  -> q = [255, 0] -> every bit plane is [1, 0]
#   p+ = 3 uS, p- = 1 uS per plane; sum_k 2^k = 255; step = r/255
#   so the ADC-off output is exactly (3-1) uS * scale.
HAND = dict(name='hand', g_plus=np.array([[3e-6, 1e-6]]), g_minus=np.array([[1e-6, 2e-6]]),
            scale=1.0, bias=np.zeros(1), input_range=1.0)
HAND_X = np.array([[1.0, 0.0]], dtype=np.float32)


def _network(**kwargs):
    return Network([HAND], tile_size=2, input_bits=8, **kwargs)


class BitSerialTests(unittest.TestCase):
    def test_eight_bit_codes_and_planes_are_the_documented_encoding(self):
        np.testing.assert_array_equal(quantize_input(HAND_X, 1.0), [[255, 0]])
        np.testing.assert_array_equal(quantize_input(np.array([[0.5]]), 1.0), [[128]])
        # r = 0 gives q = 0 rather than a division by zero.
        np.testing.assert_array_equal(quantize_input(np.array([[0.4]]), 0.0), [[0]])

    def test_adc_off_bit_serial_equals_the_restored_direct_mac(self):
        """docs/spec/08 acceptance 2: with the ADC off the 8 cycle schedule and a
        direct MAC on the dequantized input are the same number."""
        network = _network()
        direct = network(torch.from_numpy(HAND_X)).numpy()
        np.testing.assert_allclose(direct, [[2e-6]], rtol=1e-6)
        serial = {}
        network(torch.from_numpy(HAND_X), calibration=serial)
        self.assertAlmostEqual(serial['hand']['subtract_then_adc'], 2e-6, places=12)
        self.assertAlmostEqual(serial['hand']['adc_then_subtract'], 3e-6, places=12)

    def test_the_two_orders_differ_on_the_same_bits_and_range(self):
        bounds = {}
        _network()(torch.from_numpy(HAND_X), calibration=bounds)
        results = {}
        for order in ADC_ORDERS:
            results[order] = float(_network(bits=3, bounds=bounds, adc_order=order)(
                torch.from_numpy(HAND_X)).numpy()[0, 0])
        # subtract first: Q(2 uS) on [-2, 2] uS lands exactly on the top code.
        self.assertAlmostEqual(results['subtract_then_adc'], 2e-6, places=12)
        # convert first: Q(3 uS)=3 uS and Q(1 uS)=2/7*3 uS on [0, 3] uS.
        self.assertAlmostEqual(results['adc_then_subtract'], 3e-6-2*3e-6/7, places=12)
        self.assertNotAlmostEqual(results['subtract_then_adc'], results['adc_then_subtract'])

    def test_an_adc_without_an_order_or_without_planes_is_refused(self):
        with self.assertRaises(ValueError):
            Network([HAND], tile_size=2, bits=4, bounds={'hand': {}})
        digital = dict(name='hand', weights=np.ones((1, 2)), bias=np.zeros(1), input_range=1.)
        with self.assertRaises(ValueError):
            Network([digital], tile_size=2, bits=4, adc_order='subtract_then_adc',
                    bounds={'hand': {'subtract_then_adc': 1.}})

    def test_a_missing_range_for_the_requested_order_is_not_defaulted(self):
        with self.assertRaises(ValueError):
            _network(bits=4, adc_order='adc_then_subtract',
                     bounds={'hand': {'subtract_then_adc': 1e-6}})(torch.from_numpy(HAND_X))


class DigitalAndCalibrationTests(unittest.TestCase):
    def test_digital_layers_run_with_and_without_input_quantization(self):
        w = np.array([[.4, .4, .4], [.2, .2, .2], [.1, .1, .1]], dtype=np.float32)
        b = np.array([.25, .5, .75], dtype=np.float32)
        x = np.array([[1., 1., 1.]], dtype=np.float32)
        layers = [dict(name='fixture', weights=w, bias=b, input_range=1.)]
        np.testing.assert_allclose(Network(layers)(torch.from_numpy(x)).numpy(), x@w.T+b, rtol=1e-6)
        # q = 255 for every pixel, so the 8 bit path reproduces the same sum here.
        np.testing.assert_allclose(Network(layers, input_bits=8)(torch.from_numpy(x)).numpy(),
                                   x@w.T+b, rtol=1e-6)

    def test_hidden_input_range_comes_from_validation_only(self):
        w = np.array([[1., 0.], [0., 2.]], dtype=np.float32)
        layers = [dict(name='fc1', weights=w, bias=np.zeros(2, dtype=np.float32)),
                  dict(name='fc2', weights=w, bias=np.zeros(2, dtype=np.float32))]
        images = np.array([[255, 0], [0, 128], [255, 255]], dtype=np.uint8)
        labels = np.zeros(3, dtype=np.uint8)
        # Validation row 1 only: input [0, 0.502] -> hidden [0, 1.004].
        ranges = input_ranges(layers, images, labels, np.array([1]))
        self.assertEqual(ranges['fc1'], 1.)
        self.assertAlmostEqual(ranges['fc2'], 2*128/255., places=5)
        # Row 2 has a larger hidden maximum, so the two splits must not agree.
        self.assertGreater(input_ranges(layers, images, labels, np.array([2]))['fc2'],
                           ranges['fc2'])

    def test_calibration_uses_validation_rows_only_and_covers_both_orders(self):
        layer = dict(name='fixture', g_plus=np.array([[2e-5, 2e-5]]),
                     g_minus=np.array([[1e-5, 1e-5]]), scale=1., bias=np.zeros(1),
                     input_range=1.)
        images = np.array([[0, 0], [255, 255], [128, 128]], dtype=np.uint8)
        labels = np.zeros(3, dtype=np.uint8)
        zero = calibrate([layer], images, labels, np.array([0]), 2, 'torch_reference')
        self.assertEqual(zero['fixture'], {'subtract_then_adc': 0., 'adc_then_subtract': 0.})
        full = calibrate([layer], images, labels, np.array([1]), 2, 'torch_reference')
        self.assertAlmostEqual(full['fixture']['subtract_then_adc'], 2e-5, places=11)
        self.assertAlmostEqual(full['fixture']['adc_then_subtract'], 4e-5, places=11)

    def test_optional_engine_is_honest(self):
        caps = engine_capabilities()
        self.assertTrue(caps['torch_reference']['available'])
        self.assertFalse(caps['neurosim']['available'])
        if not caps['aihwkit_ideal']['available']:
            self.assertTrue(caps['aihwkit_ideal']['reason'])
            with self.assertRaises(ValueError):
                Network([dict(name='x', weights=np.ones((1, 1)), bias=np.zeros(1))], 'aihwkit_ideal')


def test_every_advertised_adc_combination_matches_the_independent_numpy_reference():
    """18 bit/tile pairs x both orders, against the NumPy model in simulation.math.

    float32 and float64 can round a sample sitting on a code boundary to
    neighbouring codes, so the tolerance is one ADC step propagated through the
    8 cycle shift-add rather than a free-form epsilon.
    """
    rng = np.random.default_rng(193)
    x = np.abs(rng.normal(size=(3, 270))).astype(np.float32)
    g_plus = np.abs(rng.normal(scale=1e-5, size=(130, 270)))+1e-7
    g_minus = np.abs(rng.normal(scale=1e-5, size=(130, 270)))+1e-7
    bias = rng.normal(scale=1e-3, size=130)
    scale, input_range = 0.37, 2.0
    layer = dict(name='swept', g_plus=g_plus, g_minus=g_minus, scale=scale, bias=bias,
                 input_range=input_range)
    reference = {}
    differential_linear(x, g_plus, g_minus, bias, scale, input_range, tile_size=64,
                        calibration=reference)
    for tile in (64, 128, 256):
        bounds = {}
        Network([layer], tile_size=tile, input_bits=8)(torch.from_numpy(x), calibration=bounds)
        for bits in range(3, 9):
            for order in ADC_ORDERS:
                bound = bounds['swept'][order]
                expected, stats = differential_linear(
                    x, g_plus, g_minus, bias, scale, input_range, tile_size=tile,
                    adc_bits=bits, bound=bound, order=order)
                network = Network([layer], tile_size=tile, bits=bits, bounds=bounds,
                                  adc_order=order)
                actual = network(torch.from_numpy(x)).numpy()
                step = bound*(2 if order == 'subtract_then_adc' else 1)/(2**bits-1)
                tolerance = step*255*(input_range/255)*scale*(g_plus.shape[1]//tile+1)
                assert np.abs(actual-expected).max() <= tolerance, (tile, bits, order)
                # The range is the float32 maximum, so a sample sitting exactly on it
                # can land either side of the bound when NumPy recomputes in float64.
                blocks = -(-130//tile)*-(-270//tile)
                assert abs(network.stats['swept']['clipped_count']
                           - stats['clipped_count']) <= blocks, (tile, bits, order)


if __name__ == '__main__':
    unittest.main()
