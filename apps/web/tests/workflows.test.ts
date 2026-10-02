import {test} from 'node:test';
import assert from 'node:assert/strict';
import {activeResolutions,commonSettings,draftUpdate,editableCard,eligibleStateIds,experimentNeedsReload,isLegacyRetentionRecord,recognizedChoices,resolutionsFor,restoreCommon} from '../src/lib/workflows.ts';

test('a record that ever used Retention renders via the legacy full table, a new one via the simplified screen',()=>{
 // Developer-side check for the compatibility branch itself (no historical Retention record exists
 // in the current verification storage to open live -- this pins the decision logic instead).
 assert.equal(isLegacyRetentionRecord({common_settings:{effects:{retention:true},years:[0]}}),true);
 assert.equal(isLegacyRetentionRecord({common_settings:{effects:{retention:false},years:[0,10]}}),true);
 assert.equal(isLegacyRetentionRecord({common_settings:{effects:{retention:false},years:[0]}}),false);
 assert.equal(isLegacyRetentionRecord({common_settings:{effects:{adc:true,c2c:true,d2d:true}}}),false);
 assert.equal(isLegacyRetentionRecord({}),false);
});

test('comparison completion refreshes experiment details after running state ends',()=>{
 assert.equal(experimentNeedsReload('running','temporary'),true);
 assert.equal(experimentNeedsReload('running','saved'),true);
 assert.equal(experimentNeedsReload('running','running'),false);
 assert.equal(experimentNeedsReload('temporary','saved'),false);
});

test('comparison settings keep the fixed scope, independent effect counts, and fixed engine/pools/mappings/seed',()=>{
 // Pools, mappings, accuracy engine and seed are no longer user choices (simplified flow): they are
 // always this one validated combination, and the engine is always aihwkit_ideal -- never a silent
 // torch_reference substitute. Only ADC/D2D/C2C on-off and their repeat counts come from the form.
 const settings=commonSettings({adc:true,adcBits:5,d2d:false,c2c:true,arrays:8,nReprogram:3});
 assert.deepEqual(settings.hardware,{tile_size:64,adc_bits:5,adc_order:'adc_then_subtract',range_policy:'validation_max_abs',preset_id:null});
 assert.deepEqual(settings.effects,{adc:true,d2d:false,c2c:true,retention:false});
 assert.equal(settings.arrays,1);assert.equal(settings.n_reprogram,3);assert.deepEqual(settings.years,[0]);
 assert.deepEqual(settings.pools,['combined']);assert.deepEqual(settings.mappings,['fixed_reference']);
 assert.deepEqual(settings.engines,{accuracy:'aihwkit_ideal',ppa:'off'});assert.equal(settings.checkpoint_id,null);
 assert.equal(typeof settings.seed,'number');
 assert.equal('profile_refs' in settings,false);
});

test('retention non-ideality is always off for this new simulation, even for a legacy draft that had it on',()=>{
 // Not a UI-only removal: a draft saved before this scope change (or any other caller) may still
 // carry effects.retention:true / a years list. restoreCommon() drops both fields entirely, and
 // commonSettings() hardcodes retention:false, years:[0] regardless of what is passed in -- so a
 // reopened legacy draft self-heals on its next autosave instead of silently resubmitting it (the
 // server rejects it either way; see product_policy.py's own rejection test).
 const legacy=restoreCommon({effects:{adc:true,c2c:false,d2d:false,retention:true},hardware:{tile_size:64,adc_bits:5,adc_order:null},years:[0,10],seed:1,engines:{accuracy:'torch_reference',ppa:'off'}});
 assert.equal('retention' in legacy,false);
 assert.equal('years' in legacy,false);
 const settings=commonSettings(legacy);
 assert.equal(settings.effects.retention,false);
 assert.deepEqual(settings.years,[0]);
});

test('manual D2D CV round-trips through editableCard like the existing manual C2C CV',()=>{
 const card={card_id:'card-1',display_name:'A1',profile_ref:{id:'profile-1',revision:1},manual_c2c_cv_percent:5,manual_d2d_cv_percent:3,c2c_approved_assumption:false,cross_condition_acknowledged:false,status:'draft',reason:null,runs:[]};
 const reopened=editableCard(card as never);
 assert.equal(reopened.manual_c2c_cv_percent,5);
 assert.equal(reopened.manual_d2d_cv_percent,3);
});

test('draft serialization sends request-only card fields and current version',()=>{
 const card={card_id:'00000000-0000-4000-8000-000000000001',display_name:'A1',profile_ref:{id:'00000000-0000-4000-8000-000000000002',revision:2},state_analysis_id:'00000000-0000-4000-8000-000000000003',c2c_approved_assumption:true,cross_condition_acknowledged:true,status:'succeeded',reason:'old',runs:[{accuracy:0.9}]};
 assert.deepEqual(editableCard(card),{card_id:card.card_id,display_name:'A1',profile_ref:card.profile_ref,base_profile_ref:card.profile_ref,state_analysis_id:card.state_analysis_id,c2c_approved_assumption:true,cross_condition_acknowledged:true});
 assert.deepEqual(draftUpdate(7,{schema_version:'1.4.0'},[card]),{expected_version:7,common_settings:{schema_version:'1.4.0'},cards:[editableCard(card)]});
});

test('reopening a server draft restores effect controls without inventing absent measurements',()=>{
 const form=restoreCommon({effects:{adc:true,c2c:true,d2d:false,retention:false},hardware:{tile_size:64,adc_bits:7,adc_order:'adc_then_subtract'},n_reprogram:4,arrays:1,years:[0],seed:0,engines:{accuracy:'aihwkit_ideal',ppa:'off'}});
 assert.equal(form.adcBits,7);assert.equal(form.c2c,true);assert.equal(form.nReprogram,4);
 assert.equal(form.d2d,false);assert.equal(form.arrays,1);
 assert.equal('seed' in form,false);assert.equal('engine' in form,false);assert.equal('checkpoint' in form,false);assert.equal('pools' in form,false);assert.equal('mappings' in form,false);
});

test('new comparisons enable 5-bit ADC while an explicit saved OFF remains OFF',()=>{
 const fresh=restoreCommon({});
 assert.equal(fresh.adc,true);assert.equal(fresh.adcBits,5);
 assert.equal(restoreCommon({effects:{adc:false}}).adc,false);
});

test('base_profile_ref survives a reload/clone round trip for a record that already set it directly',()=>{
 // Reproduces the originally reported bug: refreshing the page (or cloning) used to reset the
 // client-only "base to revise from" reference. editableCard() is exactly what persist()/draftUpdate
 // send, and what a CardResult from GET/clone is narrowed back down to, so round-tripping a card
 // through it must preserve an explicitly-set base_profile_ref even once profile_ref is cleared.
 // (The simplified upload flow itself never sets base_profile_ref -- every upload is a brand-new
 // profile identity -- but an older saved comparison may still carry one, and must keep working.)
 const card={card_id:'card-1',display_name:'A1',profile_ref:{id:'profile-1',revision:3},base_profile_ref:{id:'profile-1',revision:3},c2c_approved_assumption:false,cross_condition_acknowledged:false,status:'draft',reason:null,candidate_ids:[],runs:[]};
 const reopened=editableCard(card as never);
 assert.deepEqual(reopened.base_profile_ref,{id:'profile-1',revision:3});
 const revised={...reopened,profile_ref:null};
 assert.deepEqual(revised.base_profile_ref,{id:'profile-1',revision:3});
});

test('a pre-fix saved record with only profile_ref recovers base_profile_ref from it on reopen',()=>{
 // A comparison saved before base_profile_ref existed has profile_ref but the key is simply
 // absent (not null) -- exactly what a server response for an old record looks like.
 const oldRecord={card_id:'card-1',display_name:'A1',profile_ref:{id:'profile-9',revision:4},condition_id:'A1',
  state_analysis_id:'state-1',selected_state_ids:['s1'],c2c_analysis_id:'c2c-1',
  c2c_approved_assumption:false,cross_condition_acknowledged:false,status:'succeeded',reason:null,runs:[]};
 assert.equal('base_profile_ref' in oldRecord,false);
 const reopened=editableCard(oldRecord as never);
 assert.deepEqual(reopened.base_profile_ref,{id:'profile-9',revision:4});
 // Replacing an analysis link nulls profile_ref (it names a revision that no longer matches the
 // card); the recovered base must survive that so compose() still targets the same profile ID.
 const revised={...reopened,profile_ref:null,c2c_analysis_id:'c2c-2'};
 assert.deepEqual(revised.base_profile_ref,{id:'profile-9',revision:4});
});

test('bulk state selection uses the same eligible observed rows as individual checkboxes',()=>{
 const rows=[{state_id:'ltp',conductance_s:0.01},{state_id:'ltd',conductance_s:0.02},{state_id:'zero',conductance_s:0,exclusion_reason:'nonpositive_conductance'},{state_id:'negative',conductance_s:-1},{state_id:'',conductance_s:0.1}];
 assert.deepEqual(eligibleStateIds(rows),['ltp','ltd']);
});

test('recognition leaves IV alternatives unselected and sends chosen proposals unchanged',()=>{
 const first={recognition_id:'r',kind:'iv',inputs:[{file_id:'f',selection:{type:'iv_block',block:0,segment:0}}],settings:{}};
 const second={recognition_id:'r',kind:'iv',inputs:[{file_id:'f',selection:{type:'iv_block',block:1,segment:2}}],settings:{}};
 assert.deepEqual(recognizedChoices([first,second],new Set([1])),[second]);
 assert.equal(recognizedChoices([first,second],new Set()).length,0);
});

test('clear pulse pairs need one enqueue action without five individual confirmations',()=>{
 const pulse=Array.from({length:5},(_,i)=>({recognition_id:'plan',kind:'pulse_states',inputs:[{file_id:`ltp-${i}`},{file_id:`ltd-${i}`}],settings:{}}));
 const c2c={recognition_id:'plan',kind:'c2c_detrended',inputs:[{file_id:'c2c-a3'}],settings:{}};
 const retention={recognition_id:'plan',kind:'retention',inputs:[{file_id:'retention'}],settings:{}};
 const iv={recognition_id:'plan',kind:'iv',inputs:[{file_id:'iv',selection:{type:'iv_block',block:4,segment:1}}],settings:{}};
 const requests=[...pulse,c2c,retention,iv];
 assert.deepEqual(recognizedChoices(requests,new Set()),[...pulse,c2c,retention]);
 assert.deepEqual(recognizedChoices(requests,new Set([7])),requests);
 assert.deepEqual(recognizedChoices(requests,new Set([7]),new Set([0,1,2,3,4,5,6])),[iv]);
});

test('resolution includes only operator-entered uncertain fields and requires evidence',()=>{
 assert.deepEqual(resolutionsFor([{file_id:'f',reason:'Operator log',condition_id:'A3',units:{vgs_v:'V'}}]),[{file_id:'f',reason:'Operator log',condition_id:'A3',units:{vgs_v:'V'}}]);
 assert.throws(()=>resolutionsFor([{file_id:'f',reason:' ',condition_id:'A3'}]));
});

test('a replacement upload serializes only its active batch, ignoring old choices and unfinished reasons',()=>{
 const first={'first-ltp':{reason:'first acquisition',measurement_group:'first'},'first-ltd':{reason:'',measurement_group:'first'}};
 assert.deepEqual(activeResolutions(['first-ltp'],first),[{file_id:'first-ltp',reason:'first acquisition',measurement_group:'first'}]);
 const second={...first,'second-ltp':{reason:'second acquisition',measurement_group:'second'},'second-ltd':{reason:'second acquisition',measurement_group:'second'}};
 assert.deepEqual(activeResolutions(['second-ltp','second-ltd'],second),[
  {file_id:'second-ltp',reason:'second acquisition',measurement_group:'second'},
  {file_id:'second-ltd',reason:'second acquisition',measurement_group:'second'},
 ]);
});

test('re-recognizing the same Retention batch keeps all four independent units and source facts',()=>{
 const entered={'retention-new':{reason:'operator checked sheet',source_label:'R1',read_vgs_v:0,units:{erase_time_s:'ms',erase_id_a:'uA',program_time_s:'s',program_id_a:'nA'}}};
 const expected=[{file_id:'retention-new',reason:'operator checked sheet',source_label:'R1',read_vgs_v:0,units:{erase_time_s:'ms',erase_id_a:'uA',program_time_s:'s',program_id_a:'nA'}}];
 assert.deepEqual(activeResolutions(['retention-new'],entered),expected);
 assert.deepEqual(activeResolutions(['retention-new'],entered),expected);
});
