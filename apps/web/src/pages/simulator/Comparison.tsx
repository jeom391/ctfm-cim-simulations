import {useEffect,useRef,useState} from 'react';
import {api,ApiError,type Experiment,type Profile,type Row} from '../../lib/api';
import {c2cBasisLabels,cardProblems,commonSettings,createDraftSaver,defaultCommon,editableCard,experimentNeedsReload,isLegacyRetentionRecord,restoreCommon,toCsv,type C2cBasis,type Card,type CardUploadState,type Comparison,type CommonForm} from '../../lib/workflows';
import {DataTable,Downloads,ErrorNotice,Field,Heading,JobProgress,JsonDetails,Notices,Panel,PlotArtifacts,Status,useResource,PpaPanel} from '../../shared';

const pct=(v:unknown)=>typeof v==='number'?`${(v*100).toFixed(2)}%`:'—';
const pp=(v:unknown)=>typeof v==='number'?`${v>0?'+':''}${v.toFixed(2)} %p`:'—';
// Legacy (pre-simplification) rendering: full raw-field table + the old time/year plot, kept
// as it always was. A record that ever touched Retention renders this way so those saved results
// stay inspectable, distinguished from -- never merged into -- the simplified screen below.
const rowOf=(run:Row,card?:Card)=>({카드:card?.display_name||'공통',후보:run.candidate_id??null,유형:run.kind??null,풀:run.pool??null,매핑:run.mapping??null,배열:run.array_index??null,재기록:run.reprogram_index??null,연수:run.years??null,상태:run.status??null,사유:run.reason??null,정확도:pct(run.accuracy),'D0 손실':pp(run.loss_vs_digital_pp),'M0 손실':pp(run.loss_vs_mapped_pp),'Retention 손실':pp(run.retention_loss_pp)});

interface CardUpload extends CardUploadState {names:{ltp:string;ltd:string}|null}
const emptyUpload=():CardUpload=>({ltp:null,ltd:null,busy:false,error:null,names:null});
const sourceNames=(p:Profile)=>{const s=(p.sources||[]) as {direction?:string;filename?:string}[];return {ltp:s.find(x=>x.direction==='ltp')?.filename||'LTP',ltd:s.find(x=>x.direction==='ltd')?.filename||'LTD'};};

function conditionsLine(settings:Record<string,unknown>){
 const effects=(settings.effects||{}) as Record<string,boolean>,hardware=(settings.hardware||{}) as Record<string,unknown>;
 return ['MNIST · MLP 784-128-10 · 64×64 배열',effects.adc?`ADC ${hardware.adc_bits} bit`:'ADC OFF',effects.d2d?`D2D ON · 배열 ${settings.arrays}개`:'D2D OFF',effects.c2c?`C2C ON · 재기록 ${settings.n_reprogram}회`:'C2C OFF'].join(' · ');
}

interface ProfileRow {name:string;mapped:number|null;applied:number|null;delta:number|null;n:number;note:string|null;c2c:number|null;d2d:number|null}
export function profileRows(cards:Comparison['cards'],candidates:{profile_id:string;c2c?:{cv_percent:number}|null;d2d?:{cv_percent:number}|null}[]=[]):ProfileRow[]{
 return cards.map(card=>{
  const runs=card.runs||[];
  const m0=runs.find(r=>r.kind==='M0');
  const all=runs.filter(r=>r.kind==='ALL');
  const ok=all.filter(r=>r.status==='succeeded'&&typeof r.accuracy==='number');
  const mapped=typeof m0?.accuracy==='number'?m0.accuracy as number:null;
  const applied=ok.length?ok.reduce((sum,r)=>sum+(r.accuracy as number),0)/ok.length:null;
  const failed=all.filter(r=>r.status!=='succeeded');
  const note=!runs.length?(card.reason||'실행되지 않음'):failed.length?`${failed.length}건 실패${failed[0].reason?`: ${failed[0].reason}`:''}`:null;
  // CV values the engine actually used (effective config), not what the form currently shows.
  const used=candidates.find(c=>c.profile_id===card.profile_ref?.id);
  return {name:card.display_name,mapped,applied,delta:mapped!=null&&applied!=null?applied-mapped:null,n:ok.length,note,c2c:used?.c2c?.cv_percent??null,d2d:used?.d2d?.cv_percent??null};
 });
}

// Plain inline SVG: one grouped bar pair per profile, fixed 0-100% range, exact values labelled,
// digital baseline as one dashed reference line. Same rows as the table below.
function AccuracyChart({rows,baseline}:{rows:ProfileRow[];baseline:number|null}){
 const valid=rows.filter(r=>r.mapped!=null||r.applied!=null);
 if(!valid.length)return null;
 const groupW=Math.max(110,560/valid.length),ML=50,MR=20,MT=24,MB=52,W=ML+MR+groupW*valid.length,H=330,plotH=H-MT-MB;
 const barW=Math.min(36,groupW/3);
 const y=(percent:number)=>MT+plotH*(1-percent/100);
 return <div className="chart-scroll"><svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="프로필별 매핑 후·효과 적용 후 정확도 막대그래프">
  {[0,25,50,75,100].map(t=><g key={t}><line x1={ML} x2={W-MR} y1={y(t)} y2={y(t)} stroke="var(--rule)"/><text x={ML-8} y={y(t)+4} fontSize={11} textAnchor="end" fill="var(--muted)">{t}%</text></g>)}
  {baseline!=null&&<g><line x1={ML} x2={W-MR} y1={y(baseline*100)} y2={y(baseline*100)} stroke="var(--muted)" strokeDasharray="4 3"/></g>}
  {valid.map((r,i)=>{const cx=ML+groupW*i+groupW/2;return <g key={i}>
   {r.mapped!=null&&<g><rect x={cx-barW-2} y={y(r.mapped*100)} width={barW} height={plotH*r.mapped} fill="var(--bar-soft)"/><text x={cx-barW/2-2} y={y(r.mapped*100)-4} fontSize={10} textAnchor="middle">{pct(r.mapped)}</text></g>}
   {r.applied!=null&&<g><rect x={cx+2} y={y(r.applied*100)} width={barW} height={plotH*r.applied} fill="var(--accent)"/><text x={cx+barW/2+2} y={y(r.applied*100)-4} fontSize={10} textAnchor="middle">{pct(r.applied)}</text></g>}
   <text x={cx} y={H-MB+18} fontSize={12} textAnchor="middle">{r.name.length>14?r.name.slice(0,13)+'…':r.name}</text>
  </g>;})}
  <g transform={`translate(${ML},${H-16})`}><rect width={10} height={10} fill="var(--bar-soft)"/><text x={14} y={9} fontSize={11}>매핑 후</text><rect x={76} width={10} height={10} fill="var(--accent)"/><text x={90} y={9} fontSize={11}>효과 적용 후</text>{baseline!=null&&<><line x1={176} x2={196} y1={5} y2={5} stroke="var(--muted)" strokeDasharray="4 3"/><text x={200} y={9} fontSize={11}>디지털 기준 {pct(baseline)}</text></>}</g>
 </svg></div>;
}

function LegacyComparisonResults({record,experiment}:{record:Comparison;experiment:ReturnType<typeof useResource<Experiment>>}){
 const baseline=(experiment.data?.runs||[]).filter(r=>r.kind==='D0'||r.kind==='D1');
 const rows=record.cards.flatMap(c=>(c.runs||[]).map(r=>rowOf(r,c)));
 return <>
  <p className="muted">Retention 비이상성을 포함한 이전 방식 결과이며, 과거 기록 그대로 상세 표와 그래프를 보존해 보여줍니다.</p>
  <DataTable caption="공통 D0 / D1 기준" rows={baseline.map(r=>rowOf(r))}/>
  {record.cards.map(c=><div key={c.card_id} className="subsection"><h3>{c.display_name} · <Status value={c.status}/></h3>{c.reason&&<p>{c.reason}</p>}</div>)}
  <DataTable caption="카드별 M0 / 효과 실행 · 누락값은 —" rows={rows}/>
  {experiment.data&&<PlotArtifacts items={experiment.data.artifacts}/>}
 </>;
}

function download(name:string,text:string){const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}

export function ComparisonResults({record}:{record:Comparison}){
 const experiment=useResource<Experiment>(record.experiment_id?`/experiments/${record.experiment_id}`:null);
 const previousLifecycle=useRef(record.lifecycle);
 useEffect(()=>{if(experimentNeedsReload(previousLifecycle.current,record.lifecycle))experiment.reload();previousLifecycle.current=record.lifecycle;},[record.lifecycle,record.experiment_id]);
 const legacy=isLegacyRetentionRecord(record);
 const settings=record.common_settings||{};const effects=(settings.effects||{}) as Record<string,boolean>;
 const d0=(experiment.data?.runs||[]).find(r=>r.kind==='D0');
 const d1=(experiment.data?.runs||[]).find(r=>r.kind==='D1');
 const candidates=((experiment.data?.effective_config as {candidates?:{profile_id:string;c2c?:{cv_percent:number}|null;d2d?:{cv_percent:number}|null}[]}|undefined)?.candidates)||[];
 const rows=profileRows(record.cards,candidates);
 const table=rows.map(r=>({프로필:r.name,...(effects.c2c?{'C2C CV (%)':r.c2c??'—'}:{}),...(effects.d2d?{'D2D CV (%)':r.d2d??'—'}:{}),'매핑 후 정확도':pct(r.mapped),'효과 적용 후 정확도':r.applied!=null?pct(r.applied)+(r.n>1?` (${r.n}회 평균)`:''):'—','변화 (%p)':r.delta!=null?pp(r.delta*100):'—',...(rows.some(x=>x.note)?{상태:r.note||'완료'}:{})}));
 const csv=()=>download(`${record.name||'시뮬레이션'}_결과.csv`.replace(/[\\/:*?"<>|]/g,'_'),toCsv([...table.map(r=>({...r,조건:conditionsLine(settings)})),...(d0?[{프로필:'디지털 기준 (FP32)','매핑 후 정확도':pct(d0.accuracy)}]:[])]));
 return <Panel title={record.name||'시뮬레이션 결과'} aside={<Status value={record.outcome||record.lifecycle}/>}>
  <ErrorNotice error={experiment.error} retry={experiment.reload}/>
  {legacy?<LegacyComparisonResults record={record} experiment={experiment}/>:<>
   <p className="fixed-conditions">{conditionsLine(settings)}{record.c2c_basis?` · C2C 입력 기준: ${c2cBasisLabels[record.c2c_basis as C2cBasis]}`:''}</p>
   {d0&&<p>디지털(FP32) 기준 정확도 <strong>{pct(d0.accuracy)}</strong>{d1&&` · 입력 8 bit 양자화만 적용 ${pct(d1.accuracy)}`}</p>}
   <AccuracyChart rows={rows} baseline={typeof d0?.accuracy==='number'?d0.accuracy:null}/>
   <DataTable caption="프로필별 정확도" rows={table}/>
   <p className="muted">변화 = 효과 적용 후 − 매핑 후 (%p). 실패하거나 실행되지 않은 값은 0이 아니라 —로 표시하고 상태 열에 이유를 적습니다.</p>
   {experiment.data&&<button type="button" onClick={csv}>결과 표 CSV 내려받기</button>}
  </>}
  {experiment.data&&<><Notices items={experiment.data.warnings}/><JsonDetails title="재현 정보 (고급) · checkpoint · 실제 적용 설정" value={{checkpoint_id:experiment.data.checkpoint_id,engine:(experiment.data.effective_config as {engines?:unknown}|undefined)?.engines,candidates,summary:experiment.data.summary}}/></>}
 </Panel>;
}

export function HistoricalExperiment({id}:{id:string}){const result=useResource<Experiment>(`/experiments/${id}`);return <><Heading eyebrow="HISTORICAL RESULT" title="이전 실험 결과">당시 저장된 설정과 PPA를 그대로 표시합니다.</Heading><Panel title="실험 결과"><ErrorNotice error={result.error} retry={result.reload}/>{result.loading&&<p>결과 불러오는 중…</p>}{result.data&&<><p><Status value={result.data.status}/></p><DataTable rows={(result.data.runs||[]).map(r=>rowOf(r))}/><JsonDetails title="당시 요청 · 설정 · 상세 집계" value={{request:result.data.request,summary:result.data.summary,hardware:result.data.hardware,engines:result.data.engines}}/><PpaPanel ppa={result.data.ppa}/><PlotArtifacts items={result.data.artifacts}/><Downloads items={result.data.artifacts}/></>}</Panel></>;}

function ProfileCard({card,index,upload,problems,form,onName,onFiles,onCv,onRemove}:{card:Card;index:number;upload:CardUpload;problems:string[];form:CommonForm;onName:(v:string)=>void;onFiles:(patch:{ltp?:File|null;ltd?:File|null})=>void;onCv:(key:'manual_c2c_cv_percent'|'manual_d2d_cv_percent',v:number|null)=>void;onRemove:()=>void}){
 const id=card.card_id;
 const file=(dir:'ltp'|'ltd')=>{const picked=upload[dir];const done=upload.names?.[dir];return <div className="ltm-file"><span>{dir.toUpperCase()} 파일</span>
  {/* Native input kept for keyboard/screen readers, visually replaced by the label button. */}
  <input id={`${id}-${dir}`} className="visually-hidden" type="file" accept=".csv,.xlsx" disabled={upload.busy} onChange={e=>{onFiles({[dir]:e.target.files?.[0]||null});e.target.value='';}}/>
  <label htmlFor={`${id}-${dir}`} className="button file-button">{done||picked?'다른 파일 선택':'파일 선택'}</label>
  <span className={'file-state'+(done&&!picked?' ok':'')}>{picked?picked.name:done?<>{done} <b>업로드 완료</b></>:'선택 안 됨'}</span></div>;};
 return <section className="profile-card" role="listitem" aria-label={`프로필 ${index+1}: ${card.display_name||'이름 없음'}`}>
  <Field label="소자 이름"><input id={`name-${id}`} value={card.display_name} maxLength={200} onChange={e=>onName(e.target.value)}/></Field>
  <div className="ltm-zone"><strong>LTM 파일</strong>{file('ltp')}{file('ltd')}
   {upload.busy&&<p className="muted" role="status">업로드·인식·분석 중…</p>}
   {upload.error&&<p className="card-error" role="alert">{upload.error}{card.profile_ref?' 이전에 올린 파일은 그대로 유지됩니다.':''}</p>}
  </div>
  <Field label={`C2C 편차 CV (%)${form.c2c?'':' · 공통 설정에서 꺼짐'}`}><input type="number" min="0" step="any" inputMode="decimal" value={card.manual_c2c_cv_percent??''} placeholder={form.c2c?'필수':'미사용'} onChange={e=>onCv('manual_c2c_cv_percent',e.target.value===''?null:Number(e.target.value))}/></Field>
  <Field label={`D2D 편차 CV (%)${form.d2d?'':' · 공통 설정에서 꺼짐'}`}><input type="number" min="0" step="any" inputMode="decimal" value={card.manual_d2d_cv_percent??''} placeholder={form.d2d?'필수':'미사용'} onChange={e=>onCv('manual_d2d_cv_percent',e.target.value===''?null:Number(e.target.value))}/></Field>
  {problems.length>0&&<ul className="card-problems">{problems.map(p=><li key={p}>{p}</li>)}</ul>}
  <button type="button" className="danger-link" onClick={onRemove}>삭제</button>
 </section>;
}

export function ComparisonPage(){
 const idFromUrl=new URLSearchParams(location.search).get('comparison');
 const[id,setId]=useState<string|null>(idFromUrl),[record,setRecord]=useState<Comparison|null>(null),[form,setForm]=useState<CommonForm>(defaultCommon),[cards,setCards]=useState<Card[]>([]),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[notice,setNotice]=useState(''),[name,setName]=useState(''),[basis,setBasis]=useState<C2cBasis|''>(''),[uploads,setUploads]=useState<Record<string,CardUpload>>({});
 const recordRef=useRef<Comparison|null>(null),editRef=useRef({form:defaultCommon,cards:[] as Card[],token:0,dirty:false}),saverRef=useRef<{flush:()=>Promise<void>}|null>(null),cloneOp=useRef<string|null>(null),focusCard=useRef<string|null>(null),stripRef=useRef<HTMLDivElement|null>(null),uploadsRef=useRef(uploads);
 uploadsRef.current=uploads;
 const temporary=useResource<{items:Comparison[]}>('/comparisons?scope=temporary');
 const setCurrent=(r:Comparison,hydrate=true)=>{recordRef.current=r;setRecord(r);setId(r.comparison_id);history.replaceState(null,'',`/simulator?comparison=${r.comparison_id}`);if(hydrate){const nextForm=restoreCommon(r.common_settings),nextCards=r.cards.map(editableCard);editRef.current={form:nextForm,cards:nextCards,token:editRef.current.token+1,dirty:false};setForm(nextForm);setCards(nextCards);setDirty(false);}setName(r.name||'');};
 const reload=async()=>{if(!id)return;try{const r=await api.get<Comparison>(`/comparisons/${id}`);setCurrent(r);setError(null);}catch(e){setError(e);}};
 useEffect(()=>{if(id)void reload();},[id]);
 useEffect(()=>{if(!id||record?.lifecycle!=='running')return;const t=setInterval(()=>void reload(),2000);return()=>clearInterval(t);},[id,record?.lifecycle]);
 // A card already carrying a profile_ref (reload/clone/reopen) has no local File objects, so the
 // uploaded file names come from the published profile's own sources.
 useEffect(()=>{cards.forEach(card=>{if(!card.profile_ref||uploads[card.card_id]?.names||uploads[card.card_id]?.busy)return;const ref=card.profile_ref;api.get<Profile>(`/profiles/${ref.id}/revisions/${ref.revision}`).then(p=>setUploads(x=>({...x,[card.card_id]:{...(x[card.card_id]||emptyUpload()),names:sourceNames(p)}}))).catch(()=>{});});},[cards]);
 useEffect(()=>{const target=focusCard.current;if(!target)return;focusCard.current=null;const el=document.getElementById(`name-${target}`) as HTMLInputElement|null;el?.closest('.profile-card')?.scrollIntoView({behavior:'smooth',inline:'end',block:'nearest'});el?.focus({preventScroll:true});},[cards]);
 // Edits always build on the latest edit snapshot, so an upload finishing late never drops a card added meanwhile.
 const changed=(update:(cards:Card[],form:CommonForm)=>{cards?:Card[];form?:CommonForm})=>{const current=editRef.current;const next=update(current.cards,current.form);const nextCards=next.cards??current.cards,nextForm=next.form??current.form;editRef.current={form:nextForm,cards:nextCards,token:current.token+1,dirty:true};setCards(nextCards);setForm(nextForm);setDirty(true);};
 const patchForm=(patch:Partial<CommonForm>)=>changed((_,f)=>({form:{...f,...patch}}));
 const patchCard=(cardId:string,patch:Partial<Card>)=>changed(cs=>({cards:cs.map(c=>c.card_id===cardId?{...c,...patch}:c)}));
 const persist=async():Promise<Comparison|null>=>{if(!saverRef.current)saverRef.current=createDraftSaver(()=>{const current=recordRef.current,edit=editRef.current;if(!current||current.lifecycle!=='drafting'||!edit.dirty||edit.cards.some(c=>!c.display_name.trim()))return null;return {token:edit.token,value:{id:current.comparison_id,version:current.version,settings:commonSettings(edit.form),cards:edit.cards.map(editableCard)}};},payload=>api.updateComparison(payload.id,payload.version,payload.settings,payload.cards),(saved,token)=>{if(recordRef.current?.comparison_id!==saved.comparison_id)return;recordRef.current=saved;setRecord(saved);if(editRef.current.token===token){editRef.current.dirty=false;setDirty(false);}});try{await saverRef.current.flush();setError(null);return recordRef.current;}catch(e){setError(e);if((e as {status?:number}).status===409){setNotice('다른 탭에서 내용이 바뀌었습니다. 서버 내용을 다시 불러왔습니다.');await reload();}return null;}};
 useEffect(()=>{if(!dirty||record?.lifecycle!=='drafting')return;const t=setTimeout(()=>void persist(),650);return()=>clearTimeout(t);},[dirty,cards,form,record?.version,record?.lifecycle]);
 const create=async()=>{setBusy(true);setError(null);try{const draft=await api.createComparison();const first:Card={card_id:crypto.randomUUID(),display_name:'소자 1',c2c_approved_assumption:false,cross_condition_acknowledged:false};setCurrent(await api.updateComparison(draft.comparison_id,draft.version,commonSettings(defaultCommon),[first]));setNotice('');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const run=async()=>{setBusy(true);setError(null);try{const saved=await persist();if(!saved||editRef.current.dirty)return;const r=await api.runComparison(saved.comparison_id,saved.version);setCurrent(r);setNotice(r.job_id?'':'실행할 수 있는 프로필이 없어 결과 없이 끝났습니다. 각 카드의 사유를 확인하세요.');temporary.reload();window.scrollTo({top:0});}catch(e){setError(e);}finally{setBusy(false);}};
 const save=async()=>{if(!record||!name.trim())return;setBusy(true);setError(null);try{setCurrent(await api.saveComparison(record.comparison_id,name.trim(),basis||null));setNotice('이름을 붙여 저장했습니다. 다시 실행하지 않았습니다.');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const clone=async()=>{if(!record)return;cloneOp.current??=crypto.randomUUID();setBusy(true);setError(null);try{const r=await api.cloneComparison(record.comparison_id,cloneOp.current);cloneOp.current=null;setUploads({});setCurrent(r);setBasis('');setNotice('같은 파일·설정으로 새 시뮬레이션을 만들었습니다. 바꿀 카드의 파일이나 값만 수정하세요.');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const discard=async()=>{if(!record)return;setBusy(true);setError(null);try{const r=await api.discardComparison(record.comparison_id);setRecord(r);recordRef.current=r;setNotice('임시 시뮬레이션을 폐기했습니다. 저장한 결과와 올린 파일은 지우지 않습니다.');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const patchUpload=(cardId:string,patch:Partial<CardUpload>)=>setUploads(x=>({...x,[cardId]:{...(x[cardId]||emptyUpload()),...patch}}));
 const uploadCard=async(cardId:string)=>{
  const u=uploadsRef.current[cardId]||emptyUpload(),card=editRef.current.cards.find(c=>c.card_id===cardId);
  if(!card||!u.ltp||!u.ltd)return;
  if(!card.display_name.trim()){patchUpload(cardId,{error:'소자 이름을 먼저 입력하세요.'});return;}
  patchUpload(cardId,{busy:true,error:null});
  try{
   const p=await api.createProfileQuick(u.ltp,u.ltd,card.display_name.trim());
   patchCard(cardId,{profile_ref:{id:p.profile_id,revision:p.revision}});
   patchUpload(cardId,{busy:false,error:null,names:sourceNames(p),ltp:null,ltd:null});
  }catch(e){
   // A bad re-upload never clears the card's previous valid profile or touches other cards.
   const detail=e instanceof ApiError?e.message:String(e);
   patchUpload(cardId,{busy:false,error:`${detail} LTP와 LTD 파일이 같은 조건의 쌍인지 확인한 뒤 다시 고르세요.`,ltp:null,ltd:null});
  }
 };
 const pickFiles=(cardId:string,patch:{ltp?:File|null;ltd?:File|null})=>{const next={...(uploadsRef.current[cardId]||emptyUpload()),...patch,error:null};uploadsRef.current={...uploadsRef.current,[cardId]:next};setUploads(uploadsRef.current);if(next.ltp&&next.ltd)void uploadCard(cardId);};
 const addCard=()=>{const card:Card={card_id:crypto.randomUUID(),display_name:`소자 ${editRef.current.cards.length+1}`,c2c_approved_assumption:false,cross_condition_acknowledged:false};focusCard.current=card.card_id;changed(cs=>({cards:[...cs,card]}));};
 const removeCard=(cardId:string)=>{changed(cs=>({cards:cs.filter(c=>c.card_id!==cardId)}));setUploads(x=>{const{[cardId]:_,...rest}=x;return rest;});};

 if(!record||record.lifecycle==='discarded')return <><Heading eyebrow="CIM SIMULATION" title="CIM 시뮬레이션">소자마다 LTP/LTD 파일을 올리고 공통 조건으로 MNIST 정확도를 비교합니다. 측정 분석을 먼저 하지 않아도 됩니다.</Heading>{notice&&<p role="status">{notice}</p>}<ErrorNotice error={error}/><Panel title="시작하기"><button className="primary" disabled={busy} onClick={()=>void create()}>새 시뮬레이션</button>{!!temporary.data?.items.length&&<><h3 className="subhead">이어서 할 임시 작업</h3><ul className="activity-list">{temporary.data.items.map(r=><li key={r.comparison_id}><a href={`/simulator?comparison=${r.comparison_id}`}><strong>{r.name||r.cards.map(c=>c.display_name).join(', ')||'빈 시뮬레이션'}</strong><small>{r.updated_at.slice(0,16).replace('T',' ')}</small></a><Status value={r.lifecycle}/></li>)}</ul></>}</Panel></>;

 const problems=cardProblems(cards,form,uploads);
 const blocking=!cards.length?['프로필을 하나 이상 추가하세요.']:Object.values(problems).flat();
 return <><Heading eyebrow="CIM SIMULATION" title="CIM 시뮬레이션"/>{notice&&<p role="status" aria-live="polite">{notice}</p>}<ErrorNotice error={error}/>
  {record.lifecycle==='drafting'&&<>
   <Panel title="디바이스 프로필" aside={<span className="muted">{dirty?'저장 대기 중…':'자동 저장됨'}</span>}>
    <p className="muted">카드마다 소자 이름과 LTP·LTD 파일 한 쌍을 올리면 자동으로 인식·분석해 프로필을 만듭니다. C2C·D2D 편차는 측정 분석 결과에서 복사해 넣을 수 있습니다.</p>
    <div className="card-strip" ref={stripRef} role="list" aria-label="디바이스 프로필 카드 · 가로로 스크롤" tabIndex={0}>
     {cards.map((card,index)=><ProfileCard key={card.card_id} card={card} index={index} upload={uploads[card.card_id]||emptyUpload()} problems={problems[card.card_id]||[]} form={form}
      onName={v=>patchCard(card.card_id,{display_name:v})} onFiles={patch=>pickFiles(card.card_id,patch)}
      onCv={(key,v)=>patchCard(card.card_id,{[key]:v})} onRemove={()=>removeCard(card.card_id)}/>)}
     <button type="button" className="add-card" onClick={addCard}><span aria-hidden>+</span>프로필 추가</button>
    </div>
   </Panel>
   <Panel title="공통 실행 설정">
    <p className="fixed-conditions">MNIST · MLP 784-128-10 · 64×64 배열 · 입력 8 bit (고정)</p>
    <div className="common-row">
     <div><label className="check"><input type="checkbox" checked={form.adc} onChange={e=>patchForm({adc:e.target.checked})}/>ADC 양자화</label><Field label="ADC 비트"><select disabled={!form.adc} value={form.adcBits} onChange={e=>patchForm({adcBits:Number(e.target.value)})}>{[3,4,5,6,7,8].map(n=><option key={n} value={n}>{n} bit</option>)}</select></Field></div>
     <div><label className="check"><input type="checkbox" checked={form.d2d} onChange={e=>patchForm({d2d:e.target.checked})}/>D2D 편차 반영</label><Field label="배열 생성 수" hint="서로 다른 D2D 실현(배열) 수"><input type="number" min="1" max="100" disabled={!form.d2d} value={form.d2d?form.arrays:1} onChange={e=>patchForm({arrays:Number(e.target.value)})}/></Field></div>
     <div><label className="check"><input type="checkbox" checked={form.c2c} onChange={e=>patchForm({c2c:e.target.checked})}/>C2C 편차 반영</label><Field label="재기록 횟수" hint="같은 배열을 다시 기록하는 횟수"><input type="number" min="1" max="100" disabled={!form.c2c} value={form.c2c?form.nReprogram:1} onChange={e=>patchForm({nReprogram:Number(e.target.value)})}/></Field></div>
    </div>
    <p className="muted">정확도 엔진 AIHWKit · ADC는 두 경로를 각각 변환한 뒤 차감 · checkpoint와 seed는 모든 프로필에 같게 고정됩니다. Retention과 PPA는 이 시뮬레이션에서 다루지 않습니다.</p>
   </Panel>
   <div className="run-bar">
    {blocking.length>0&&<p className="notice" role="status">실행 전에 확인할 항목 {blocking.length}개 · 카드에 표시했습니다.</p>}
    <button className="primary run" disabled={busy||blocking.length>0} onClick={()=>void run()}>{busy?'요청 중…':'시뮬레이션 실행 →'}</button>
    <p className="muted">실행하면 진행 상황과 결과 화면으로 이동합니다. <button type="button" className="subtle" disabled={busy} onClick={()=>void discard()}>이 임시 작업 폐기</button></p>
   </div>
  </>}
  {record.lifecycle==='running'&&<><Panel title="진행 상황"><p className="fixed-conditions">{conditionsLine(record.common_settings||{})}</p><p>{record.cards.filter(c=>c.status!=='blocked').map(c=>c.display_name).join(', ')}</p>{record.cards.some(c=>c.status==='blocked')&&<Notices title="실행에서 빠진 카드" items={record.cards.filter(c=>c.status==='blocked').map(c=>`${c.display_name}: ${c.reason}`)}/>}</Panel><JobProgress id={record.job_id||null} onDone={()=>void reload()}/></>}
  {(record.lifecycle==='temporary'||record.lifecycle==='saved')&&<><ComparisonResults record={record}/>
   <Panel title={record.lifecycle==='saved'?'저장됨':'결과 저장'}>
    {record.lifecycle==='temporary'?<>
     <Field label="결과 이름"><input value={name} maxLength={200} onChange={e=>setName(e.target.value)} placeholder="예: A1–A5 · ADC 5bit · C2C 추세 제거"/></Field>
     {(record.common_settings?.effects as {c2c?:boolean}|undefined)?.c2c&&<fieldset><legend>C2C CV 입력값의 기준</legend>{(Object.keys(c2cBasisLabels) as C2cBasis[]).map(k=><label key={k} className="check"><input type="radio" name="c2c-basis" checked={basis===k} onChange={()=>setBasis(k)}/>{c2cBasisLabels[k]}</label>)}</fieldset>}
     <div className="actions"><button className="primary" disabled={busy||!name.trim()||(!!(record.common_settings?.effects as {c2c?:boolean}|undefined)?.c2c&&!basis)} onClick={()=>void save()}>이름 붙여 저장</button><button disabled={busy} onClick={()=>void clone()}>설정 복제해 새 시뮬레이션</button><button className="subtle" disabled={busy} onClick={()=>void discard()}>임시 결과 폐기</button></div>
    </>:<div className="actions"><span>{record.name}</span><button disabled={busy} onClick={()=>void clone()}>설정 복제해 새 시뮬레이션</button><a className="button" href="/saved-results">저장한 결과 목록</a></div>}
   </Panel></>}
 </>;
}
