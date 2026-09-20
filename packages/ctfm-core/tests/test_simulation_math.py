"""Synthetic, hand-computed contract fixtures; no MNIST claims."""
import hashlib
import json
import unittest
import numpy as np
from ctfm.simulation.math import (map_weights, d2d_factors, retention_ratio, quantize,
                                  tiled_linear, summarize, quantize_input, bit_planes,
                                  differential_linear, ADC_ORDERS)

def states(values):
    return [dict(state_id=str(i), conductance_s=g, direction='ltp') for i,g in enumerate(values)]

class SimulationMathTests(unittest.TestCase):
    def test_mapping_endpoints_zero_tie_and_membership(self):
        m=map_weights(np.array([[-1.,-.25,0,.25,1]]),states([1.,2.,3.]),'fixed_reference')
        np.testing.assert_equal(m['g_plus'],[[1,1,1,1,3]])
        np.testing.assert_equal(m['g_minus'],[[3,1,1,1,1]])
        self.assertEqual(m['scale'],.5)
        z=map_weights(np.zeros((2,2)),states([1.,2.]),'pair_search')
        self.assertEqual(z['scale'],0)
        np.testing.assert_equal(z['g_plus'],np.ones((2,2)))
    def test_pair_search_matches_independent_brute_force(self):
        gs=[1.,1.,1.4,2.8,4.]; w=np.array([np.linspace(-1,1,101)])
        m=map_weights(w,states(gs),'pair_search')
        for k,target in enumerate(np.abs(w[0])/m['scale']):
            candidates=[(abs((p-n)-target),p+n,i,j) for i,p in enumerate(gs) for j,n in enumerate(gs) if p>=n]
            _,_,i,j=min(candidates)
            if w[0,k]<0:i,j=j,i
            self.assertEqual(m['plus_index'][0,k],i)
            self.assertEqual(m['minus_index'][0,k],j)
    def test_seed_contract_cv_zero_null_and_polarity(self):
        key=[7,'abc',2,'fc1','plus']
        seed=int.from_bytes(hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).digest()[:8],'big')
        f,info=d2d_factors((3,4),.2,*key); s=np.sqrt(np.log(1+.2**2))
        expected=np.exp(-s*s/2+s*np.random.Generator(np.random.PCG64(seed)).standard_normal((3,4)))
        np.testing.assert_equal(f,expected);self.assertEqual(info['seed'],seed)
        np.testing.assert_equal(f,d2d_factors((3,4),.2,*key)[0])
        self.assertFalse(np.array_equal(f,d2d_factors((3,4),.2,7,'abc',2,'fc1','minus')[0]))
        np.testing.assert_equal(d2d_factors((3,4),0,*key)[0],np.ones((3,4)))
        with self.assertRaises(ValueError):d2d_factors((3,4),None,*key)
    def test_retention_zero_valid_and_invalid_extrapolation(self):
        fit=dict(a=2.,b=-.2,time_min_s=10.,time_max_s=100.)
        self.assertEqual(retention_ratio(fit,0)['ratio'],1)
        r=retention_ratio(fit,1)
        self.assertAlmostEqual(r['ratio'],(2-.2*np.log10(10+365.25*86400))/1.8)
        self.assertTrue(r['extrapolated'])
        self.assertEqual(retention_ratio(dict(fit,a=.5),1)['status'],'invalid')
        self.assertEqual(retention_ratio(dict(fit,a=.1),0)['status'],'invalid')
    def test_adc_grid_bits_clipping_and_zero(self):
        q3,d=quantize(np.array([0.,.2,2.]),3,-1.,1.);q8,_=quantize(np.array([0.,.2,2.]),8,-1.,1.)
        np.testing.assert_allclose(q3,[1/7,1/7,1]);self.assertFalse(np.allclose(q3,q8))
        self.assertEqual(d['clipped_count'],1);self.assertEqual(d['count'],3)
        np.testing.assert_equal(quantize(np.array([4.,0.]),3,0.,0.)[0],[0,0])

    def test_unipolar_grid_starts_at_the_lower_bound(self):
        q,_=quantize(np.array([0.,1.5,3.]),3,0.,3.)
        np.testing.assert_allclose(q,[0.,3*4/7,3.])
        with self.assertRaises(ValueError):quantize(np.array([0.]),3,1.,0.)
        with self.assertRaises(ValueError):quantize(np.array([0.]),2,0.,1.)

    def test_unsigned_input_codes_and_lsb_first_planes(self):
        np.testing.assert_array_equal(quantize_input(np.array([0.,.5,1.,2.]),1.),[0,128,255,255])
        np.testing.assert_array_equal(quantize_input(np.array([1.]),0.),[0])
        with self.assertRaises(ValueError):quantize_input(np.array([-.1]),1.)
        planes=bit_planes(np.array([5]),4)
        np.testing.assert_array_equal(planes[:,0],[1,0,1,0])
        self.assertEqual(bit_planes(np.array([0]),8).shape,(8,1))

    def test_bit_serial_pair_matches_the_hand_computed_partial_sums(self):
        gp=np.array([[3e-6,1e-6]]);gm=np.array([[1e-6,2e-6]]);b=np.zeros(1)
        x=np.array([[1.,0.]])
        direct,_=differential_linear(x,gp,gm,b,1.,1.,tile_size=2)
        np.testing.assert_allclose(direct,[[2e-6]])
        cal={}
        serial,_=differential_linear(x,gp,gm,b,1.,1.,tile_size=2,calibration=cal)
        np.testing.assert_allclose(serial,direct,atol=1e-18)
        self.assertAlmostEqual(cal['subtract_then_adc'],2e-6,places=12)
        self.assertAlmostEqual(cal['adc_then_subtract'],3e-6,places=12)
        first,_=differential_linear(x,gp,gm,b,1.,1.,tile_size=2,adc_bits=3,
                                    bound=cal['subtract_then_adc'],order='subtract_then_adc')
        second,_=differential_linear(x,gp,gm,b,1.,1.,tile_size=2,adc_bits=3,
                                     bound=cal['adc_then_subtract'],order='adc_then_subtract')
        np.testing.assert_allclose(first,[[2e-6]],atol=1e-18)
        np.testing.assert_allclose(second,[[3e-6-2*3e-6/7]],atol=1e-18)

    def test_bit_serial_equals_the_direct_mac_with_the_adc_off(self):
        rng=np.random.default_rng(5)
        gp=np.abs(rng.normal(scale=1e-5,size=(9,11)))+1e-7
        gm=np.abs(rng.normal(scale=1e-5,size=(9,11)))+1e-7
        b=rng.normal(size=9)*1e-3;x=np.abs(rng.normal(size=(4,11)))
        direct,_=differential_linear(x,gp,gm,b,.3,2.,tile_size=4)
        serial,_=differential_linear(x,gp,gm,b,.3,2.,tile_size=4,calibration={})
        np.testing.assert_allclose(serial,direct,rtol=1e-12)

    def test_the_adc_needs_an_explicit_order_and_a_physical_tile(self):
        gp=np.ones((2,2))*1e-5;gm=np.ones((2,2))*1e-6;b=np.zeros(2);x=np.ones((1,2))
        with self.assertRaises(ValueError):
            differential_linear(x,gp,gm,b,1.,1.,tile_size=2,adc_bits=4,bound=1.,order=None)
        with self.assertRaises(ValueError):
            differential_linear(x,gp,gm,b,1.,1.,tile_size=None)
        with self.assertRaises(ValueError):
            differential_linear(x,gp,gm[:1],b,1.,1.,tile_size=2)
        self.assertEqual(ADC_ORDERS,('subtract_then_adc','adc_then_subtract'))
    def test_row_adc_then_sum_and_bias_once_column_blocks(self):
        x=np.array([[1.,1.,1.]]);w=np.array([[.4,.4,.4],[.2,.2,.2],[.1,.1,.1]]);b=np.array([.25,.5,.75])
        y,_=tiled_linear(x,w,b,tile_size=2,bits=3,bound=1)
        np.testing.assert_allclose(y,[[5/7+3/7+.25,3/7+1/7+.5,1/7+1/7+.75]])
        self.assertFalse(np.allclose(y,tiled_linear(x,w,b,tile_size=3,bits=3,bound=1)[0]))
        np.testing.assert_allclose(tiled_linear(x,w,b)[0],x@w.T+b)
        np.testing.assert_equal(tiled_linear(x,w,b,tile_size=2,bits=3,bound=0)[0],[b])
    def test_summary_valid_denominator(self):
        self.assertIsNone(summarize([.5])['std']);self.assertIsNone(summarize([])['mean'])
        self.assertEqual(summarize([.5,.7])['n'],2)
        self.assertAlmostEqual(summarize([.5,.7])['std'],np.sqrt(.02))
if __name__=='__main__':unittest.main()
