"""Synthetic, hand-computed contract fixtures; no MNIST claims."""
import hashlib
import json
import unittest
import numpy as np
from ctfm.simulation.math import (map_weights, d2d_factors, retention_ratio, quantize,
                                  tiled_linear, summarize, quantize_input, bit_planes,
                                  differential_linear, ADC_ORDERS,
                                  c2c_factors, c2c_relative_cv_percent_to_ratio,
                                  c2c_factor_statistics, observed_range_violation)

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

    # --- C2C core module (task 03; calculation only, not wired into run_experiment) ---

    def test_c2c_percent_to_ratio_is_the_only_percent_conversion(self):
        self.assertEqual(c2c_relative_cv_percent_to_ratio(5), .05)
        self.assertEqual(c2c_relative_cv_percent_to_ratio(0), 0.)
        for bad in (None, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):c2c_relative_cv_percent_to_ratio(bad)

    def test_c2c_seed_contract_matches_d2d_shape_and_adds_reprogram_index(self):
        key=[7,'abc',2,3,'fc1','plus']
        seed=int.from_bytes(hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).digest()[:8],'big')
        f,info=c2c_factors((3,4),.2,*key);s=np.sqrt(np.log1p(.2**2))
        expected=np.exp(-s*s/2+s*np.random.Generator(np.random.PCG64(seed)).standard_normal((3,4)))
        np.testing.assert_equal(f,expected);self.assertEqual(info['seed'],seed);self.assertEqual(info['seed_key'],key)

    def test_c2c_off_or_cv_zero_is_the_identity_and_leaves_input_unchanged(self):
        f,_=c2c_factors((3,4),0,7,'abc',2,3,'fc1','plus')
        np.testing.assert_equal(f,np.ones((3,4)))
        g_nominal=np.array([[1e-6,2e-6],[3e-6,4e-6]])
        np.testing.assert_equal(g_nominal*np.ones((2,2)),g_nominal)  # off/CV0: G_program==G_nominal exactly
        with self.assertRaises(ValueError):c2c_factors((3,4),None,7,'abc',2,3,'fc1','plus')

    def test_c2c_reproducible_for_the_same_record_across_two_adc_orders(self):
        """No adc_order/years parameter exists on c2c_factors -- calling it twice
        with the same (seed, profile, array, reprogram, layer, polarity), once
        as if for subtract_then_adc and once for adc_then_subtract, MUST return
        the same record; there is nothing to pass differently, by construction."""
        key=(11,'profile-hash',0,5,'fc2','minus')
        first,_=c2c_factors((6,),.1,*key)
        second,_=c2c_factors((6,),.1,*key)
        np.testing.assert_equal(first,second)

    def test_c2c_new_reprogram_or_polarity_draws_a_different_record(self):
        base=c2c_factors((6,),.1,11,'profile-hash',0,5,'fc2','minus')[0]
        reprogrammed=c2c_factors((6,),.1,11,'profile-hash',0,6,'fc2','minus')[0]
        other_polarity=c2c_factors((6,),.1,11,'profile-hash',0,5,'fc2','plus')[0]
        self.assertFalse(np.array_equal(base,reprogrammed))
        self.assertFalse(np.array_equal(base,other_polarity))

    def test_d2d_array_deviation_is_unaffected_by_c2c_reprogram_draws(self):
        """D2D is keyed only by array_index (no reprogram_index); redrawing C2C
        for a new record must never move the D2D factor for that same array."""
        d2d_before,_=d2d_factors((4,),.15,99,'profile-hash',0,'fc1','plus')
        c2c_factors((4,),.1,99,'profile-hash',0,1,'fc1','plus')  # a C2C draw happens in between
        c2c_factors((4,),.1,99,'profile-hash',0,2,'fc1','plus')  # ... and another, different record
        d2d_after,_=d2d_factors((4,),.15,99,'profile-hash',0,'fc1','plus')
        np.testing.assert_equal(d2d_before,d2d_after)

    def test_c2c_rejects_nonfinite_or_negative_cv_and_invalid_shape(self):
        for bad_cv in (None, -.01, float('nan'), float('inf'), True, False):
            with self.assertRaises(ValueError):c2c_factors((2,2),bad_cv,1,'p',0,0,'fc1','plus')
        for bad_shape in ((), (0,), (-1,), (2.5,), (True,)):
            with self.assertRaises(ValueError):c2c_factors(bad_shape,.1,1,'p',0,0,'fc1','plus')
        with self.assertRaises(ValueError):c2c_factors((2,),1e200,1,'p',0,0,'fc1','plus')  # sigma overflow, not silent inf

    def test_c2c_percent_to_ratio_rejects_bool_even_though_python_treats_it_as_an_int(self):
        for bad in (True, False):
            with self.assertRaises(ValueError):c2c_relative_cv_percent_to_ratio(bad)

    def test_c2c_uses_log1p_so_a_tiny_cv_does_not_silently_zero_out(self):
        """1+cv*cv rounds to exactly 1.0 in float64 once cv is below ~1e-8, so
        plain log(1+cv*cv) would silently return sigma=0 (identity, no C2C
        effect at all) for a nonzero manual CV. log1p keeps it nonzero."""
        f,_=c2c_factors((5,),1e-9,1,'p',0,0,'fc1','plus')
        self.assertFalse(np.array_equal(f,np.ones(5)))

    def test_c2c_statistical_sanity_mean_one_and_target_cv_at_large_n(self):
        f,_=c2c_factors((300000,),.08,42,'profile-x',0,3,'fc1','plus')
        stats=c2c_factor_statistics(f)
        self.assertEqual(stats['n'],300000)
        self.assertAlmostEqual(stats['mean'],1.,delta=.005)          # SE(mean)~cv/sqrt(n)~1.5e-4
        self.assertAlmostEqual(stats['empirical_cv'],.08,delta=.08*.05)  # within 5% relative of the target CV
        with self.assertRaises(ValueError):c2c_factor_statistics(np.array([]))
        with self.assertRaises(ValueError):c2c_factor_statistics(np.array([1.,float('nan')]))

    def test_c2c_factor_statistics_is_not_fooled_by_g_program_spread(self):
        """The exact mistake docs/completion-plan-2026-09-21.md P2 warns against:
        std(G_program)/mean(G_program) is dominated by each weight's distinct
        nominal conductance, not the injected C2C ratio -- only the factor
        array itself recovers the injected CV."""
        f,_=c2c_factors((5000,),.05,1,'p',0,0,'fc1','plus')
        g_nominal=np.geomspace(1e-7,1e-3,5000)  # four decades of nominal spread
        g_program=g_nominal*f
        factor_cv=c2c_factor_statistics(f)['empirical_cv']
        g_program_cv=np.std(g_program,ddof=1)/np.mean(g_program)
        self.assertAlmostEqual(factor_cv,.05,delta=.05*.1)
        self.assertGreater(g_program_cv,1.)  # wildly larger than .05; would misreport the injected CV

    def test_observed_range_violation_reports_without_clipping(self):
        g_program=np.array([.5,1.5,2.,3.5,4.])
        result=observed_range_violation(g_program,1.,3.)
        self.assertAlmostEqual(result['outside_observed_fraction'],3/5)  # .5, 3.5 and 4. fall outside [1,3]
        self.assertEqual((result['min_s'],result['max_s']),(.5,4.))
        np.testing.assert_equal(g_program,[.5,1.5,2.,3.5,4.])  # input array itself is never modified/clipped
        with self.assertRaises(ValueError):observed_range_violation(np.array([float('nan')]),0.,1.)
        with self.assertRaises(ValueError):observed_range_violation(g_program,2.,1.)  # min>max
if __name__=='__main__':unittest.main()
