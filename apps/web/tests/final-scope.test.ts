import {test} from 'node:test';
import assert from 'node:assert/strict';
import {cardProblems,commonSettings,d2dPairDevices,defaultCommon,toCsv} from '../src/lib/workflows.ts';

const card=(extra={})=>({card_id:'c1',display_name:'A1',c2c_approved_assumption:false,cross_condition_acknowledged:false,profile_ref:{id:'p',revision:1},...extra});

test('effects OFF never require a CV; ON requires only that effect, and 0 counts as entered',()=>{
 assert.deepEqual(cardProblems([card()],{...defaultCommon,c2c:false,d2d:false}),{});
 assert.deepEqual(cardProblems([card()],{...defaultCommon,c2c:true}),{c1:['C2C가 켜져 있어 C2C CV(%)가 필요합니다.']});
 assert.deepEqual(cardProblems([card({manual_c2c_cv_percent:0})],{...defaultCommon,c2c:true}),{});
 assert.deepEqual(cardProblems([card({manual_c2c_cv_percent:0})],{...defaultCommon,c2c:true,d2d:true}),{c1:['D2D가 켜져 있어 D2D CV(%)가 필요합니다.']});
});

test('a card without its LTM upload or name blocks the run, and an in-flight upload is reported as such',()=>{
 assert.deepEqual(cardProblems([card({profile_ref:null,display_name:' '})],defaultCommon),{c1:['소자 이름을 입력하세요.','LTP와 LTD 파일을 올리세요.']});
 assert.deepEqual(cardProblems([card({profile_ref:null})],defaultCommon,{c1:{busy:true}}),{c1:['LTM 파일을 처리하는 중입니다.']});
});

test('more than five cards are allowed by the client; settings carry no card count',()=>{
 const cards=Array.from({length:7},(_,i)=>card({card_id:'c'+i}));
 assert.deepEqual(cardProblems(cards,defaultCommon),{});
 assert.equal('profile_refs' in commonSettings(defaultCommon),false);
});

test('D2D pair labels name the file, never a guessed device number, and cite the snapshot folder when known',()=>{
 const [a,b]=d2dPairDevices([{file_id:'1',name:'_26CTFM_A5_IdVg_sweep_223_15V_.xlsx',snapshot_paths:['D2D/A5/_26CTFM_A5_IdVg_sweep_223_15V_.xlsx','IV Sweep/A5/x.xlsx']},{file_id:'2',name:'x.xlsx'}]);
 assert.equal(a.device_id,'소자 1 (_26CTFM_A5_IdVg_sweep_223_15V_.xlsx)');
 assert.match(a.identity_evidence,/D2D\/A5\//);
 assert.equal(b.identity_evidence,'사용자가 서로 다른 물리 소자의 파일로 지정');
 assert.notEqual(a.device_id,b.device_id);
});

test('result CSV keeps the shown values, quotes commas and neutralises formula-like text',()=>{
 const csv=toCsv([{프로필:'A1, 2',정확도:'96.12%','변화':-0.5},{프로필:'=cmd'}]);
 assert.ok(csv.startsWith('﻿프로필,정확도,변화\r\n'));
 assert.ok(csv.includes('"A1, 2",96.12%,-0.5\r\n'));
 assert.ok(csv.includes("'=cmd,,\r\n"));
});
