"""Actual MNIST experiment orchestration. No surrogate accuracy or dataset fallback."""
from copy import deepcopy
import hashlib
import json
import math as _math
from pathlib import Path
import platform
import sys
import time
import uuid
import numpy as np
from ctfm.adapters import engine_capabilities
from .data import load_mnist
from .math import (map_weights, d2d_factors, retention_ratio, summarize, ADC_ORDERS, INPUT_BITS,
                   c2c_factors, c2c_relative_cv_percent_to_ratio, c2c_factor_statistics, observed_range_violation)
from .torch_runner import create_model, train_model, model_layers, Network, evaluate, calibrate, input_ranges

POOL_ORDER=('combined','ltp','ltd','common')
MAPPING_ORDER=('fixed_reference','pair_search')
# The only supported model; the PPA adapter needs the shapes, not the weights.
MNIST_MLP_V1_LAYERS=((784,128),(128,10))
ASSUMPTIONS=[
 {'id':'linear_mac','description':'ID/0.1 V is effective G in a linear MAC approximation; gate-input linearity is not established','evidence_kind':'assumed'},
 {'id':'independent_state_programming','description':'The two differential devices can be independently programmed along each selected measured path','evidence_kind':'assumed'},
 {'id':'digital_bias','description':'Original digital bias, ideal DAC and fixed mapping scale; no gain or drift compensation','evidence_kind':'assumed'},
 {'id':'lognormal_d2d','description':'Mean-one positive lognormal distribution transfers IV-proxy CV to every pulse state; devices and polarities independent','evidence_kind':'assumed'},
 {'id':'manual_lognormal_c2c','description':'Mean-one positive lognormal distribution from a manually assumed relative CV, drawn independently per reprogram/layer/plane; not a measured CTFM cycle-to-cycle distribution (docs/completion-plan-2026-09-21.md P2)','evidence_kind':'assumed'},
 {'id':'retention_ms_to_10s','description':'Millisecond pulse-read G is treated as the 10-second reference state','evidence_kind':'assumed'},
 {'id':'retention_read_bias_transfer','description':'Program fit may transfer across pulse/retention read VGS, including A3/A4/A5; source read biases are retained','evidence_kind':'assumed'},
 {'id':'retention_common_gain','description':'The same Program retention ratio affects both devices and every state; not a state-specific memory-loss model','evidence_kind':'assumed'},
 {'id':'adc_bipolar_grid','description':'Uniform ADC grid per bit plane; a bipolar range can omit exact zero; digital shift-add across bits, digital row sum and bias once','evidence_kind':'assumed'},
 {'id':'unsigned_8bit_bitserial','description':'Activations are unsigned 8 bit driven LSB-first over a fixed 8 cycle schedule with no zero-cycle skipping; only nonnegative pixel and ReLU activations are in scope','evidence_kind':'assumed'},
 {'id':'hidden_range_from_digital_checkpoint','description':'The hidden input range r is the digital checkpoint maximum over the 5k validation split, held fixed across bits, arrays and retention timepoints','evidence_kind':'assumed'},
]


def _json_bytes(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def _sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()


def _save_json(path,value):
    Path(path).write_bytes(_json_bytes(value))
    return _sha(path)


SCHEMA_VERSIONS=('1.2.0','1.3.0')


def _validate(config,profiles):
    from ctfm.profiles import validate_profile
    schema_version=config.get('schema_version')
    if schema_version not in SCHEMA_VERSIONS or config.get('model_id')!='mnist_mlp_v1':raise ValueError('Unsupported experiment/model version')
    seed=config.get('seed')
    if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<=2**32-1:raise ValueError('Explicit uint32 seed required')
    effects=config['effects'];hardware=config['hardware']
    n_reprogram=config.get('n_reprogram')
    if isinstance(n_reprogram,bool) or not isinstance(n_reprogram,int) or not 1<=n_reprogram<=100:raise ValueError('n_reprogram must be an integer 1..100')
    if effects.get('c2c'):
        if schema_version!='1.3.0':raise ValueError('C2C requires schema_version 1.3.0')
    elif n_reprogram!=1:raise ValueError('C2C off requires n_reprogram=1 (a single write)')
    if config['engines'].get('ppa')!='off' or hardware.get('preset_id') is not None:raise ValueError('PPA is unsupported without a validated CTFM preset')
    engine=config['engines']['accuracy'];caps=engine_capabilities()
    if engine not in ('torch_reference','aihwkit_ideal') or not caps[engine]['available']:raise ValueError('Requested accuracy engine is unavailable: '+str(caps.get(engine)))
    if not config['pools'] or len(set(config['pools']))!=len(config['pools']) or any(p not in POOL_ORDER for p in config['pools']):raise ValueError('Invalid pools')
    if not config['mappings'] or len(set(config['mappings']))!=len(config['mappings']) or any(m not in MAPPING_ORDER for m in config['mappings']):raise ValueError('Invalid mappings')
    arrays=config['arrays'];years=config['years']
    if isinstance(arrays,bool) or not isinstance(arrays,int) or not 1<=arrays<=100:raise ValueError('Arrays must be 1..100')
    if not effects['d2d'] and arrays!=1:raise ValueError('D2D off requires one array')
    if not 1<=len(years)<=10 or len(set(years))!=len(years) or 0 not in years or any(isinstance(y,bool) or not isinstance(y,(int,float)) or not _math.isfinite(y) or not 0<=y<=100 for y in years):raise ValueError('Years must be distinct finite values in 0..100 including zero')
    if not effects['retention'] and years!=[0]:raise ValueError('Retention off requires years=[0]')
    # The array is physical, so its size is required whether or not an ADC
    # converts the partial sums; only the converter controls go null.
    if hardware.get('tile_size') not in (64,128,256):raise ValueError('An explicit physical tile size of 64, 128 or 256 is required')
    if effects['adc']:
        if hardware.get('adc_bits') not in range(3,9) or hardware.get('range_policy')!='validation_max_abs':raise ValueError('Unsupported ADC configuration')
        if hardware.get('adc_order') not in ADC_ORDERS:raise ValueError('ADC requires an explicit order: '+', '.join(ADC_ORDERS))
    elif any(hardware.get(k) is not None for k in ('adc_bits','range_policy','adc_order')):raise ValueError('ADC off requires null converter fields; the order does not apply')
    if not 1<=len(profiles)<=5 or len(profiles)!=len(config['profile_refs']):raise ValueError('Profile reference count mismatch')
    refs={(r['id'],r['revision']) for r in config['profile_refs']}
    if len({r['id'] for r in config['profile_refs']})!=len(config['profile_refs']):raise ValueError('Duplicate profile revisions')
    ref_by_key={(r['id'],r['revision']):r for r in config['profile_refs']}
    for profile in profiles:
        m=profile['manifest'];validate_profile(m,profile['states'],published_required=True)
        if (m['profile_id'],m['revision']) not in refs:raise ValueError('Resolved profile does not match requested revision')
        if effects['d2d']:
            d=m['d2d'];cv=d.get('cv')
            if d.get('status')!='available' or cv is None or not _math.isfinite(cv) or cv<0:raise ValueError('D2D requires available measured CV')
        if effects.get('c2c'):
            # Manual assumption, never inherited: every referenced profile revision
            # must state its own cv_percent explicitly (docs/completion-plan P2).
            ref=ref_by_key[(m['profile_id'],m['revision'])];c2c_ref=ref.get('c2c') or {}
            if c2c_ref.get('source')!='manual_assumption':raise ValueError('C2C requires source=manual_assumption on every referenced profile')
            cv_percent=c2c_ref.get('cv_percent')
            if isinstance(cv_percent,bool) or not isinstance(cv_percent,(int,float)) or not _math.isfinite(cv_percent) or cv_percent<0:raise ValueError('C2C requires a finite nonnegative relative CV percent on every referenced profile')
        if effects['retention']:
            r=m['retention'];fit=r.get('program_fit')
            if r.get('status')!='available' or not fit:raise ValueError('Retention requires available Program fit')
            if retention_ratio(fit,0)['status']!='valid':raise ValueError('Retention fit has invalid reference current')
    if len(profiles)*len(config['pools'])*len(config['mappings'])*arrays*n_reprogram*len(years)>2000:raise ValueError('Requested run budget exceeds 2000')


def _execution_config(request):
    """Resolve equivalent JSON integer/UUID representations without editing input."""
    config=deepcopy(request)
    def integer(value):
        return int(value) if type(value) is float and value.is_integer() else value
    for key in ('seed','arrays','n_reprogram'):
        config[key]=integer(config.get(key))
    for key in ('tile_size','adc_bits'):
        config['hardware'][key]=integer(config['hardware'].get(key))
    for ref in config['profile_refs']:
        ref['id']=str(uuid.UUID(ref['id']))
        ref['revision']=integer(ref['revision'])
    if config.get('checkpoint_id') is not None:
        config['checkpoint_id']=str(uuid.UUID(config['checkpoint_id']))
    return config


def run_experiment(config,profiles,output_dir,*,cache_dir,checkpoint_path=None,progress=None,split_seed=20260917):
    """Execute all requested candidates using one trained/reused MNIST checkpoint.

    ``split_seed`` is explicit so server policy cannot silently alter the split.
    Artifacts use relative filenames. Workers own cancellation/process isolation.
    """
    import torch
    started=time.monotonic();requested=deepcopy(config);config=_execution_config(config);_validate(config,profiles)
    if type(split_seed) is float and split_seed.is_integer():split_seed=int(split_seed)
    if not isinstance(split_seed,int) or isinstance(split_seed,bool) or not 0<=split_seed<=2**32-1:raise ValueError('split_seed must be uint32')
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(4);torch.use_deterministic_algorithms(True)
    torch.manual_seed(config['seed'])
    resolved=deepcopy(config)
    resolved['split_seed']=split_seed
    resolved['profiles']=[dict(profile_id=p['manifest']['profile_id'],revision=p['manifest']['revision'],profile_hash=p['manifest']['profile_hash']) for p in profiles]
    resolved_hash=hashlib.sha256(_json_bytes(resolved)).hexdigest()
    _save_json(output_dir/'resolved-config.json',resolved)
    train_images,train_labels,test_images,test_labels,data_sources=load_mnist(cache_dir,progress)
    if len(train_images)!=60000 or len(test_images)!=10000:raise ValueError('Official MNIST dataset sizes required')
    permutation=torch.randperm(60000,generator=torch.Generator().manual_seed(split_seed)).numpy()
    train_idx=permutation[:55000];validation_idx=permutation[55000:]
    split_hash=hashlib.sha256(permutation.astype('<i8').tobytes()).hexdigest()
    np.savez_compressed(output_dir/'split.npz',train_indices=train_idx,validation_indices=validation_idx,test_indices=np.arange(10000))
    dataset_hash=hashlib.sha256(_json_bytes(data_sources)).hexdigest()
    checkpoint_id=config.get('checkpoint_id');training_losses=None
    if checkpoint_path is None:
        if checkpoint_id is not None:raise ValueError('Requested checkpoint was not resolved')
        model,training_losses=train_model(train_images,train_labels,train_idx,config['seed'],progress)
        checkpoint_id=str(uuid.uuid4())
        metadata=dict(checkpoint_id=checkpoint_id,model_id='mnist_mlp_v1',split_seed=split_seed,split_sha256=split_hash,
                      dataset_sha256=dataset_hash,training_seed=config['seed'],epochs=5,optimizer='Adam',learning_rate=.001,batch_size=256,
                      checkpoint_policy='last_epoch',normalization='uint8 / 255',dtype='float32',device='cpu')
        checkpoint_path=output_dir/'checkpoint.pt'
        torch.save(dict(state_dict=model.state_dict(),metadata=metadata),checkpoint_path)
        checkpoint_filename='checkpoint.pt'
    else:
        if checkpoint_id is None:raise ValueError('Checkpoint path requires explicit checkpoint_id')
        checkpoint=torch.load(Path(checkpoint_path),map_location='cpu',weights_only=True)
        metadata=checkpoint['metadata']
        for key,value in dict(checkpoint_id=checkpoint_id,model_id='mnist_mlp_v1',split_seed=split_seed,split_sha256=split_hash,dataset_sha256=dataset_hash).items():
            if metadata.get(key)!=value:raise ValueError('Checkpoint metadata mismatch: '+key)
        model=create_model();model.load_state_dict(checkpoint['state_dict'],strict=True);model.eval()
        checkpoint_filename=None
    digital_layers=model_layers(model)
    # r per layer comes from the digital checkpoint on the validation split only,
    # so every candidate shares one input range and the test set is never used.
    ranges=input_ranges(digital_layers,train_images,train_labels,validation_idx)
    digital_layers=[dict(layer,input_range=ranges[layer['name']]) for layer in digital_layers]
    digital=evaluate(Network(digital_layers),test_images,test_labels)
    runs=[dict(run_id='D0',kind='D0',status='succeeded',**digital,loss_vs_digital_pp=0.)]
    # Digital weights with the same unsigned 8 bit activations: the gap to D0 is
    # the input quantization loss on its own, before any mapping or converter.
    digital_8bit=evaluate(Network(digital_layers,input_bits=INPUT_BITS),test_images,test_labels)
    runs.append(dict(run_id='D1',kind='D1',status='succeeded',**digital_8bit,
                     loss_vs_digital_pp=100*(digital['accuracy']-digital_8bit['accuracy'])))
    np.savez_compressed(output_dir/'trace-test-first-256.npz',images=test_images[:256],labels=test_labels[:256],indices=np.arange(256))
    effects=config['effects'];hardware=config['hardware'];engine=config['engines']['accuracy']
    warnings=[];recommendations=[];array_summaries=[];calibrations=[];candidate_records=[];ppa_source=None
    candidate_number=0;completed=0
    total=len(profiles)*len(config['pools'])*len(config['mappings'])*config['arrays']*config['n_reprogram']*len(config['years'])
    for profile in profiles:
        manifest=profile['manifest'];state_by_id={s['state_id']:s for s in profile['states']};profile_candidates=[]
        c2c_cv_percent=c2c_ratio=None
        if effects.get('c2c'):
            # Manual assumption is per profile revision, never per pool/mapping,
            # so it is resolved once here and reused by every candidate below.
            ref=next(r for r in config['profile_refs'] if r['id']==manifest['profile_id'] and r['revision']==manifest['revision'])
            c2c_cv_percent=ref['c2c']['cv_percent'];c2c_ratio=c2c_relative_cv_percent_to_ratio(c2c_cv_percent)
        for pool in POOL_ORDER:
            if pool not in config['pools']:continue
            pool_info=manifest['pools'].get(pool,{})
            states=[state_by_id[sid] for sid in pool_info.get('state_ids',[]) if sid in state_by_id]
            for mapping in MAPPING_ORDER:
                if mapping not in config['mappings']:continue
                candidate_number+=1;candidate_id='candidate-'+str(candidate_number)
                identity=dict(candidate_id=candidate_id,profile_id=manifest['profile_id'],profile_revision=manifest['revision'],profile_hash=manifest['profile_hash'],pool=pool,mapping=mapping)
                if not pool_info.get('available') or len({s['conductance_s'] for s in states})<2:
                    runs.append(dict(**identity,kind='candidate',status='skipped',reason=pool_info.get('reason') or 'Pool requires two distinct measured conductances'))
                    completed+=config['arrays']*config['n_reprogram']*len(config['years'])
                    if progress:progress('inference',completed,total)
                    continue
                maps=[map_weights(layer['weights'],states,mapping) for layer in digital_layers]
                nominal=[dict(name=layer['name'],weights=mapped['weights'],bias=layer['bias'],
                              g_plus=mapped['g_plus'],g_minus=mapped['g_minus'],scale=mapped['scale'],
                              input_range=layer['input_range'])
                         for layer,mapped in zip(digital_layers,maps)]
                # PPA is a nominal-time estimate, so one assembled engine input is
                # enough; keep the first valid candidate and name it in the result.
                if ppa_source is None:ppa_source=dict(identity=identity,nominal=nominal,states=states)
                nominal_validation=evaluate(Network(nominal,engine,tile_size=hardware['tile_size'],input_bits=INPUT_BITS),train_images,train_labels,validation_idx)
                nominal_test=evaluate(Network(nominal,engine,tile_size=hardware['tile_size'],input_bits=INPUT_BITS),test_images,test_labels)
                nominal_accuracy=nominal_test['accuracy']
                nominal_record=dict(**identity,run_id=candidate_id+'-M0',kind='M0',status='succeeded',**nominal_test,
                                    validation_accuracy=nominal_validation['accuracy'],loss_vs_digital_pp=100*(digital['accuracy']-nominal_accuracy),loss_vs_mapped_pp=0.)
                runs.append(nominal_record);profile_candidates.append(nominal_record)
                payload={};mapping_meta=[]
                for layer,mapped in zip(digital_layers,maps):
                    name=layer['name']
                    for key in ('g_plus','g_minus','plus_index','minus_index'):payload[name+'_'+key]=mapped[key]
                    payload[name+'_bias']=layer['bias'];payload[name+'_scale']=np.array(mapped['scale'])
                    mapping_meta.append(dict(layer=name,scale=mapped['scale'],errors=mapped['errors'],g_min_s=mapped['g_min_s'],g_max_s=mapped['g_max_s'],shape=list(mapped['g_plus'].shape)))
                mapping_filename=candidate_id+'-mapping.npz';np.savez_compressed(output_dir/mapping_filename,**payload)
                mapping_metadata=dict(**identity,layers=mapping_meta,states=states,array_filename=mapping_filename,array_sha256=_sha(output_dir/mapping_filename),orientation='output_by_input',index_semantics='index into states; each row preserves source direction and path')
                _save_json(output_dir/(candidate_id+'-mapping.json'),mapping_metadata)
                bounds=None;calibration_filename=None;calibration_hash=None
                if effects['adc']:
                    bounds=calibrate(nominal,train_images,train_labels,validation_idx,hardware['tile_size'],engine)
                    calibration_filename=candidate_id+'-calibration.json'
                    calibration_hash=_save_json(output_dir/calibration_filename,dict(**identity,bounds=bounds,tile_size=hardware['tile_size'],range_policy='validation_max_abs',adc_order=hardware['adc_order'],source='nominal M0 with the ADC bypassed; complete validation set only',validation_count=5000,split_sha256=split_hash,units='siemens x input bit; physical current is this times VDS',input_ranges=ranges,shared_across='bits, arrays and all retention timepoints; both orders collected in one pass'))
                    calibrations.append(dict(**identity,filename=calibration_filename,sha256=calibration_hash,bounds=bounds))
                candidate_records.append(dict(**identity,mapping_artifact=mapping_filename,mapping_errors=mapping_meta,
                    hardware={**hardware,'calibration_filename':calibration_filename,'calibration_sha256':calibration_hash,'bounds':bounds},
                    c2c=dict(cv_percent=c2c_cv_percent,cv_ratio=c2c_ratio,source='manual_assumption') if effects.get('c2c') else None))
                # year -> {array_index: [accuracy per reprogram]}; a record never
                # counts as its own independent array (docs/spec review).
                samples={str(y):{} for y in sorted(config['years'])}
                for array_index in range(config['arrays']):
                    array_layers=[];array_diag={};array_payload={};seed_records=[]
                    for layer,mapped in zip(digital_layers,maps):
                        name=layer['name'];gs=[]
                        for polarity,key in [('plus','g_plus'),('minus','g_minus')]:
                            if effects['d2d']:
                                factor,seed_info=d2d_factors(mapped[key].shape,manifest['d2d']['cv'],config['seed'],manifest['profile_hash'],array_index,name,polarity)
                                seed_records.append(seed_info)
                            else:factor=np.ones_like(mapped[key])
                            g=mapped[key]*factor;gs.append(g)
                            if effects['d2d']:
                                array_payload[name+'_'+polarity+'_factor']=factor;array_payload[name+'_'+polarity+'_g_s']=g
                            array_diag[name+'_'+polarity]=dict(min_s=float(g.min()),max_s=float(g.max()),outside_observed_fraction=float(np.mean((g<mapped['g_min_s']) | (g>mapped['g_max_s']))),factor_mean=float(factor.mean()),factor_std=float(factor.std(ddof=1)) if factor.size>1 else None)
                        array_layers.append(dict(name=name,weights=mapped['scale']*(gs[0]-gs[1]),bias=layer['bias'],
                                                g_plus=gs[0],g_minus=gs[1],scale=mapped['scale'],
                                                input_range=layer['input_range']))
                    array_filename=None
                    if effects['d2d']:
                        array_filename=candidate_id+'-array-'+str(array_index)+'.npz'
                        np.savez_compressed(output_dir/array_filename,**array_payload)
                        _save_json(output_dir/(candidate_id+'-array-'+str(array_index)+'.json'),dict(**identity,array_index=array_index,seeds=seed_records,diagnostics=array_diag,array_filename=array_filename,array_sha256=_sha(output_dir/array_filename)))
                    for reprogram_index in range(config['n_reprogram']):
                        # G_program = G_nominal * D2D * C2C (docs/completion-plan P2);
                        # D2D is already baked into array_layers above and stays fixed
                        # across every reprogram of this same array. record_layers
                        # aliases array_layers directly when C2C is off, so the off
                        # path is bit-identical to before this feature existed.
                        record_layers=array_layers;c2c_diag=None;record_filename=None
                        if effects.get('c2c'):
                            record_layers=[];c2c_diag={};record_seed_records=[]
                            for layer,mapped in zip(array_layers,maps):
                                name=layer['name'];gs=[]
                                for polarity,key in [('plus','g_plus'),('minus','g_minus')]:
                                    factor,seed_info=c2c_factors(layer[key].shape,c2c_ratio,config['seed'],manifest['profile_hash'],array_index,reprogram_index,name,polarity)
                                    record_seed_records.append(seed_info)
                                    g=layer[key]*factor;gs.append(g)
                                    stats=c2c_factor_statistics(factor)
                                    # Statistics of the factor itself, never of g: g's spread
                                    # also carries each weight's distinct nominal conductance
                                    # and must not be reported as the injected C2C CV.
                                    violation=observed_range_violation(g,mapped['g_min_s'],mapped['g_max_s'])
                                    c2c_diag[name+'_'+polarity]=dict(seed=seed_info['seed'],factor_mean=stats['mean'],factor_std=stats['std'],factor_empirical_cv=stats['empirical_cv'],**violation)
                                record_layers.append(dict(layer,weights=layer['scale']*(gs[0]-gs[1]),g_plus=gs[0],g_minus=gs[1]))
                            record_filename=candidate_id+'-array-'+str(array_index)+'-record-'+str(reprogram_index)+'.json'
                            _save_json(output_dir/record_filename,dict(**identity,array_index=array_index,reprogram_index=reprogram_index,cv_percent=c2c_cv_percent,cv_ratio=c2c_ratio,source='manual_assumption',seeds=record_seed_records,diagnostics=c2c_diag))
                        # Only 1.2.0-identical run_ids when off: n_reprogram==1 is the
                        # only value 1.2.0/C2C-off ever allows, so this suffix is empty
                        # for every existing (non-C2C) result.
                        record_suffix='' if config['n_reprogram']==1 else '-record-'+str(reprogram_index)
                        accuracy_t0=None
                        for year in sorted(config['years']):
                            retention=retention_ratio(manifest['retention']['program_fit'],year) if effects['retention'] else dict(years=0,ratio=1.,status='valid',extrapolated=False)
                            record=dict(**identity,run_id=candidate_id+'-array-'+str(array_index)+record_suffix+'-year-'+str(year),kind='ALL',array_index=array_index,reprogram_index=reprogram_index,years=year,effects=deepcopy(effects),retention=retention,d2d_diagnostics=array_diag if effects['d2d'] else None,c2c_diagnostics=c2c_diag,array_artifact=array_filename,record_artifact=record_filename,calibration_sha256=calibration_hash)
                            if retention['status']=='invalid':
                                record.update(status='invalid',reason=retention['reason'],accuracy=None,loss_vs_digital_pp=None,loss_vs_mapped_pp=None,retention_loss_pp=None)
                            else:
                                # One common gain on both devices, so the pair still reads G+ minus G-.
                                ratio=retention['ratio'];time_layers=[dict(l,weights=l['weights']*ratio,g_plus=l['g_plus']*ratio,g_minus=l['g_minus']*ratio) for l in record_layers]
                                try:
                                    result=evaluate(Network(time_layers,engine,tile_size=hardware['tile_size'],input_bits=INPUT_BITS,
                                                            bits=hardware['adc_bits'] if effects['adc'] else None,
                                                            adc_order=hardware['adc_order'] if effects['adc'] else None,
                                                            bounds=bounds),test_images,test_labels)
                                    accuracy=result['accuracy']
                                    if year==0:accuracy_t0=accuracy
                                    record.update(status='succeeded',**result,loss_vs_digital_pp=100*(digital['accuracy']-accuracy),loss_vs_mapped_pp=100*(nominal_accuracy-accuracy),retention_loss_pp=100*(accuracy_t0-accuracy) if accuracy_t0 is not None else None)
                                    samples[str(year)].setdefault(array_index,[]).append(accuracy)
                                except (ValueError,FloatingPointError,OverflowError) as exc:
                                    record.update(status='invalid',reason=str(exc),accuracy=None,loss_vs_digital_pp=None,loss_vs_mapped_pp=None,retention_loss_pp=None)
                            runs.append(record);completed+=1
                            if progress:progress('inference',completed,total)
                for year in sorted(config['years']):
                    # One value per array (its own mean across reprograms) so a
                    # multiply-reprogrammed array is never counted as several
                    # independent arrays; the per-array reprogram breakdown is kept
                    # separately and only populated when reprogramming is actually used.
                    per_array_means=[float(np.mean(v)) for v in samples[str(year)].values()]
                    array_accuracy=summarize(per_array_means)
                    reprogram_accuracy_by_array=None
                    if config['n_reprogram']>1:
                        # summarize()'s default interpretation ("distribution across
                        # seeded arrays") is right for array_accuracy here, but wrong
                        # if copied onto a per-array entry below, which is a
                        # within-array reprogram distribution, not an across-array
                        # one (04_REVIEW). Override only at these two call sites;
                        # summarize()'s own default text is unchanged everywhere else.
                        array_accuracy=dict(array_accuracy,interpretation="distribution across seeded arrays; each array contributes its own mean over n_reprogram reprograms, not one sample per reprogram")
                        reprogram_accuracy_by_array={}
                        for array_index,values in samples[str(year)].items():
                            entry=summarize(values)
                            entry['interpretation']=f"distribution across the {config['n_reprogram']} reprograms of this one array (array_index={array_index}), not across different arrays"
                            reprogram_accuracy_by_array[str(array_index)]=entry
                    array_summaries.append(dict(**identity,years=year,requested_arrays=config['arrays'],invalid_arrays=config['arrays']-len(per_array_means),accuracy=array_accuracy,
                                                requested_reprogram=config['n_reprogram'],
                                                reprogram_accuracy_by_array=reprogram_accuracy_by_array))
        if profile_candidates:
            best=max(profile_candidates,key=lambda r:r['validation_accuracy'])
            recommendations.append(dict(profile_id=manifest['profile_id'],profile_hash=manifest['profile_hash'],candidate_id=best['candidate_id'],pool=best['pool'],mapping=best['mapping'],validation_accuracy=best['validation_accuracy'],selection='nominal M0 validation accuracy; canonical pool/mapping order breaks ties'))
    if effects['retention']:warnings.append('Retention beyond the measured time range is extrapolation sensitivity, not measured long-term accuracy. No automatic gain compensation.')
    if not engine_capabilities()['aihwkit_ideal']['available']:warnings.append('AIHWKit ideal is unavailable; no AIHWKit parity claim is made for this run.')
    effective=deepcopy(config)
    effective.update(checkpoint_id=checkpoint_id,split_seed=split_seed,candidates=candidate_records,
                     dtype='float32',device='cpu',mapping_scale_policy='fixed_nominal',digital_bias='unchanged',dac='ideal',
                     input_encoding=dict(bits=INPUT_BITS,signedness='unsigned',schedule='LSB-first fixed 8 cycles, zero cycles not skipped',
                                         ranges=ranges,range_source='digital checkpoint maximum over the 5k validation split'),
                     partial_sum_units='siemens x input bit; physical current is this times the measured VDS',
                     effect_owners=dict(d2d='ctfm.simulation.math',retention='ctfm.simulation.math',adc='ctfm.simulation.torch_runner',c2c='ctfm.simulation.math'),
                     disabled_effects=['programming_noise','forward_noise','PCM_drift','compensation','IR_drop','nonlinear_IV','endurance'])
    provenance=dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,torch=str(torch.__version__),
                    deterministic_algorithms=True,cpu_threads=4,dataset=data_sources,dataset_sha256=dataset_hash,
                    split=dict(seed=split_seed,sha256=split_hash,train=55000,validation=5000,test=10000,algorithm='torch.randperm CPU; first 55000 train'),
                    checkpoint=dict(**metadata,sha256=_sha(checkpoint_path)),training_epoch_losses=training_losses,
                    profiles=[dict(manifest=p['manifest']) for p in profiles],engines=engine_capabilities(),
                    code_sha256={str(f.relative_to(Path(__file__).parent.parent)).replace(chr(92),'/'):_sha(f) for folder in (Path(__file__).parent,Path(__file__).parent.parent/'adapters') for f in folder.glob('*.py')},
                    d2d_seed_policy='SHA256(compact UTF-8 JSON [root_seed,profile_hash,array_index,layer,polarity]) first 8 bytes big-endian uint64; NumPy PCG64 standard_normal row-major',
                    trace=dict(filename='trace-test-first-256.npz',sha256=_sha(output_dir/'trace-test-first-256.npz'),count=256,source='first 256 official test examples; also the PPA activation trace source'))
    used_assumptions=[a for a in ASSUMPTIONS if (effects['d2d'] or a['id']!='lognormal_d2d') and (effects['retention'] or not a['id'].startswith('retention_')) and (effects['adc'] or a['id']!='adc_bipolar_grid') and (effects.get('c2c') or a['id']!='manual_lognormal_c2c')]
    # Ask the adapter rather than hard-coding the refusal, so the result carries
    # the engine build state, the preset decision and the structural model
    # differences instead of an empty mismatch list.
    from ctfm.adapters.neurosim import build_engine_inputs,ppa_result as _ppa_result
    ppa_inputs=None
    if ppa_source is not None:
        # Capture each layer's input from the same trace the result records, using
        # the nominal network so the engine sees exactly the mapped weights.
        recorded=[]
        trace_batch=torch.as_tensor(test_images[:256],dtype=torch.float32)/255.
        with torch.inference_mode():Network(ppa_source['nominal'],'torch_reference',tile_size=hardware['tile_size'],input_bits=INPUT_BITS)(trace_batch,record_inputs=recorded)
        try:
            ppa_inputs=build_engine_inputs(ppa_source['nominal'],recorded,output_dir/'neurosim-inputs',
                                           input_bits=8,synapse_bit=8,profile_states=ppa_source['states'])
        except ValueError as exc:
            warnings.append('NeuroSim engine inputs could not be assembled ('+type(exc).__name__+')')
    _decision=_ppa_result(MNIST_MLP_V1_LAYERS,inputs=ppa_inputs,out_dir=output_dir,
                          hardware={**hardware,'input_bits':INPUT_BITS} if effects['adc'] else None)
    if ppa_source is not None:_decision['candidate']=ppa_source['identity']
    # Keep the list as well as the joined text: individual reasons contain their
    # own semicolons, so the joined string cannot be split back apart.
    ppa=dict(status=_decision['status'],reasons=list(_decision['reasons']),
             reason=' | '.join(_decision['reasons']) or None,
             area_m2=_decision['area_m2'],energy_j_per_inference=_decision['energy_j_per_inference'],
             latency_s_per_inference=_decision['latency_s_per_inference'],
             model_mismatches=_decision['model_mismatches'],raw_output=_decision['raw_output'],
             engine=_decision['engine'],preset=_decision['preset'],
             preset_artifact=_decision.get('preset_artifact'),candidate=_decision.get('candidate'),
             coverage=_decision.get('coverage'),schedule_check=_decision.get('schedule_check'),
             engine_totals=_decision.get('engine_totals'),build=_decision.get('build'),
             blocking_reasons=list(_decision.get('blocking_reasons') or []),
             incomplete_reasons=list(_decision.get('incomplete_reasons') or []),
             normalization=_decision.get('normalization'),conductance=_decision.get('conductance'),
             trace_sample=_decision['trace_sample'],time_basis=_decision['time_basis'])
    candidate_by_id={c['candidate_id']:c for c in candidate_records}
    for run in runs:
        run['engine']='torch_reference' if run['kind'] in ('D0','D1') else engine
        run['profile_ref']=dict(id=run['profile_id'],revision=run['profile_revision']) if 'profile_id' in run else None
        run['ppa']=deepcopy(ppa)
        candidate=candidate_by_id.get(run.get('candidate_id'))
        run['mapping_errors']=candidate['mapping_errors'] if candidate else None
        run['hardware']=deepcopy(candidate['hardware']) if candidate and run['kind']=='ALL' else dict(tile_size=None,adc_bits=None,adc_order=None,range_policy=None,preset_id=None)
    completed_runs=sum(r['kind']=='ALL' and r['status']=='succeeded' for r in runs)
    failed_runs=sum(r['kind']=='ALL' and r['status']=='invalid' for r in runs)
    skipped_runs=sum(r['status']=='skipped' for r in runs)*config['arrays']*config['n_reprogram']*len(config['years'])
    if completed_runs+failed_runs+skipped_runs!=total:raise RuntimeError('Experiment run accounting mismatch')
    result=dict(schema_version=config['schema_version'],status='partial' if failed_runs or skipped_runs else 'succeeded',requested_config=requested,resolved_config=resolved,resolved_config_hash=resolved_hash,effective_config=effective,
                checkpoint_id=checkpoint_id,checkpoint_filename=checkpoint_filename,provenance=provenance,assumptions=used_assumptions,warnings=warnings,runs=runs,
                summary=dict(digital_accuracy=digital['accuracy'],recommendations=recommendations,array_statistics=array_summaries,
                             requested=total,completed=completed_runs,failed=failed_runs,skipped=skipped_runs,
                             record_counts=dict(succeeded=sum(r['status']=='succeeded' for r in runs),invalid=sum(r['status']=='invalid' for r in runs),skipped=sum(r['status']=='skipped' for r in runs)),elapsed_seconds=time.monotonic()-started),
                ppa=ppa)
    _save_json(output_dir/'result.json',result)
    return result
