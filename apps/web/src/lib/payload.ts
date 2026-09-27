import {profileKey,analysisId,analysisCondition} from './api/index.ts';
import type {Analysis,Capabilities,Dataset,Kind,Profile,SimulationForm,ExperimentRequest} from './api/index.ts';
export const canonicalKeys:Record<Kind,string[]>={iv:['vgs_v','id_a'],d2d:['vgs_v','id_a'],retention:['time_s','program_id_a','erase_id_a'],pulse_states:['time_s','id_a','vgs_v'],c2c_detrended:[]};
export const unitOptions=(key:string)=>key==='time_s'?['s','ms']:key==='vgs_v'?['V','mV']:['A','mA','uA','nA'];
// Instrument exports name their columns the same way every run, so the first
// guess is worth prefilling. Nothing here skips a check: every dataset still
// needs its own 확인 tick, and buildAnalysis re-validates what is submitted.
export const retentionRoles=['erase_time_s','erase_id_a','program_time_s','program_id_a'] as const;
// A column is suggested only when its header identifies exactly one column; ambiguous headers stay empty for the user.
const retentionHints:Record<string,RegExp>={erase_time_s:/eras.*time/i,erase_id_a:/eras(?!.*time)/i,program_time_s:/program.*time/i,program_id_a:/program(?!.*time)/i};
export function suggestRetentionColumns(headers:(string|null)[]){
 const out:Record<string,string>={};
 for(const role of retentionRoles){const hits=headers.map((h,i)=>h&&retentionHints[role].test(h)?i:-1).filter(i=>i>=0);if(hits.length===1&&!Object.values(out).includes(String(hits[0])))out[role]=String(hits[0]);}
 return out;
}
export const c2cConditionFields:{key:string;label:string;kind:'voltage'|'positive'|'text';unit:string;hint:string}[]=[
 {key:'program_voltage_v',label:'Program 전압',kind:'voltage',unit:'V',hint:'부호 포함, 예: 10'},
 {key:'program_pulse_width_s',label:'Program 펄스 폭',kind:'positive',unit:'s',hint:'0보다 커야 함'},
 {key:'erase_voltage_v',label:'Erase 전압',kind:'voltage',unit:'V',hint:'부호 포함, 예: -10'},
 {key:'erase_pulse_width_s',label:'Erase 펄스 폭',kind:'positive',unit:'s',hint:'0보다 커야 함'},
 {key:'read_voltage_v',label:'Read 전압',kind:'voltage',unit:'V',hint:'0도 유효'},
 {key:'read_terminal_meaning',label:'Read 전압이 걸린 단자',kind:'text',unit:'',hint:'예: gate'},
 {key:'vds_v',label:'VDS',kind:'voltage',unit:'V',hint:'절대 전도도 변환에만 필요'},
 {key:'read_time_s',label:'읽기 시간',kind:'positive',unit:'s',hint:'0보다 커야 함'},
 {key:'read_extraction_point',label:'전류 추출 시점',kind:'text',unit:'',hint:'예: 읽기 펄스 끝'}];
const columnHints:Record<string,RegExp>={time_s:/^time/i,id_a:/^(id\b|i_?d\b|drain|meas\s*result\s*1)/i,vgs_v:/^(vg|v_?gs|gate|meas\s*result\s*2)/i,program_id_a:/program/i,erase_id_a:/eras/i};
export function suggestDataset(kind:Kind,filename:string,columns:string[]){
 const column_mapping:Record<string,string>={},units:Record<string,string>={};
 for(const key of canonicalKeys[kind]){
  const hit=columns.find(c=>columnHints[key]?.test(c.trim())&&!Object.values(column_mapping).includes(c));
  if(hit){column_mapping[key]=hit;units[key]=unitOptions(key)[0];}
 }
 const condition=/(^|[^a-z0-9])([a-e]\d)([^a-z0-9]|$)/i.exec(filename);
 const direction=/ltp/i.test(filename)?'ltp':/ltd/i.test(filename)?'ltd':'';
 return {column_mapping,units,condition_id:condition?condition[2].toUpperCase():'',direction:kind==='pulse_states'?direction:''};
}
export const available=(value:unknown)=>value===true||(typeof value==='object'&&value!==null&&'available'in value&&value.available===true);
const check=(ok:unknown,message:string)=>{if(!ok)throw new Error(message);};
const integer=(n:number,min:number,max:number)=>Number.isInteger(n)&&n>=min&&n<=max;
export function buildExperiment(f:SimulationForm,profiles:Profile[],caps:Capabilities,analyses:Analysis[]=[]):ExperimentRequest{
 check(f.profileKeys.length>=1&&f.profileKeys.length<=5,'발행 프로파일을 1~5개 선택하세요.');
 const selected=f.profileKeys.map(key=>profiles.find(p=>`${p.profile_id}:${p.revision}`===key));
 check(selected.every(p=>p?.status==='published'),'발행된 프로파일 revision만 실행할 수 있습니다.');
 const chosen=selected as Profile[];
 check(new Set(chosen.map(p=>p.profile_id)).size===chosen.length,'동일 프로파일의 여러 revision을 동시에 선택할 수 없습니다.');
 check(f.pools.length>0&&new Set(f.pools).size===f.pools.length&&f.pools.every(p=>['combined','ltp','ltd','common'].includes(p)),'전도도 풀을 선택하세요.');
 check(f.mappings.length>0&&new Set(f.mappings).size===f.mappings.length&&f.mappings.every(p=>['fixed_reference','pair_search'].includes(p)),'매핑 방식을 선택하세요.');
 check(integer(f.seed,0,4294967295),'seed는 0~4294967295 정수여야 합니다.');
 check(caps.engines?.[f.engine]?.available&&['torch_reference','aihwkit_ideal'].includes(f.engine),'선택 엔진을 사용할 수 없습니다.');
 check(!f.d2d||chosen.every(p=>p.d2d?.status==='available'&&typeof p.d2d.cv==='number'),'D2D CV가 제공된 프로파일만 D2D 효과를 사용할 수 있습니다.');
 check(!f.retention||chosen.every(p=>p.retention?.status==='available'&&p.retention.program_fit),'Retention Program fit이 제공된 프로파일만 사용할 수 있습니다.');
 const arrays=f.d2d?f.arrays:1;check(integer(arrays,1,100),'배열 수는 1~100 정수여야 합니다.');
 const parts=f.years.split(',').map(s=>s.trim());const years=f.retention?parts.map(Number):[0];
 check(!f.retention||parts.every(Boolean),'연수 목록에 빈 항목을 넣을 수 없습니다.');
 check(years.length<=10&&years.includes(0)&&new Set(years).size===years.length&&years.every(n=>Number.isFinite(n)&&n>=0&&n<=100),'연수는 0을 포함하고 중복 없는 0~100 값이어야 하며 최대 10개입니다.');
 check(!f.adc||available(caps.effects?.adc),'현재 엔진 환경에서 ADC를 지원하지 않습니다.');
 // assumed_proxy prices the virtual analog circuit, so it needs the ADC, the engine build and a tile size the engine has completed.
 if(f.ppa){check(f.adc,'PPA 비용 추정은 ADC를 켠 요청에서만 실행됩니다. ADC off의 비용은 ADC를 제거한 회로 비용이 아닙니다.');const ne=caps.engines?.neurosim;check(ne?.available,'NeuroSim 엔진을 이 실행 환경에서 사용할 수 없습니다'+(ne?.reason?`: ${ne.reason}`:'.'));check(caps.hardware?.ppa_tile_sizes?.includes(f.tileSize),`PPA 비용 추정은 배열 크기 ${f.tileSize}에서 지원되지 않습니다: ${caps.hardware?.ppa_unsupported?.[String(f.tileSize)]??'엔진이 이 크기를 지원한다고 보고하지 않았습니다.'}`);}
 // The array is physical, so its size is part of every request, ADC or not.
 check([64,128,256].includes(f.tileSize),'배열 크기는 64/128/256이어야 합니다.');
 if(f.adc){check(integer(f.adcBits,3,8),'ADC는 3~8 bit여야 합니다.');check(['subtract_then_adc','adc_then_subtract'].includes(f.adcOrder),'두 ADC 순서 중 하나를 선택하세요.');const pairs=caps.hardware?.validated_combinations;if(pairs)check(pairs.some(p=>p.tile_size===f.tileSize&&p.adc_bits===f.adcBits&&(!p.engine||p.engine===f.engine)&&(!p.adc_order||p.adc_order===f.adcOrder)),'검증되지 않은 ADC·타일·순서·엔진 조합입니다.');}
 const nReprogram=f.c2c?f.nReprogram:1;check(integer(nReprogram,1,100),'재기록 횟수는 1~100 정수여야 합니다.');
 // Each referenced revision states its own manual CV; nothing is inherited from another profile.
 const cv=Object.fromEntries(chosen.map(p=>[profileKey(p),(f.c2cCv?.[profileKey(p)]??'').trim()]));
 const measuredOf=(p:Profile)=>f.c2c&&f.c2cSource?.[profileKey(p)]==='measured';
 const refFor=(p:Profile)=>{
  const key=profileKey(p),name=p.display_name||p.condition_id;
  if(!f.c2c)return {id:p.profile_id,revision:p.revision};
  if(!measuredOf(p)){check(cv[key]!==''&&Number.isFinite(Number(cv[key]))&&Number(cv[key])>=0,`${name}의 C2C 상대 CV(%)를 0 이상의 숫자로 입력하세요.`);return {id:p.profile_id,revision:p.revision,c2c:{cv_percent:Number(cv[key]),source:'manual_assumption' as const}};}
  const id=f.c2cAnalysis?.[key]||'';const a=analyses.find(x=>analysisId(x)===id);
  check(a&&a.kind==='c2c_detrended'&&a.status==='succeeded',`${name}: 완료된 실측 C2C 분석을 선택하세요.`);
  check(a!.program?.status==='ok'&&typeof a!.program.primary.relative_residual_std_percent==='number',`${name}: 선택한 분석의 Program 편차를 사용할 수 없습니다.`);
  check(f.c2cApproved?.[key]===true,`${name}: Program 상대 편차를 이 프로파일의 모든 LTP/LTD 상태에 적용하는 가정을 확인해 주세요.`);
  const cross=analysisCondition(a!)!==p.condition_id;
  check(!cross||f.c2cCross?.[key]===true,`${name}: 분석 조건(${analysisCondition(a!)})과 프로파일 조건(${p.condition_id})이 다릅니다. 다른 조건에 적용하는 것을 확인해 주세요.`);
  return {id:p.profile_id,revision:p.revision,c2c:{source:'measured_detrended' as const,analysis_id:id,approved_assumption:true as const,...(cross?{cross_condition_acknowledged:true}:{})}};
 };
 const refs=chosen.map(refFor);const anyMeasured=chosen.some(measuredOf);
 check(chosen.length*f.pools.length*f.mappings.length*arrays*nReprogram*years.length<=2000,'한 요청의 최대 실행 수는 2,000입니다.');
 const checkpoint=f.checkpoint.trim();check(!checkpoint||/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(checkpoint),'checkpoint ID는 UUID여야 합니다.');
 return {schema_version:f.ppa||(f.c2c&&anyMeasured)?'1.4.0':f.c2c?'1.3.0':'1.2.0',profile_refs:refs as ExperimentRequest['profile_refs'],model_id:'mnist_mlp_v1',checkpoint_id:checkpoint||null,pools:f.pools as ExperimentRequest['pools'],mappings:f.mappings as ExperimentRequest['mappings'],effects:{d2d:f.d2d,retention:f.retention,adc:f.adc,c2c:f.c2c},arrays,n_reprogram:nReprogram,years,seed:f.seed,hardware:{tile_size:f.tileSize as 64|128|256,adc_bits:f.adc?f.adcBits as 3|4|5|6|7|8:null,adc_order:f.adc?f.adcOrder:null,range_policy:f.adc?'validation_max_abs':null,preset_id:null},engines:{accuracy:f.engine as 'torch_reference'|'aihwkit_ideal',ppa:f.ppa?'assumed_proxy':'off'}};
}
function ivBlockInput(d:Dataset,prefix:string){
 const layout=d.ivLayout;check(layout&&d.sheet,prefix+'시트와 블록 구조가 필요합니다.');
 const block=layout!.blocks.find(b=>String(b.index)===d.block);check(block,prefix+'Vg/Id/Ig 블록을 선택하세요.');
 check(block!.status==='ok',prefix+`선택한 블록을 사용할 수 없습니다: ${block!.error}`);
 const segment=block!.segments?.find(s=>String(s.index)===d.segment);check(segment,prefix+'Vg 구간을 선택하세요.');
 check(['program','erase'].includes(d.branch||''),prefix+'분기를 선택하세요.');
 check((d.branch==='erase')===(segment!.direction==='increasing'),prefix+`${d.branch} 분기는 ${d.branch==='erase'?'상승':'하강'} 구간이어야 합니다.`);
 check(unitOptions('vgs_v').includes(d.units.vgs_v)&&unitOptions('id_a').includes(d.units.id_a),prefix+'Vg와 Id 단위를 선택하세요.');
 check(d.sweep_amplitude_v!==''&&Number.isFinite(Number(d.sweep_amplitude_v))&&Number(d.sweep_amplitude_v)>0,prefix+'양의 스윕 진폭이 필요합니다.');
 check(Math.abs(Number(d.sweep_amplitude_v)-ivAmplitudeV(block!.proposed_amplitude_v,d.units.vgs_v))<1e-9,prefix+`스윕 진폭은 선택한 블록의 최대 |Vg| (${ivAmplitudeV(block!.proposed_amplitude_v,d.units.vgs_v)} V)와 같아야 합니다.`);
 check(!d.row_start&&!d.row_end,prefix+'블록 선택에서는 원본 행 범위를 지정하지 않습니다.');
 return {file_id:d.file_id,sheet:d.sheet,units:{vgs_v:d.units.vgs_v,id_a:d.units.id_a},device_id:d.device_id.trim(),condition_id:d.condition_id.trim(),branch:d.branch,sweep_amplitude_v:Number(d.sweep_amplitude_v),vds_v:0.1,read_vgs_v:0,selection:{type:'iv_block',block:Number(d.block),segment:Number(d.segment)}} as Record<string,unknown>;
}
function retentionColumnInput(d:Dataset,prefix:string){
 check(d.sheet&&d.retentionLayout,prefix+'시트와 열 구조가 필요합니다.');
 const picked=retentionRoles.map(role=>d.retentionColumns?.[role]);
 check(picked.every(v=>v!==undefined&&v!==''),prefix+'Erase/Program의 시간·전류 열 네 개를 모두 선택하세요.');
 check(new Set(picked).size===4,prefix+'네 열은 서로 달라야 합니다.');
 check(unitOptions('time_s').includes(d.units.erase_time_s)&&unitOptions('time_s').includes(d.units.program_time_s)&&unitOptions('id_a').includes(d.units.erase_id_a)&&unitOptions('id_a').includes(d.units.program_id_a),prefix+'시간·전류 단위를 선택하세요.');
 check(d.source_label?.trim(),prefix+'원본 데이터 라벨이 필요합니다.');
 check(d.vds_v!==''&&Number(d.vds_v)>0&&Number.isFinite(Number(d.vds_v)),prefix+'양의 읽기 VDS가 필요합니다.');
 check(d.read_vgs_v!==''&&Number.isFinite(Number(d.read_vgs_v)),prefix+'읽기 VGS가 필요합니다.');
 check(!d.row_start&&!d.row_end,prefix+'열 선택에서는 원본 행 범위를 지정하지 않습니다.');
 return {file_id:d.file_id,sheet:d.sheet,units:Object.fromEntries(retentionRoles.map(r=>[r,d.units[r]])),device_id:d.device_id.trim(),condition_id:d.condition_id.trim(),source_label:d.source_label,read_vgs_v:Number(d.read_vgs_v),vds_v:Number(d.vds_v),selection:{type:'retention_columns',columns:Object.fromEntries(retentionRoles.map((r,i)=>[r,Number(picked[i])]))}} as Record<string,unknown>;
}
function c2cInput(d:Dataset,prefix:string){
 check(d.device_id.trim()&&d.condition_id.trim(),prefix+'소자 ID와 조건 ID가 필요합니다.');
 const conditions:Record<string,unknown>={};
 for(const f of c2cConditionFields){
  const raw=(d.conditions?.[f.key]??'').trim();if(!raw)continue;
  if(f.kind==='text'){conditions[f.key]=raw;continue;}
  const n=Number(raw);check(Number.isFinite(n),prefix+`${f.label}은 유한한 숫자여야 합니다.`);check(f.kind!=='positive'||n>0,prefix+`${f.label}은 0보다 커야 합니다.`);conditions[f.key]=n;
 }
 return {file_id:d.file_id,sheet:d.sheet,device_id:d.device_id.trim(),condition_id:d.condition_id.trim(),measurement_conditions:conditions} as Record<string,unknown>;
}
export function buildAnalysis({kind,datasets,settings}:{kind:Kind;datasets:Dataset[];settings:Record<string,unknown>}){
 check(datasets.length>0,'분석할 데이터셋을 추가하세요.');
 if(kind==='c2c_detrended'){check(datasets.length===1,'실측 C2C는 워크북 하나만 분석합니다. 나머지는 삭제하세요.');check(datasets[0].confirmed,'데이터셋 1: 시트와 조건을 확인해 주세요.');return {kind,inputs:[c2cInput(datasets[0],'데이터셋 1: ')],settings:{}};}
 const inputs=datasets.map((d,i)=>{const prefix=`데이터셋 ${i+1}: `;check(d.confirmed,prefix+'열·단위·조건을 확인해 주세요.');check(d.device_id.trim()&&d.condition_id.trim(),prefix+'소자 ID와 조건 ID가 필요합니다.');
 if(d.layoutKind==='iv_block'&&(kind==='iv'||kind==='d2d'))return ivBlockInput(d,prefix);
 if(d.layoutKind==='retention_columns'&&kind==='retention')return retentionColumnInput(d,prefix);
 check(!d.layoutKind,prefix+'이 파일은 반복 블록/독립 시간축 형식이라 현재 분석 종류에서는 쓸 수 없습니다. 삭제하거나 맞는 분석 탭으로 돌아가세요.');
 for(const key of canonicalKeys[kind]){check(d.column_mapping[key],prefix+`${key} 열을 선택하세요.`);check(unitOptions(key).includes(d.units[key]),prefix+`${key} 단위를 선택하세요.`);}
 check(new Set(canonicalKeys[kind].map(key=>d.column_mapping[key])).size===canonicalKeys[kind].length,prefix+'서로 다른 원본 열을 지정하세요.');
 const value:Record<string,unknown>={file_id:d.file_id,sheet:d.sheet,column_mapping:Object.fromEntries(canonicalKeys[kind].map(k=>[k,d.column_mapping[k]])),units:Object.fromEntries(canonicalKeys[kind].map(k=>[k,d.units[k]])),device_id:d.device_id.trim(),condition_id:d.condition_id.trim()};
 if(kind!=='retention')Object.assign(value,{vds_v:0.1,read_vgs_v:0});
 if(kind==='iv'||kind==='d2d'){check(['program','erase'].includes(d.branch||''),prefix+'분기를 선택하세요.');check(d.sweep_amplitude_v!==''&&Number.isFinite(Number(d.sweep_amplitude_v))&&Number(d.sweep_amplitude_v)>0,prefix+'양의 스윕 진폭이 필요합니다.');Object.assign(value,{branch:d.branch,sweep_amplitude_v:Number(d.sweep_amplitude_v)});}
 if(kind==='pulse_states'){check(['ltp','ltd'].includes(d.direction||''),prefix+'LTP/LTD 방향을 선택하세요.');value.direction=d.direction;}
 if(kind==='retention'){check(d.source_label?.trim(),prefix+'원본 데이터 라벨이 필요합니다.');check(d.vds_v!==''&&Number(d.vds_v)>0&&Number.isFinite(Number(d.vds_v)),prefix+'양의 읽기 VDS가 필요합니다.');check(d.read_vgs_v!==''&&Number.isFinite(Number(d.read_vgs_v)),prefix+'읽기 VGS가 필요합니다.');Object.assign(value,{source_label:d.source_label,read_vgs_v:Number(d.read_vgs_v),vds_v:Number(d.vds_v)});}
 for(const key of ['row_start','row_end'] as const)if(d[key]!==''&&d[key]!==undefined){check(integer(Number(d[key]),1,Number.MAX_SAFE_INTEGER),prefix+'행 범위는 1 이상의 정수여야 합니다.');value[key]=Number(d[key]);}
 check(!value.row_start||!value.row_end||Number(value.row_start)<=Number(value.row_end),prefix+'시작 행이 종료 행보다 클 수 없습니다.');return value;});
 return {kind,inputs,settings};
}

// Block layout values are raw instrument numbers; selection supplies the unit.
export function ivAmplitudeV(raw:number|undefined,unit:string):number { return (raw??0)*(unit==='mV'?0.001:1); }
