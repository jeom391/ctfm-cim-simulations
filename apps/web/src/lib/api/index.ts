import type {components} from './generated';
export type ExperimentRequest = components['schemas']['ExperimentRequest'];
export type Profile = components['schemas']['ProfileManifest'];
export type Row = Record<string, unknown>;
export type Kind = 'iv'|'d2d'|'retention'|'pulse_states';
export interface Availability { available:boolean; version?:string|null; reason?:string|null }
export interface Capabilities { engines:Record<string,Availability>; effects?:Record<string,Availability|boolean>; hardware?:{tile_sizes?:number[];adc_bits?:number[];adc_orders?:string[];validated_combinations?:{tile_size:number;adc_bits:number;adc_order?:string;engine?:string;range_policy?:string}[]}; models?:unknown; [key:string]:unknown }
export interface Artifact {id:string;filename:string;kind:string;media_type?:string;download_url?:string;sha256?:string;size_bytes?:number}
export interface Analysis {id?:string;analysis_id?:string;job_id?:string;request?:{kind?:Kind;inputs?:{condition_id?:string}[]};kind:Kind;status:string;condition_id?:string;states?:Row[];summaries?:Row;tables?:Record<string,Row[]>;exclusions?:unknown[];warnings?:unknown[];artifacts?:Artifact[];settings?:Row;[key:string]:unknown}
export interface CostCoverage {status:string;counted_components?:string[];missing_components?:{id:string;detail:string}[];excluded_by_scope?:{id:string;detail:string}[];totals_reason?:string;inventory?:{adc_order?:string;physical_cells?:number;adc_count?:number;conversion_cycles_per_inference?:number;layers?:Record<string,unknown>[];[key:string]:unknown}}
export interface PpaSummary {status:string;reasons?:string[];reason?:string|null;
 coverage?:CostCoverage|null;engine_totals?:Record<string,number|null>|null;
 blocking_reasons?:string[];incomplete_reasons?:string[];build?:Record<string,unknown>|null;
 schedule_check?:{status?:string;detail?:string|null;assumed_read_window_s?:number|null}|null;
 area_m2?:number|null;energy_j_per_inference?:number|null;latency_s_per_inference?:number|null;
 model_mismatches?:{id:string;detail:string}[];
 preset?:{preset_id?:string|null;status?:string;problems?:string[]}|null;
 preset_artifact?:{filename?:string;sha256?:string}|null;
 engine?:{available?:boolean;commit?:string|null;reason?:string|null}|null}
export interface Job {id?:string;job_id?:string;state:string;stage?:string;progress?:number|null;completed?:number;total?:number;cancel_requested?:boolean;error?:unknown}
export interface Experiment {id?:string;experiment_id?:string;job_id?:string;status:string;runs?:Row[];summary?:Row;warnings?:unknown[];assumptions?:unknown[];artifacts?:Artifact[];ppa?:PpaSummary|null;[key:string]:unknown}
export interface UploadedFile {file_id:string;name:string;sha256:string;size_bytes:number;media_type:string}
export interface Preview {file_id:string;sheets:string[];sheet:string|null;columns:string[];rows:Row[];source_rows:number[];warnings:unknown[]}
export interface Dataset {key?:string;file_id:string;filename?:string;sheet:string|null;column_mapping:Record<string,string>;units:Record<string,string>;device_id:string;condition_id:string;branch?:string;sweep_amplitude_v?:number|string;direction?:string;source_label?:string;read_vgs_v?:number|string;vds_v?:number|string;row_start?:number|string;row_end?:number|string;confirmed:boolean;preview?:Preview}
export type AdcOrder = 'subtract_then_adc'|'adc_then_subtract';
export interface SimulationForm {profileKeys:string[];pools:string[];mappings:string[];d2d:boolean;retention:boolean;adc:boolean;c2c:boolean;nReprogram:number;c2cCv:Record<string,string>;arrays:number;years:string;seed:number;tileSize:number;adcBits:number;adcOrder:AdcOrder;engine:string;checkpoint:string}
export class ApiError extends Error { code?:string;field?:string;requestId?:string; constructor(message:string,code?:string,field?:string,requestId?:string){super(message);this.code=code;this.field=field;this.requestId=requestId;} }
export async function request<T>(path:string,options:RequestInit={}):Promise<T>{
 let response:Response;
 try{response=await fetch('/api/v1'+path,{...options,headers:{...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options.headers}});}catch{throw new ApiError('서버에 연결할 수 없습니다. API 실행 상태를 확인한 뒤 다시 시도하세요.');}
 const data=await response.json().catch(()=>null);
 if(!response.ok){const error=data?.error;throw new ApiError(error?.message||`요청에 실패했습니다 (HTTP ${response.status}).`,error?.code,error?.field,error?.request_id);}
 return data as T;
}
export const api={createExperiment:(body:ExperimentRequest)=>request<components['schemas']['QueuedExperiment']>('/experiments',{method:'POST',body:JSON.stringify(body)}),get:<T,>(path:string)=>request<T>(path),post:<T,>(path:string,body:unknown)=>request<T>(path,{method:'POST',body:JSON.stringify(body)}),upload:async(files:File[],path='/files')=>{const body=new FormData();files.forEach(file=>body.append(path==='/profiles/import'?'file':'files',file));return request<{files:UploadedFile[]}&Profile>(path,{method:'POST',body});}};
export const profileKey=(p:Profile)=>`${p.profile_id}:${p.revision}`;
export const analysisId=(a:Analysis)=>a.analysis_id||a.id||'';

export const analysisKind=(a:Analysis)=>a.kind||a.request?.kind||'iv';
export const analysisCondition=(a:Analysis)=>a.condition_id||a.request?.inputs?.[0]?.condition_id||'';



