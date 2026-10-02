import type {components} from './api/generated';

export type Card = components['schemas']['ComparisonCard'];
export type CardResult = components['schemas']['ComparisonCardResult'];
export type Comparison = components['schemas']['ComparisonResult'];
export type Recognition = components['schemas']['RecognitionResult'];
export type Resolution = components['schemas']['RecognitionResolution'];
export type Proposal = components['schemas']['AnalysisRequest'];

// A saved comparison that ever used Retention (effects.retention, or a years list longer than the
// fixed [0] every new comparison sends) renders via the old full table + plot.png instead of the
// new simplified screen -- distinguished, never deleted. Pure/exported so this branch decision is
// unit-testable without a live historical record.
export function isLegacyRetentionRecord(record:{common_settings?:Record<string,unknown>}):boolean{
 const settings=(record.common_settings||{}) as {effects?:{retention?:boolean};years?:number[]};
 return !!settings.effects?.retention||(settings.years?.length||1)>1;
}

// Retention non-ideality selection/application is out of scope for this new simulation (measurement
// analysis and its extrapolation queries elsewhere are unaffected): there is deliberately no form
// field for it, and commonSettings() always emits effects.retention:false, years:[0] so a legacy
// draft saved before this scope change can never resubmit it -- the server rejects it either way
// (see packages/contracts/product_policy.py), but the UI must not offer it at all.
//
// Pools/mappings/engine/checkpoint/seed are no longer user choices either (simplified flow,
// 2026-10): pools+mappings are fixed to the one validated combination (combined/fixed_reference),
// the accuracy engine is fixed to aihwkit_ideal (torch_reference must never be a silent substitute
// -- an unavailable engine surfaces as a blocked-card error instead, see Comparison.tsx), and the
// seed is a fixed internal constant. Full determinism (same seed, same split, same deterministic
// training) means every run reproduces the identical checkpoint without the user ever naming one,
// which is what "same checkpoint across every profile and ADC condition" actually requires.
export interface CommonForm {adc:boolean;adcBits:number;d2d:boolean;arrays:number;c2c:boolean;nReprogram:number}
export const defaultCommon:CommonForm={adc:true,adcBits:5,d2d:false,arrays:1,c2c:false,nReprogram:1};
const FIXED_SEED=20260917;
const FIXED_ENGINE='aihwkit_ideal';

export function commonSettings(form:CommonForm){
 if(form.adc&&(!Number.isInteger(form.adcBits)||form.adcBits<3||form.adcBits>8))throw new Error('ADC는 3~8 bit여야 합니다.');
 if(form.d2d&&(!Number.isInteger(form.arrays)||form.arrays<1||form.arrays>100))throw new Error('D2D 배열 반복 횟수는 1~100이어야 합니다.');
 if(form.c2c&&(!Number.isInteger(form.nReprogram)||form.nReprogram<1||form.nReprogram>100))throw new Error('C2C 재기록 반복 횟수는 1~100이어야 합니다.');
 return {schema_version:'1.4.0',model_id:'mnist_mlp_v1',checkpoint_id:null,pools:['combined'],mappings:['fixed_reference'],effects:{adc:form.adc,d2d:form.d2d,c2c:form.c2c,retention:false},arrays:form.d2d?form.arrays:1,n_reprogram:form.c2c?form.nReprogram:1,years:[0],seed:FIXED_SEED,hardware:{tile_size:64,adc_bits:form.adc?form.adcBits:null,adc_order:form.adc?'adc_then_subtract':null,range_policy:form.adc?'validation_max_abs':null,preset_id:null},engines:{accuracy:FIXED_ENGINE,ppa:'off'}};
}

export function restoreCommon(raw:Record<string,unknown>):CommonForm{
 const effects=(raw.effects||{}) as Record<string,boolean>,hardware=(raw.hardware||{}) as Record<string,unknown>;
 return {...defaultCommon,adc:effects.adc??defaultCommon.adc,d2d:effects.d2d??false,c2c:effects.c2c??false,adcBits:typeof hardware.adc_bits==='number'?hardware.adc_bits:5,arrays:typeof raw.arrays==='number'?raw.arrays:1,nReprogram:typeof raw.n_reprogram==='number'?raw.n_reprogram:1};
}

const cardKeys=['card_id','display_name','profile_ref','base_profile_ref','condition_id','state_analysis_id','selected_state_ids','d2d_analysis_id','retention_analysis_id','c2c_analysis_id','c2c_approved_assumption','cross_condition_acknowledged','manual_c2c_cv_percent','manual_d2d_cv_percent'] as const;
export function editableCard(card:CardResult|Card):Card {
 const next=Object.fromEntries(cardKeys.filter(k=>k in card).map(k=>[k,card[k]])) as unknown as Card;
 // A record saved before base_profile_ref existed has only profile_ref; recover the same value as
 // the revise-from base rather than leaving it unset. Dead for the simplified upload flow itself
 // (every upload makes a brand-new profile identity, never a revision of an existing one), but kept
 // so an older saved comparison that still carries both fields round-trips unchanged.
 if(!next.base_profile_ref&&next.profile_ref)next.base_profile_ref=next.profile_ref;
 return next;
}
export function draftUpdate(expected_version:number,common_settings:Record<string,unknown>,cards:(Card|CardResult)[]){return {expected_version,common_settings,cards:cards.map(editableCard)};}
export function createDraftSaver<T,R>(read:()=>{token:number;value:T}|null,save:(value:T)=>Promise<R>,onSaved:(result:R,token:number)=>void){
 let pending:Promise<void>|null=null;
 return {async flush(){
  while(true){
   if(pending){await pending;continue;}
   const snapshot=read();if(!snapshot)return;
   pending=save(snapshot.value).then(result=>onSaved(result,snapshot.token)).finally(()=>{pending=null;});
   await pending;
  }
 }};
}
export function recognizedChoices(requests:Proposal[],selected:Set<number>,submitted:Set<number>=new Set()):Proposal[]{return requests.filter((p,i)=>!submitted.has(i)&&(p.kind!=='iv'||selected.has(i)));}
export function eligibleStateIds(states:ReadonlyArray<{state_id?:unknown;conductance_s?:unknown}>):string[]{return states.map(row=>String(row.state_id||'')).filter((id,i)=>!!id&&Number(states[i].conductance_s)>0);}
export function experimentNeedsReload(before:string,after:string){return before==='running'&&after!=='running';}
export function resolutionsFor(entries:Resolution[]):Resolution[]{return entries.map(({file_id,reason,...fields})=>{if(!reason.trim())throw new Error('선택 사유를 입력하세요.');return {file_id,reason:reason.trim(),...Object.fromEntries(Object.entries(fields).filter(([,v])=>v!==undefined&&v!==null&&v!==''))};});}
export function activeResolutions(fileIds:string[],entries:Record<string,Partial<Resolution>>):Resolution[]{
 return resolutionsFor(fileIds.filter(id=>Object.keys(entries[id]||{}).some(k=>k!=='reason')).map(file_id=>({file_id,...entries[file_id]}) as Resolution));
}

// Which C2C figure a saved run's per-card CV came from (handoff 06 §2.2): overall variation or the
// linearly detrended relative residual SD from the measurement page, or a plain assumption.
export type C2cBasis = 'overall'|'detrended'|'assumed';
export const c2cBasisLabels:Record<C2cBasis,string>={overall:'전체 변동',detrended:'추세 제거 후 변동',assumed:'직접 가정'};

export interface CardUploadState {ltp:File|null;ltd:File|null;busy:boolean;error:string|null}
// Run blockers per card, in the card's own words. With an effect OFF its CV is never required;
// with it ON only that effect's CV is checked, and 0 is a valid entered value (null = not entered).
export function cardProblems(cards:Card[],form:CommonForm,uploads:Record<string,Partial<CardUploadState>>={}):Record<string,string[]>{
 const problems:Record<string,string[]>={};
 for(const card of cards){
  const list:string[]=[];
  if(!card.display_name.trim())list.push('소자 이름을 입력하세요.');
  if(uploads[card.card_id]?.busy)list.push('LTM 파일을 처리하는 중입니다.');
  else if(!card.profile_ref)list.push('LTP와 LTD 파일을 올리세요.');
  if(form.c2c&&(card.manual_c2c_cv_percent==null))list.push('C2C가 켜져 있어 C2C CV(%)가 필요합니다.');
  if(form.d2d&&(card.manual_d2d_cv_percent==null))list.push('D2D가 켜져 있어 D2D CV(%)가 필요합니다.');
  if(list.length)problems[card.card_id]=list;
 }
 return problems;
}

// Two chosen files = two physical devices. The label names the file, never a guessed device number.
export function d2dPairDevices(files:{file_id:string;name:string;snapshot_paths?:string[]}[]){
 return files.map((f,i)=>({file_id:f.file_id,device_id:`소자 ${i+1} (${f.name})`,
  identity_evidence:f.snapshot_paths?.find(p=>p.startsWith('D2D/'))?`소자팀 지정 D2D 파일 쌍 (팀 스냅샷 ${f.snapshot_paths.find(p=>p.startsWith('D2D/'))})`:'사용자가 서로 다른 물리 소자의 파일로 지정'}));
}

// Client-side CSV of exactly the rows shown on screen (UTF-8 BOM for Excel; formula-like text quoted).
export function toCsv(rows:Record<string,unknown>[]):string{
 const keys=Array.from(new Set(rows.flatMap(r=>Object.keys(r))));
 const cell=(v:unknown)=>{let s=v==null?'':String(v);if(/^[=+\-@]/.test(s)&&typeof v==='string')s="'"+s;return /[",\n]/.test(s)?`"${s.replace(/"/g,'""')}"`:s;};
 return '\uFEFF'+[keys.map(cell).join(','),...rows.map(r=>keys.map(k=>cell(r[k])).join(','))].join('\r\n')+'\r\n';
}
