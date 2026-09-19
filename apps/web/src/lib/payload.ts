import type {Capabilities,Dataset,Kind,Profile,SimulationForm,ExperimentRequest} from './api/index.ts';
export const canonicalKeys:Record<Kind,string[]>={iv:['vgs_v','id_a'],d2d:['vgs_v','id_a'],retention:['time_s','program_id_a','erase_id_a'],pulse_states:['time_s','id_a','vgs_v']};
export const unitOptions=(key:string)=>key==='time_s'?['s','ms']:key==='vgs_v'?['V','mV']:['A','mA','uA','nA'];
export const available=(value:unknown)=>value===true||(typeof value==='object'&&value!==null&&'available'in value&&value.available===true);
const check=(ok:unknown,message:string)=>{if(!ok)throw new Error(message);};
const integer=(n:number,min:number,max:number)=>Number.isInteger(n)&&n>=min&&n<=max;
export function buildExperiment(f:SimulationForm,profiles:Profile[],caps:Capabilities):ExperimentRequest{
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
 if(f.adc){check([64,128,256].includes(f.tileSize)&&integer(f.adcBits,3,8),'ADC는 3~8 bit, 타일은 64/128/256이어야 합니다.');const pairs=caps.hardware?.validated_combinations;if(pairs)check(pairs.some(p=>p.tile_size===f.tileSize&&p.adc_bits===f.adcBits&&(!p.engine||p.engine===f.engine)),'검증되지 않은 ADC·타일·엔진 조합입니다.');}
 check(chosen.length*f.pools.length*f.mappings.length*arrays*years.length<=2000,'한 요청의 최대 실행 수는 2,000입니다.');
 const checkpoint=f.checkpoint.trim();check(!checkpoint||/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(checkpoint),'checkpoint ID는 UUID여야 합니다.');
 return {schema_version:'1.1.0',profile_refs:chosen.map(p=>({id:p.profile_id,revision:p.revision})),model_id:'mnist_mlp_v1',checkpoint_id:checkpoint||null,pools:f.pools as ExperimentRequest['pools'],mappings:f.mappings as ExperimentRequest['mappings'],effects:{d2d:f.d2d,retention:f.retention,adc:f.adc,c2c:false},arrays,n_reprogram:1,years,seed:f.seed,hardware:{tile_size:f.adc?f.tileSize as 64|128|256:null,adc_bits:f.adc?f.adcBits as 3|4|5|6|7|8:null,range_policy:f.adc?'validation_max_abs':null,preset_id:null},engines:{accuracy:f.engine as 'torch_reference'|'aihwkit_ideal',ppa:'off'}};
}
export function buildAnalysis({kind,datasets,settings}:{kind:Kind;datasets:Dataset[];settings:Record<string,unknown>}){
 check(datasets.length>0,'분석할 데이터셋을 추가하세요.');
 const inputs=datasets.map((d,i)=>{const prefix=`데이터셋 ${i+1}: `;check(d.confirmed,prefix+'열·단위·조건을 확인해 주세요.');check(d.device_id.trim()&&d.condition_id.trim(),prefix+'소자 ID와 조건 ID가 필요합니다.');
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


