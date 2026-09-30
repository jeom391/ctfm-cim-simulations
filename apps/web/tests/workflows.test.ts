import {test} from 'node:test';
import assert from 'node:assert/strict';
import {activeResolutions,canPublishPending,commonSettings,compositionKey,draftUpdate,editableCard,eligibleStateIds,experimentNeedsReload,profileRevisionPayload,publishedCard,recognizedChoices,resolutionsFor,restoreCommon,reviewKey} from '../src/lib/workflows.ts';

test('comparison completion refreshes experiment details after running state ends',()=>{
 assert.equal(experimentNeedsReload('running','temporary'),true);
 assert.equal(experimentNeedsReload('running','saved'),true);
 assert.equal(experimentNeedsReload('running','running'),false);
 assert.equal(experimentNeedsReload('temporary','saved'),false);
});

test('comparison settings keep the fixed scope and independent effect counts',()=>{
 const settings=commonSettings({adc:true,adcBits:5,d2d:false,c2c:true,retention:false,arrays:8,nReprogram:3,years:'0, 10',pools:['combined'],mappings:['fixed_reference'],engine:'torch_reference',checkpoint:'',seed:0});
 assert.deepEqual(settings.hardware,{tile_size:64,adc_bits:5,adc_order:'adc_then_subtract',range_policy:'validation_max_abs',preset_id:null});
 assert.deepEqual(settings.effects,{adc:true,d2d:false,c2c:true,retention:false});
 assert.equal(settings.arrays,1);assert.equal(settings.n_reprogram,3);assert.deepEqual(settings.years,[0]);
 assert.deepEqual(settings.engines,{accuracy:'torch_reference',ppa:'off'});assert.equal(settings.seed,0);
 assert.equal('profile_refs' in settings,false);
});

test('draft serialization sends request-only card fields and current version',()=>{
 const card={card_id:'00000000-0000-4000-8000-000000000001',display_name:'A1',profile_ref:{id:'00000000-0000-4000-8000-000000000002',revision:2},state_analysis_id:'00000000-0000-4000-8000-000000000003',c2c_approved_assumption:true,cross_condition_acknowledged:true,status:'succeeded',reason:'old',runs:[{accuracy:0.9}]};
 assert.deepEqual(editableCard(card),{card_id:card.card_id,display_name:'A1',profile_ref:card.profile_ref,state_analysis_id:card.state_analysis_id,c2c_approved_assumption:true,cross_condition_acknowledged:true});
 assert.deepEqual(draftUpdate(7,{schema_version:'1.4.0'},[card]),{expected_version:7,common_settings:{schema_version:'1.4.0'},cards:[editableCard(card)]});
});

test('reopening a server draft restores effect controls without inventing absent measurements',()=>{
 const form=restoreCommon({effects:{adc:true,c2c:true,d2d:false,retention:false},hardware:{tile_size:64,adc_bits:7,adc_order:'adc_then_subtract'},n_reprogram:4,arrays:1,years:[0],seed:0,engines:{accuracy:'aihwkit_ideal',ppa:'off'}});
 assert.equal(form.adcBits,7);assert.equal(form.c2c,true);assert.equal(form.nReprogram,4);assert.equal(form.seed,0);
 assert.equal(form.d2d,false);assert.equal(form.arrays,1);
});

test('new comparisons enable 5-bit ADC while an explicit saved OFF remains OFF',()=>{
 const fresh=restoreCommon({});
 assert.equal(fresh.adc,true);assert.equal(fresh.adcBits,5);
 assert.equal(restoreCommon({effects:{adc:false}}).adc,false);
});

test('selecting one published card keeps its own immutable analysis links and resets C2C approval',()=>{
 const base={card_id:'card-1',display_name:'A1 card',c2c_approved_assumption:true,cross_condition_acknowledged:true};
 const p={profile_id:'profile-1',revision:2,condition_id:'A1',pools:{combined:{state_ids:['s1','s2']}},analysis_links:{state:{analysis_id:'state-1'},d2d:{analysis_id:'d2d-1'},c2c:{analysis_id:'c2c-1'}}};
 const card=publishedCard(base,p);
 assert.equal(card.profile_ref.id,'profile-1');assert.equal(card.profile_ref.revision,2);
 assert.deepEqual(card.selected_state_ids,['s1','s2']);assert.equal(card.d2d_analysis_id,'d2d-1');assert.equal(card.retention_analysis_id,null);assert.equal(card.c2c_analysis_id,'c2c-1');
 assert.equal(card.c2c_approved_assumption,false);assert.equal(card.cross_condition_acknowledged,false);
 assert.equal(base.c2c_approved_assumption,true);
});

test('replacing C2C on one card revises only that link and retains base state and other effects',()=>{
 const base={profile_id:'profile-1',revision:2,condition_id:'A1',pools:{combined:{state_ids:['s1','s2']}},analysis_links:{state:{analysis_id:'state-1'},d2d:{analysis_id:'d2d-1'}}};
 const card={card_id:'card-1',display_name:'A1 revised',state_analysis_id:'state-1',selected_state_ids:['s1','s2'],d2d_analysis_id:'d2d-1',retention_analysis_id:null,c2c_analysis_id:'c2c-new',c2c_approved_assumption:false,cross_condition_acknowledged:false};
 assert.deepEqual(profileRevisionPayload(card,base),{base_revision:2,display_name:'A1 revised',c2c_analysis_id:'c2c-new'});
});

test('review belongs to one card and immutable draft revision, and stale composition cannot publish',()=>{
 const a={card_id:'a',display_name:'A1',condition_id:'A1',state_analysis_id:'s1',selected_state_ids:['x','y'],c2c_approved_assumption:false,cross_condition_acknowledged:false};
 const b={...a,card_id:'b',display_name:'A3',condition_id:'A3',state_analysis_id:'s3'};
 const pa={profile_id:'p1',revision:1,profile_hash:'hash-a'},pb={profile_id:'p3',revision:1,profile_hash:'hash-b'};
 const pendingA={profile:pa,sourceKey:compositionKey(a,null)},pendingB={profile:pb,sourceKey:compositionKey(b,null)};
 const reviews={[reviewKey(a.card_id,pa)]:{reviewer:'Alice',note:'A1 states checked',reviewed:true}};
 assert.equal(canPublishPending(a,null,pendingA,reviews),true);
 assert.equal(canPublishPending(b,null,pendingB,reviews),false);
 assert.equal(canPublishPending({...a,selected_state_ids:['x','z']},null,pendingA,reviews),false);
 assert.equal(canPublishPending(a,null,{profile:{...pa,revision:2},sourceKey:pendingA.sourceKey},reviews),false);
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
