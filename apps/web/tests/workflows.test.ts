import {test} from 'node:test';
import assert from 'node:assert/strict';
import {commonSettings,draftUpdate,editableCard,profileRevisionPayload,publishedCard,recognizedChoices,resolutionsFor,restoreCommon} from '../src/lib/workflows.ts';

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

test('recognition leaves IV alternatives unselected and sends chosen proposals unchanged',()=>{
 const first={recognition_id:'r',kind:'iv',inputs:[{file_id:'f',selection:{type:'iv_block',block:0,segment:0}}],settings:{}};
 const second={recognition_id:'r',kind:'iv',inputs:[{file_id:'f',selection:{type:'iv_block',block:1,segment:2}}],settings:{}};
 assert.deepEqual(recognizedChoices([first,second],new Set([1])),[second]);
 assert.equal(recognizedChoices([first,second],new Set()).length,0);
});

test('resolution includes only operator-entered uncertain fields and requires evidence',()=>{
 assert.deepEqual(resolutionsFor([{file_id:'f',reason:'Operator log',condition_id:'A3',units:{vgs_v:'V'}}]),[{file_id:'f',reason:'Operator log',condition_id:'A3',units:{vgs_v:'V'}}]);
 assert.throws(()=>resolutionsFor([{file_id:'f',reason:' ',condition_id:'A3'}]));
});
