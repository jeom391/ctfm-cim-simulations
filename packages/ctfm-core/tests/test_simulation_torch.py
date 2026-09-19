"""Synthetic torch fixture verifies the real inference wrapper, without downloading MNIST."""
import unittest
import numpy as np
import torch
from ctfm.simulation.torch_runner import Network, evaluate, calibrate
from ctfm.simulation.math import tiled_linear
from ctfm.adapters import engine_capabilities

class TorchSimulationTests(unittest.TestCase):
    def test_numpy_hand_fixture_matches_actual_torch_tiles(self):
        w=np.array([[.4,.4,.4],[.2,.2,.2],[.1,.1,.1]],dtype=np.float32)
        b=np.array([.25,.5,.75],dtype=np.float32)
        x=np.array([[1.,1.,1.]],dtype=np.float32)
        layers=[dict(name='fixture',weights=w,bias=b)]
        n=Network(layers,tile_size=2,bits=3,bounds={'fixture':1.})
        np.testing.assert_allclose(n(torch.from_numpy(x)).numpy(),tiled_linear(x,w,b,tile_size=2,bits=3,bound=1)[0],rtol=1e-6)
        np.testing.assert_allclose(Network(layers)(torch.from_numpy(x)).numpy(),x@w.T+b)
        np.testing.assert_equal(Network(layers,tile_size=2,bits=3,bounds={'fixture':0.})(torch.from_numpy(x)).numpy(),[b])
    def test_validation_only_calibration_and_real_denominator(self):
        layers=[dict(name='fixture',weights=np.array([[1.,1.,1.],[-1.,-1.,-1.]]),bias=np.zeros(2))]
        x=np.array([[0,0,0],[255,255,255],[128,128,128]],dtype=np.uint8);y=np.array([0,0,0])
        self.assertEqual(calibrate(layers,x,y,np.array([0]),2,'torch_reference'),{'fixture':0.})
        self.assertEqual(calibrate(layers,x,y,np.array([1]),2,'torch_reference'),{'fixture':2.})
        result=evaluate(Network(layers),x,y)
        self.assertEqual(result['n'],3);self.assertEqual(result['correct'],3)
    def test_optional_engine_is_honest(self):
        caps=engine_capabilities()
        self.assertTrue(caps['torch_reference']['available'])
        self.assertFalse(caps['neurosim']['available'])
        if not caps['aihwkit_ideal']['available']:
            self.assertTrue(caps['aihwkit_ideal']['reason'])
            with self.assertRaises(ValueError):Network([dict(name='x',weights=np.ones((1,1)),bias=np.zeros(1))],'aihwkit_ideal')
if __name__=='__main__':unittest.main()

def test_every_advertised_torch_adc_combination_matches_independent_numpy():
    rng=np.random.default_rng(193)
    x=rng.normal(size=(3,270)).astype(np.float32)
    weights=rng.normal(scale=.12,size=(130,270)).astype(np.float32)
    bias=rng.normal(scale=.01,size=130).astype(np.float32)
    layers=[dict(name="supported",weights=weights,bias=bias)]
    for tile in (64,128,256):
        for bits in range(3,9):
            expected,stats=tiled_linear(x,weights,bias,tile_size=tile,bits=bits,bound=1.75)
            network=Network(layers,tile_size=tile,bits=bits,bounds={"supported":1.75})
            actual=network(torch.from_numpy(x)).numpy()
            np.testing.assert_allclose(actual,expected,atol=2e-5,rtol=2e-5)
            assert network.stats["supported"]["clipped_count"]==stats["clipped_count"]
