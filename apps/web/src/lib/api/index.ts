import type {components} from './generated';
import type {Card,Comparison,Recognition,Resolution,Proposal} from '../workflows.ts';
import {draftUpdate} from '../workflows.ts';
export type ExperimentRequest = components['schemas']['ExperimentRequest'];
export type Profile = components['schemas']['ProfileManifest'];
export type Row = Record<string, unknown>;
export type Kind = 'iv'|'d2d'|'retention'|'pulse_states'|'c2c_detrended';
export interface Availability { available:boolean; version?:string|null; reason?:string|null }
export interface Capabilities { engines:Record<string,Availability>; effects?:Record<string,Availability|boolean>; hardware?:{ppa_tile_sizes?:number[];ppa_unsupported?:Record<string,string>;tile_sizes?:number[];adc_bits?:number[];adc_orders?:string[];validated_combinations?:{tile_size:number;adc_bits:number;adc_order?:string;engine?:string;range_policy?:string}[]}; models?:unknown; [key:string]:unknown }
export interface Artifact {id:string;filename:string;kind:string;media_type?:string;download_url?:string;sha256?:string;size_bytes?:number}
export interface C2cBranch {status:string;blocked_reason?:string|null;primary:{relative_residual_std_percent:number|null;residual_lag1_correlation:number|null};degree4_vs_degree3_change_percent:number|null;raw_statistics:{relative_std_percent:number|null}}
export interface Analysis {program?:C2cBranch;erase?:C2cBranch;analysis_result_sha256?:string;id?:string;analysis_id?:string;job_id?:string;request?:{kind?:Kind;inputs?:{condition_id?:string}[]};kind:Kind;status:string;condition_id?:string;states?:Row[];summaries?:Row;tables?:Record<string,Row[]>;exclusions?:unknown[];warnings?:unknown[];artifacts?:Artifact[];settings?:Row;[key:string]:unknown}
export interface CostCoverage {status:string;counted_components?:string[];missing_components?:{id:string;detail:string}[];excluded_by_scope?:{id:string;detail:string}[];totals_reason?:string;inventory?:{adc_order?:string;physical_cells?:number;adc_count?:number;conversion_cycles_per_inference?:number;layers?:Record<string,unknown>[];[key:string]:unknown}}
export interface PpaSummary {candidate?:{candidate_id:string;profile_id:string;profile_revision:number;pool:string;mapping:string}|null;status:string;reasons?:string[];reason?:string|null;
 coverage?:CostCoverage|null;engine_totals?:Record<string,number|null>|null;
 blocking_reasons?:string[];incomplete_reasons?:string[];build?:Record<string,unknown>|null;
 schedule_check?:{status?:string|null;detail?:string|null;assumed_read_window_s?:number|null;read_window_s?:number;engine_clock_period_s?:number|null;bitline_settling_s?:number|null;sensing_latency_s?:number|null;needed_cycle_s?:number|null;effective_cycle_s?:number|null;cycles_per_inference?:number|null}|null;
 area_m2?:number|null;energy_j_per_inference?:number|null;latency_s_per_inference?:number|null;
 model_mismatches?:{id:string;detail:string}[];
 requested?:string|null;model_status?:string|null;label?:string|null;
 preset?:{preset_id?:string|null;status?:string;problems?:string[];model_status?:string|null;validated_for_ctfm?:boolean;sub_array?:number;basis?:Record<string,string>}|null;
 preset_artifact?:{filename?:string;sha256?:string}|null;
 engine?:{available?:boolean;commit?:string|null;reason?:string|null;fixes?:Record<string,boolean>}|null;
 conductance?:Record<string,unknown>|null;trace_sample?:string|null;time_basis?:string|null;
 order?:string|null;input_encoding?:{input:string;schedule:string;engine_trace:string}|null;
 known_total?:{complete:boolean;area_m2?:number|null;energy_j_per_inference?:number|null;latency_s_per_inference?:number|null;note:string}|null;
 known_components?:{id:string;owner:string;area_m2?:number|null;energy_j_per_inference?:number|null;note?:string}[];
 unknown_components?:{id:string;detail:string}[];
 placement?:{spec_slots_per_plane:number;used_slots_per_plane:number;instantiated_slots_per_plane:number;removed_unused_slots?:number|null;planes:number;tile_size:number;weight_cells_per_plane:number;physical_cells:number;padding_cells:number;matches_spec_tiling:boolean}|null;
 fidelity?:{status:string;meaning:string;layers:{layer:string;column_conductance_rel_error:{plus:number;minus:number};rows_read:number;rows_read_expected:number;weight_cells:number;weight_cells_expected:number;used_slots:number;used_slots_expected:number}[]}|null;
 consistency?:Record<string,boolean|null>|null;adc_range_note?:Record<string,{accuracy_range_s?:number|null;engine_full_scale_s:number;fraction?:number|null}>|null;
 diagnostics?:{latency?:{engine_clock_s?:number|null;window_adjusted_s?:number|null}}|null;
 engine_cross_check?:{status:string;reason?:string;engine_array_cells_per_plane?:number;weights_per_plane?:number;spec_tiled_cells_per_plane?:number;engine_padding_cells?:number;engine_weight_utilization?:number|null;matches_spec_tiling?:boolean;planes?:string}|null}
export interface Job {id?:string;job_id?:string;state:string;stage?:string;progress?:number|null;completed?:number;total?:number;cancel_requested?:boolean;error?:unknown}
export interface Experiment {id?:string;experiment_id?:string;job_id?:string;status:string;runs?:Row[];summary?:Row;warnings?:unknown[];assumptions?:unknown[];artifacts?:Artifact[];ppa?:PpaSummary|null;[key:string]:unknown}
export interface IvSegment {index:number;direction:'increasing'|'decreasing';points:number;source_row_start:number;source_row_end:number;vg_start:number;vg_end:number}
export interface IvBlock {index:number;columns:number[];status:'ok'|'invalid';error?:string;points?:number;proposed_amplitude_v?:number;segments?:IvSegment[]}
export interface IvLayout {file_id:string;sheet:string|null;sheets:string[];block_count:number;blocks:IvBlock[];warnings?:unknown[]}
export interface RetentionLayout {file_id:string;sheet:string|null;sheets:string[];columns:{index:number;header:string|null;non_empty:number;first:unknown[]}[];embedded_source_headers:{sheet:string;header:string;read_bias_v:number[];embedded_numbers:number[]}[];warnings?:unknown[]}
export interface UploadedFile {file_id:string;name:string;sha256:string;size_bytes:number;media_type:string}
export interface Preview {file_id:string;sheets:string[];sheet:string|null;columns:string[];rows:Row[];source_rows:number[];warnings:unknown[]}
export interface Dataset {key?:string;file_id:string;filename?:string;sheet:string|null;column_mapping:Record<string,string>;units:Record<string,string>;device_id:string;condition_id:string;branch?:string;sweep_amplitude_v?:number|string;direction?:string;source_label?:string;read_vgs_v?:number|string;vds_v?:number|string;row_start?:number|string;row_end?:number|string;confirmed:boolean;preview?:Preview;conditions?:Record<string,string>;layoutKind?:'iv_block'|'retention_columns';ivLayout?:IvLayout;retentionLayout?:RetentionLayout;block?:string;segment?:string;retentionColumns?:Record<string,string>}
export type AdcOrder = 'subtract_then_adc'|'adc_then_subtract';
export interface SimulationForm {profileKeys:string[];pools:string[];mappings:string[];d2d:boolean;retention:boolean;adc:boolean;c2c:boolean;nReprogram:number;c2cCv:Record<string,string>;c2cSource?:Record<string,'manual'|'measured'>;c2cAnalysis?:Record<string,string>;c2cApproved?:Record<string,boolean>;c2cCross?:Record<string,boolean>;arrays:number;years:string;seed:number;tileSize:number;adcBits:number;adcOrder:AdcOrder;engine:string;checkpoint:string;ppa?:boolean}
export class ApiError extends Error { code?:string;field?:string;requestId?:string;status?:number; constructor(message:string,code?:string,field?:string,requestId?:string,status?:number){super(message);this.code=code;this.field=field;this.requestId=requestId;this.status=status;} }
export async function request<T>(path:string,options:RequestInit={}):Promise<T>{
 let response:Response;
 try{response=await fetch('/api/v1'+path,{...options,headers:{...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options.headers}});}catch{throw new ApiError('서버에 연결할 수 없습니다. API 실행 상태를 확인한 뒤 다시 시도하세요.');}
 const data=await response.json().catch(()=>null);
 if(!response.ok){const error=data?.error;throw new ApiError(error?.message||`요청에 실패했습니다 (HTTP ${response.status}).`,error?.code,error?.field,error?.request_id,response.status);}
 return data as T;
}
export const api={createExperiment:(body:ExperimentRequest)=>request<components['schemas']['QueuedExperiment']>('/experiments',{method:'POST',body:JSON.stringify(body)}),get:<T,>(path:string)=>request<T>(path),post:<T,>(path:string,body:unknown)=>request<T>(path,{method:'POST',body:JSON.stringify(body)}),put:<T,>(path:string,body:unknown)=>request<T>(path,{method:'PUT',body:JSON.stringify(body)}),upload:async(files:File[],path='/files')=>{const body=new FormData();files.forEach(file=>body.append(path==='/profiles/import'?'file':'files',file));return request<{files:UploadedFile[]}&Profile>(path,{method:'POST',body});},
 createProfileQuick:(ltp:File,ltd:File,display_name:string)=>{const body=new FormData();body.append('ltp_file',ltp);body.append('ltd_file',ltd);body.append('display_name',display_name);return request<Profile>('/profiles/quick',{method:'POST',body});},recognize:(file_ids:string[],resolutions:Resolution[]=[])=>request<Recognition>('/measurements/recognize',{method:'POST',body:JSON.stringify({file_ids,resolutions})}),resolveD2d:(body:components['schemas']['D2DRecognitionRequest'])=>request<Recognition>('/measurements/resolve-d2d',{method:'POST',body:JSON.stringify(body)}),enqueue:(proposal:Proposal)=>request<{analysis_id:string;job_id:string}>('/analyses',{method:'POST',body:JSON.stringify(proposal)}),createComparison:()=>request<Comparison>('/comparisons',{method:'POST',body:'{}'}),updateComparison:(id:string,expected_version:number,common_settings:Record<string,unknown>,cards:Card[])=>request<Comparison>(`/comparisons/${id}/draft`,{method:'PUT',body:JSON.stringify(draftUpdate(expected_version,common_settings,cards))}),runComparison:(id:string,expected_version:number)=>request<Comparison>(`/comparisons/${id}/run`,{method:'POST',body:JSON.stringify({expected_version})}),saveComparison:(id:string,name:string)=>request<Comparison>(`/comparisons/${id}/save`,{method:'POST',body:JSON.stringify({name})}),cloneComparison:(id:string,operation_id:string)=>request<Comparison>(`/comparisons/${id}/clone`,{method:'POST',body:JSON.stringify({operation_id})}),discardComparison:(id:string)=>request<Comparison>(`/comparisons/${id}/discard`,{method:'POST'})};
export const profileKey=(p:Profile)=>`${p.profile_id}:${p.revision}`;
export const analysisId=(a:Analysis)=>a.analysis_id||a.id||'';

export const analysisKind=(a:Analysis)=>a.kind||a.request?.kind||'iv';
export const analysisCondition=(a:Analysis)=>a.condition_id||a.request?.inputs?.[0]?.condition_id||'';



