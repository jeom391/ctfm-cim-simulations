import type {components} from './api/generated';

export type Card = components['schemas']['ComparisonCard'];
export type CardResult = components['schemas']['ComparisonCardResult'];
export type Comparison = components['schemas']['ComparisonResult'];
export type Recognition = components['schemas']['RecognitionResult'];
export type Resolution = components['schemas']['RecognitionResolution'];
export type Proposal = components['schemas']['AnalysisRequest'];
type PublishedProfile = Pick<components['schemas']['ProfileManifest'],'profile_id'|'revision'|'condition_id'|'pools'|'analysis_links'>;

export interface CommonForm {adc:boolean;adcBits:number;d2d:boolean;c2c:boolean;retention:boolean;arrays:number;nReprogram:number;years:string;pools:string[];mappings:string[];engine:string;checkpoint:string;seed:number}
export const defaultCommon:CommonForm={adc:false,adcBits:5,d2d:false,c2c:false,retention:false,arrays:1,nReprogram:1,years:'0',pools:['combined'],mappings:['fixed_reference'],engine:'torch_reference',checkpoint:'',seed:20260917};

export function commonSettings(form:CommonForm){
 const years=form.retention?form.years.split(',').map(s=>Number(s.trim())):[0];
 if(form.retention&&(form.years.split(',').some(s=>!s.trim())||years.length>10||!years.includes(0)||years.some(n=>!Number.isFinite(n)||n<0||n>100)||new Set(years).size!==years.length))throw new Error('연수는 0을 포함하는 중복 없는 0~100 값, 최대 10개여야 합니다.');
 if(form.adc&&(!Number.isInteger(form.adcBits)||form.adcBits<3||form.adcBits>8))throw new Error('ADC는 3~8 bit여야 합니다.');
 if(form.d2d&&(!Number.isInteger(form.arrays)||form.arrays<1||form.arrays>100))throw new Error('D2D 배열 수는 1~100이어야 합니다.');
 if(form.c2c&&(!Number.isInteger(form.nReprogram)||form.nReprogram<1||form.nReprogram>100))throw new Error('C2C 재기록 횟수는 1~100이어야 합니다.');
 if(!form.pools.length||!form.mappings.length)throw new Error('풀과 매핑을 선택하세요.');
 if(!Number.isInteger(form.seed)||form.seed<0||form.seed>4294967295)throw new Error('seed는 0~4294967295 정수여야 합니다.');
 const checkpoint=form.checkpoint.trim();if(checkpoint&&!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(checkpoint))throw new Error('checkpoint ID는 UUID여야 합니다.');
 return {schema_version:'1.4.0',model_id:'mnist_mlp_v1',checkpoint_id:checkpoint||null,pools:form.pools,mappings:form.mappings,effects:{adc:form.adc,d2d:form.d2d,c2c:form.c2c,retention:form.retention},arrays:form.d2d?form.arrays:1,n_reprogram:form.c2c?form.nReprogram:1,years,seed:form.seed,hardware:{tile_size:64,adc_bits:form.adc?form.adcBits:null,adc_order:form.adc?'adc_then_subtract':null,range_policy:form.adc?'validation_max_abs':null,preset_id:null},engines:{accuracy:form.engine,ppa:'off'}};
}

export function restoreCommon(raw:Record<string,unknown>):CommonForm{
 const effects=(raw.effects||{}) as Record<string,boolean>,hardware=(raw.hardware||{}) as Record<string,unknown>,engines=(raw.engines||{}) as Record<string,unknown>;
 return {...defaultCommon,adc:effects.adc??false,d2d:effects.d2d??false,c2c:effects.c2c??false,retention:effects.retention??false,adcBits:typeof hardware.adc_bits==='number'?hardware.adc_bits:5,arrays:typeof raw.arrays==='number'?raw.arrays:1,nReprogram:typeof raw.n_reprogram==='number'?raw.n_reprogram:1,years:Array.isArray(raw.years)?raw.years.join(', '):'0',pools:Array.isArray(raw.pools)?raw.pools as string[]:['combined'],mappings:Array.isArray(raw.mappings)?raw.mappings as string[]:['fixed_reference'],engine:typeof engines.accuracy==='string'?engines.accuracy:'torch_reference',checkpoint:typeof raw.checkpoint_id==='string'?raw.checkpoint_id:'',seed:typeof raw.seed==='number'?raw.seed:20260917};
}

const cardKeys=['card_id','display_name','profile_ref','condition_id','state_analysis_id','selected_state_ids','d2d_analysis_id','retention_analysis_id','c2c_analysis_id','c2c_approved_assumption','cross_condition_acknowledged','manual_c2c_cv_percent'] as const;
export function editableCard(card:CardResult|Card):Card {return Object.fromEntries(cardKeys.filter(k=>k in card).map(k=>[k,card[k]])) as unknown as Card;}
export function publishedCard(card:Card,profile:PublishedProfile):Card{
 const links=profile.analysis_links as Record<string,{analysis_id?:string}>|null|undefined;
 return {...card,profile_ref:{id:profile.profile_id,revision:profile.revision},condition_id:profile.condition_id,state_analysis_id:links?.state?.analysis_id||null,selected_state_ids:profile.pools.combined?.state_ids||null,d2d_analysis_id:links?.d2d?.analysis_id||null,retention_analysis_id:links?.retention?.analysis_id||null,c2c_analysis_id:links?.c2c?.analysis_id||null,manual_c2c_cv_percent:null,c2c_approved_assumption:false,cross_condition_acknowledged:false};
}
export function profileRevisionPayload(card:Card,base:PublishedProfile):components['schemas']['ProfileRevision']{
 const links=base.analysis_links as Record<string,{analysis_id?:string}>|null|undefined;
 const body:components['schemas']['ProfileRevision']={base_revision:base.revision,display_name:card.display_name};
 for(const [kind,key] of [['state','state_analysis_id'],['d2d','d2d_analysis_id'],['retention','retention_analysis_id'],['c2c','c2c_analysis_id']] as const){
  const selected=card[key]||null,original=links?.[kind]?.analysis_id||null;
  if(selected!==original&&(kind!=='state'||selected))body[key]=selected;
 }
 const selected=card.selected_state_ids,previous=base.pools.combined?.state_ids||[];
 if(selected&& (selected.length!==previous.length||selected.some(id=>!previous.includes(id))))body.selected_state_ids=selected;
 return body;
}
export function draftUpdate(expected_version:number,common_settings:Record<string,unknown>,cards:(Card|CardResult)[]){return {expected_version,common_settings,cards:cards.map(editableCard)};}
export function recognizedChoices(requests:Proposal[],selected:Set<number>):Proposal[]{return requests.filter((_,i)=>selected.has(i));}
export function resolutionsFor(entries:Resolution[]):Resolution[]{return entries.map(({file_id,reason,...fields})=>{if(!reason.trim())throw new Error('선택 사유를 입력하세요.');return {file_id,reason:reason.trim(),...Object.fromEntries(Object.entries(fields).filter(([,v])=>v!==undefined&&v!==null&&v!==''))};});}
