import {useState} from 'react';
import {api} from '../../lib/api';
import {activeResolutions,d2dPairDevices,recognizedChoices,type Recognition,type Resolution,type Proposal} from '../../lib/workflows';
import {ErrorNotice,Field,JobProgress,Panel,Status} from '../../shared';

export const kindLabels:Record<string,string>={pulse_states:'LTP / LTD 상태',iv:'Vth / MW',retention:'Retention',c2c_detrended:'C2C (반복 P/E)',c2c_sweep:'C2C (반복 스윕)',d2d:'D2D'};
type Source=Recognition['sources'][number];
const issueText=(x:{code:string;detail:string;sheet?:string|null;source_row?:number|null;cell?:string|null;block?:number|null})=>`${x.detail}${x.sheet?` · ${x.sheet}`:''}${x.source_row!=null?` · 원본 ${x.source_row}행`:''}${x.cell?` · ${x.cell}`:''}${x.block!=null?` · 블록 ${x.block}`:''}`;
const inputLabel=(p:Proposal,plan:Recognition)=>{
 const inputs=p.inputs as {file_id:string;selection?:{type?:string;block?:number;segment?:number};branch?:string;sweep_amplitude_v?:number}[];
 if(p.kind==='d2d'){const names=[...new Set(inputs.map(i=>plan.sources.find(s=>s.file_id===i.file_id)?.name||i.file_id))];return `${names.join(' ↔ ')} · 대응 조건 ${inputs.length/2}개`;}
 return inputs.map(i=>{const s=plan.sources.find(s=>s.file_id===i.file_id);return `${s?.name||i.file_id}${i.selection?.type==='iv_block'?` · 블록 ${i.selection.block} / 구간 ${i.selection.segment}`:''}${i.branch?` · ${i.branch}`:''}${i.sweep_amplitude_v!=null?` · ${i.sweep_amplitude_v} V`:''}`;}).join(' + ');
};
const UNIT_CHOICES:Record<string,string[]>={time:['s','ms'],vgs_v:['V','mV'],current:['A','mA','uA','nA']};
const unitChoices=(role:string)=>role.endsWith('time_s')?UNIT_CHOICES.time:role==='vgs_v'?UNIT_CHOICES.vgs_v:UNIT_CHOICES.current;

function SourceDetails({s,resolution,update}:{s:Source;resolution:Partial<Resolution>;update:(patch:Partial<Resolution>)=>void}){
 const issues=s.issues||[],codes=new Set(issues.map(i=>i.code));
 const layout=s.layout as {columns?:string[];sheets?:string[];blocks?:{index:number;status:string;error?:string;proposed_amplitude_v?:number}[]}|null;
 const project=(s.evidence||[]).filter(e=>e.scope==='project_assumption'||e.scope==='project_source');
 const file=(s.evidence||[]).filter(e=>e.scope!=='project_assumption'&&e.scope!=='project_source');
 const select=(label:string,value:string,options:string[],onChange:(v:string)=>void)=><Field key={label} label={label}><select value={value} onChange={e=>onChange(e.target.value)}><option value="">선택</option>{options.map(o=><option key={o}>{o}</option>)}</select></Field>;
 return <details open={s.status==='needs_choice'||s.status==='invalid'}>
  <summary>{s.name} · {kindLabels[s.kind||'']||'종류 미상'} · {s.condition_id||'조건 미상'} · <Status value={s.status}/></summary>
  {issues.length>0&&<ul>{issues.map((x,i)=><li key={i}>{issueText(x)}</li>)}</ul>}
  {project.length>0&&<p className="muted">프로젝트 조건·가정(파일 측정값 아님): {project.map(e=>`${e.field} ${JSON.stringify(e.value)}`).join(' · ')}</p>}
  {s.warnings?.length>0&&<ul className="muted">{s.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul>}
  {file.length>0&&<details><summary>인식 근거 {file.length}개 · 시트 {s.sheet||'—'} · SHA-256 {s.sha256.slice(0,12)}</summary><ul>{file.map((e,i)=><li key={i}>{e.field}: {JSON.stringify(e.value)} · {e.scope} · {e.detail}</li>)}</ul></details>}
  {s.status==='needs_choice'&&<div className="form-grid">
   <Field label="선택 사유"><input value={resolution.reason||''} onChange={e=>update({reason:e.target.value})}/></Field>
   {(!s.kind||codes.has('invalid_resolution'))&&<Field label="분석 종류"><select value={resolution.kind||''} onChange={e=>update({kind:e.target.value as Resolution['kind']})}><option value="">선택</option>{Object.entries(kindLabels).filter(([k])=>k!=='d2d').map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></Field>}
   {(!s.condition_id||codes.has('conflicting_condition'))&&<Field label="조건 ID"><input value={resolution.condition_id||''} onChange={e=>update({condition_id:e.target.value})}/></Field>}
   {Array.isArray(layout?.sheets)&&select('원본 시트',resolution.sheet||'',layout!.sheets!,v=>update({sheet:v}))}
   {s.kind==='pulse_states'&&!s.direction&&select('펄스 방향',resolution.direction||'',['ltp','ltd'],v=>update({direction:v as Resolution['direction']}))}
   {(codes.has('measurement_group_required')||codes.has('pulse_pair_required'))&&<Field label="같은 취득 그룹 ID"><input value={resolution.measurement_group||''} onChange={e=>update({measurement_group:e.target.value})}/></Field>}
   {codes.has('retention_source_required')&&<><Field label="원본 라벨"><input value={resolution.source_label||''} onChange={e=>update({source_label:e.target.value})}/></Field><Field label="읽기 VGS (V)"><input type="number" step="any" value={resolution.read_vgs_v??''} onChange={e=>update({read_vgs_v:e.target.value===''?undefined:Number(e.target.value)})}/></Field></>}
   {codes.has('mapping_units_required')&&['time_s','id_a','vgs_v'].map(role=>select(`원본 열 · ${role}`,resolution.column_mapping?.[role]||'',layout?.columns||[],v=>update({column_mapping:{...resolution.column_mapping,[role]:v}})))}
   {(codes.has('retention_source_required')||codes.has('units_required')||codes.has('mapping_units_required'))&&(codes.has('retention_source_required')?['erase_time_s','erase_id_a','program_time_s','program_id_a']:['time_s','id_a','vgs_v']).map(role=>select(`${role} 단위`,resolution.units?.[role]||'',unitChoices(role),v=>update({units:{...resolution.units,[role]:v}})))}
  </div>}
 </details>;
}

export function Recognition({onQueued}:{onQueued:(analysisId:string,jobId:string)=>void}){
 const[fileIds,setFileIds]=useState<string[]>([]),[plan,setPlan]=useState<Recognition|null>(null),[selected,setSelected]=useState<Set<number>>(new Set()),[submitted,setSubmitted]=useState<Set<number>>(new Set()),[resolutions,setResolutions]=useState<Record<string,Partial<Resolution>>>({}),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[message,setMessage]=useState(''),[page,setPage]=useState(0),[jobs,setJobs]=useState<{analysis_id:string;job_id:string;label:string}[]>([]);
 const[pair,setPair]=useState<[string,string]>(['','']),[d2dCondition,setD2dCondition]=useState('');
 const updateResolution=(id:string,patch:Partial<Resolution>)=>setResolutions(v=>({...v,[id]:{...v[id],...patch}}));
 const adopt=(found:Recognition,text:string)=>{setPlan(found);setSelected(new Set());setSubmitted(new Set());setPage(0);setMessage(text);};
 const upload=async(files:File[])=>{setBusy(true);setError(null);setMessage('파일 업로드 중…');try{const uploaded=await api.upload(files);const ids=uploaded.files.map(f=>f.file_id);setFileIds(ids);setResolutions({});setPlan(null);setPair(['','']);setMessage(`${ids.length}개 파일 인식 중…`);const found=await api.recognize(ids);adopt(found,`${found.sources.length}개 파일 · ${found.requests.length}개 분석 제안`);}catch(e){setError(e);setMessage('');}finally{setBusy(false);}};
 const recognize=async()=>{if(!fileIds.length)return;setBusy(true);setError(null);try{adopt(await api.recognize(fileIds,activeResolutions(fileIds,resolutions)),'선택을 반영했습니다.');}catch(e){setError(e);}finally{setBusy(false);}};
 const enqueue=async()=>{if(!plan)return;const ready=recognizedChoices(plan.requests,selected,submitted);if(!ready.length)return;setBusy(true);setError(null);try{for(const p of ready){const q=await api.enqueue(p);setJobs(old=>[...old,{...q,label:`${kindLabels[p.kind]||p.kind} · ${p.inputs[0]?.condition_id||''} · ${inputLabel(p,plan)}`}]);setSubmitted(old=>new Set(old).add(plan.requests.indexOf(p)));onQueued(q.analysis_id,q.job_id);}setMessage(`${ready.length}개 분석을 실행했습니다.`);setSelected(new Set());}catch(e){setError(e);}finally{setBusy(false);}};
 const ivSources=plan?.sources.filter(s=>s.kind==='iv'&&s.status==='ready')||[];
 const resolvePair=async()=>{setBusy(true);setError(null);try{
  const chosen=pair.map(id=>ivSources.find(s=>s.file_id===id));
  if(chosen.some(s=>!s)||pair[0]===pair[1])throw new Error('서로 다른 IV 파일 두 개를 고르세요.');
  const condition=d2dCondition.trim()||chosen[0]!.condition_id||'';
  if(!condition)throw new Error('D2D 조건 ID를 입력하세요.');
  const found=await api.resolveD2dPair({condition_id:condition,devices:d2dPairDevices(chosen as Source[])});
  // Appended, not replaced: the other proposals of this upload stay runnable (each keeps its own recognition_id).
  setPlan(p=>p&&{...p,sources:p.sources.map(s=>found.sources.find(f=>f.file_id===s.file_id)||s),requests:[...p.requests,...found.requests]});
  setPage(Math.floor((plan!.requests.length)/50));setMessage('D2D 비교 제안을 목록 끝에 추가했습니다.');
 }catch(e){setError(e);}finally{setBusy(false);}};
 const runnable=plan?recognizedChoices(plan.requests,selected,submitted).length:0;
 return <Panel title="측정 파일 올리기" aside={<span className="muted">CSV / XLSX · 한 번에 1~20개</span>}>
  <p>파일을 올리면 종류와 조건을 인식해 분석을 제안합니다. 준비된 분석은 바로 실행하고, Vth/MW는 블록·구간을, D2D는 비교할 두 파일을 고릅니다.</p>
  <label className="upload">측정 파일 선택<input type="file" multiple accept=".csv,.xlsx" disabled={busy} onChange={e=>{const files=Array.from(e.target.files||[]);if(files.length)void upload(files);e.target.value='';}}/></label>
  {message&&<p role="status" aria-live="polite">{message}</p>}<ErrorNotice error={error}/>
  {plan&&<>
   <div className="subsection"><h3>인식 결과</h3>
    {plan.sources.map(s=><SourceDetails key={s.file_id} s={s} resolution={resolutions[s.file_id]||{}} update={patch=>updateResolution(s.file_id,patch)}/>)}
    {fileIds.some(id=>Object.keys(resolutions[id]||{}).some(k=>k!=='reason'))&&<button type="button" disabled={busy} onClick={()=>void recognize()}>선택 적용 후 다시 인식</button>}
    {plan.pulse_pairs.filter(p=>p.status!=='ready').map(p=><p key={p.pair_key} className="notice">{p.condition_id} LTP/LTD 쌍이 완성되지 않았습니다 · <Status value={p.status}/></p>)}
   </div>
   {ivSources.length>=2&&<div className="subsection"><h3>D2D · 두 소자 파일 비교</h3>
    <p className="muted">고른 두 파일을 서로 다른 물리 소자로 보고, 두 파일에 모두 있는 스윕 진폭·분기 조건을 서버가 짝지어 Vg = 0 V 전류(VDS 0.1 V)로 비교합니다. 한 파일에 같은 진폭 블록이 중복되면 그 진폭은 제외하고 사유를 남깁니다.</p>
    <div className="form-grid">
     {[0,1].map(i=><Field key={i} label={`소자 ${i+1} 파일`}><select value={pair[i]} onChange={e=>{const next=[...pair] as [string,string];next[i]=e.target.value;setPair(next);}}><option value="">파일 선택</option>{ivSources.map(s=><option key={s.file_id} value={s.file_id}>{s.condition_id} · {s.name}</option>)}</select></Field>)}
     <Field label="조건 ID" hint="비우면 첫 파일의 조건을 사용합니다."><input value={d2dCondition} placeholder={ivSources.find(s=>s.file_id===pair[0])?.condition_id||''} onChange={e=>setD2dCondition(e.target.value)}/></Field>
    </div>
    <button disabled={busy||!pair[0]||!pair[1]} onClick={()=>void resolvePair()}>D2D 비교 제안 만들기</button>
   </div>}
   <div className="subsection"><h3>분석 제안 · {plan.requests.length}개</h3>
    {plan.requests.length>50&&<div className="actions"><button disabled={page===0} onClick={()=>setPage(page-1)}>이전</button><span>{page+1} / {Math.ceil(plan.requests.length/50)}페이지</span><button disabled={(page+1)*50>=plan.requests.length} onClick={()=>setPage(page+1)}>다음</button></div>}
    {plan.requests.slice(page*50,(page+1)*50).map((p,offset)=>{const i=page*50+offset;return <label className="profile-option" key={i}>{p.kind==='iv'&&<input type="checkbox" aria-label={`Vth/MW 제안 ${i+1} 선택`} checked={selected.has(i)} onChange={e=>setSelected(old=>{const next=new Set(old);e.target.checked?next.add(i):next.delete(i);return next;})}/>}<span><strong>{kindLabels[p.kind]||p.kind} · {p.inputs[0]?.condition_id}</strong><small>{inputLabel(p,plan)}</small><small>{submitted.has(i)?'실행함':p.kind==='iv'?'블록·구간을 체크해 선택':'준비됨'}</small></span></label>;})}
    <button className="primary" disabled={busy||!runnable} onClick={()=>void enqueue()}>분석 {runnable}개 실행</button>
   </div>
  </>}
  {jobs.length>0&&<div className="subsection"><h3>실행한 분석</h3>{jobs.map(j=><div key={j.analysis_id}><a href={`/measurements?analysis=${j.analysis_id}`}>{j.label}</a><JobProgress id={j.job_id} onDone={()=>{}}/></div>)}</div>}
 </Panel>;
}
