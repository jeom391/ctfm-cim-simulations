import {useEffect,useRef,useState} from 'react';
import {api,ApiError,type Experiment,type Profile,type Row} from '../../lib/api';
import {commonSettings,createDraftSaver,defaultCommon,editableCard,experimentNeedsReload,restoreCommon,type Card,type Comparison,type CommonForm} from '../../lib/workflows';
import {DataTable,Downloads,ErrorNotice,Field,Heading,JobProgress,JsonDetails,Notices,Panel,PlotArtifacts,Status,useResource,PpaPanel,show} from '../../shared';

const pct=(v:unknown)=>typeof v==='number'?`${(v*100).toFixed(2)}%`:'—';
const pp=(v:unknown)=>typeof v==='number'?`${v.toFixed(3)} %p`:'—';
// Legacy (pre-simplification) rendering: full raw-field table + the old time/year plot, kept
// byte-for-byte as it always was. A record that ever touched Retention (the only thing the old
// screen's extra columns/plot were ever for) renders this way so those saved results stay fully
// inspectable, distinguished from -- never merged into -- the new simplified screen below.
const rowOf=(run:Row,card?:Card)=>({카드:card?.display_name||'공통',후보:run.candidate_id??null,유형:run.kind??null,풀:run.pool??null,매핑:run.mapping??null,배열:run.array_index??null,재기록:run.reprogram_index??null,연수:run.years??null,상태:run.status??null,사유:run.reason??null,정확도:pct(run.accuracy),'D0 손실':pp(run.loss_vs_digital_pp),'M0 손실':pp(run.loss_vs_mapped_pp),'Retention 손실':pp(run.retention_loss_pp)});
const isLegacyRetentionRecord=(record:Comparison)=>{const settings=(record.common_settings||{}) as {effects?:{retention?:boolean};years?:number[]};return !!settings.effects?.retention||(settings.years?.length||1)>1;};

interface CardUpload {ltp:File|null;ltd:File|null;busy:boolean;error:string|null;info:{condition_id:string;n_states:number;g_min_s:number|null;g_max_s:number|null}|null}
const emptyUpload=():CardUpload=>({ltp:null,ltd:null,busy:false,error:null,info:null});
const profileInfo=(p:Profile)=>({condition_id:p.condition_id,n_states:p.pools.combined?.state_ids.length||0,g_min_s:p.pools.combined?.g_min_s??null,g_max_s:p.pools.combined?.g_max_s??null});

function commonSummaryLine(settings:Record<string,unknown>){
 const effects=(settings.effects||{}) as Record<string,boolean>,hardware=(settings.hardware||{}) as Record<string,unknown>;
 const adc=effects.adc?`ADC ${hardware.adc_bits}bit`:'ADC OFF';
 const d2d=effects.d2d?`D2D ON · 배열 ${settings.arrays}개`:'D2D OFF';
 const c2c=effects.c2c?`C2C ON · 재기록 ${settings.n_reprogram}회`:'C2C OFF';
 return `64×64 배열 · ${adc} · ${d2d} · ${c2c}`;
}

interface ProfileRow {name:string;mapped:number|null;applied:number|null;delta:number|null;n:number;note:string|null}
function profileRows(cards:Comparison['cards']):ProfileRow[]{
 return cards.map(card=>{
  const runs=card.runs||[];
  const m0=runs.find(r=>r.kind==='M0');
  const all=runs.filter(r=>r.kind==='ALL');
  const ok=all.filter(r=>r.status==='succeeded'&&typeof r.accuracy==='number');
  const mapped=typeof m0?.accuracy==='number'?m0.accuracy as number:null;
  const applied=ok.length?ok.reduce((sum,r)=>sum+(r.accuracy as number),0)/ok.length:null;
  const delta=mapped!=null&&applied!=null?applied-mapped:null;
  const failedOne=all.find(r=>r.status!=='succeeded');
  const note=!runs.length?(card.reason||'실행되지 않음'):failedOne?`${all.length-ok.length}건 실패${failedOne.reason?`: ${failedOne.reason}`:''}`:null;
  return {name:card.display_name,mapped,applied,delta,n:ok.length,note};
 });
}

// Plain inline SVG, no charting dependency: one grouped bar pair ("매핑 후" vs "효과 적용 후") per
// profile name, 0-100% fixed range, exact values labeled on each bar, digital baseline as one
// dashed reference line. Replaces the old per-candidate scatter-at-one-x plot, which compared
// nothing meaningful once every profile already shares the same fixed hardware/mapping.
function AccuracyChart({rows,baseline}:{rows:ProfileRow[];baseline:number|null}){
 const valid=rows.filter(r=>r.mapped!=null||r.applied!=null);
 if(!valid.length)return null;
 const W=640,H=320,ML=50,MR=20,MT=20,MB=50,plotW=W-ML-MR,plotH=H-MT-MB;
 const groupW=plotW/valid.length,barW=Math.min(36,groupW/3);
 const y=(percent:number)=>MT+plotH*(1-percent/100);
 return <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="프로필별 매핑 후·효과 적용 후 정확도 비교 막대그래프" style={{width:'100%',maxWidth:640,height:'auto'}}>
  {[0,25,50,75,100].map(t=><g key={t}><line x1={ML} x2={W-MR} y1={y(t)} y2={y(t)} stroke="#e2e2e2"/><text x={ML-8} y={y(t)+4} fontSize={11} textAnchor="end">{t}%</text></g>)}
  {baseline!=null&&<g><line x1={ML} x2={W-MR} y1={y(baseline*100)} y2={y(baseline*100)} stroke="#999" strokeDasharray="4 3"/><text x={W-MR} y={y(baseline*100)-4} fontSize={11} textAnchor="end">디지털 기준 {pct(baseline)}</text></g>}
  {valid.map((r,i)=>{const cx=ML+groupW*i+groupW/2;return <g key={r.name}>
   {r.mapped!=null&&<g><rect x={cx-barW-2} y={y(r.mapped*100)} width={barW} height={plotH*r.mapped} fill="#8aa6c2"/><text x={cx-barW/2-2} y={y(r.mapped*100)-4} fontSize={10} textAnchor="middle">{pct(r.mapped)}</text></g>}
   {r.applied!=null&&<g><rect x={cx+2} y={y(r.applied*100)} width={barW} height={plotH*r.applied} fill="#2f5d8a"/><text x={cx+barW/2+2} y={y(r.applied*100)-4} fontSize={10} textAnchor="middle">{pct(r.applied)}</text></g>}
   <text x={cx} y={H-MB+18} fontSize={12} textAnchor="middle">{r.name}</text>
  </g>;})}
  <g transform={`translate(${ML},${H-14})`}><rect width={10} height={10} fill="#8aa6c2"/><text x={14} y={9} fontSize={11}>매핑 후</text><rect x={76} width={10} height={10} fill="#2f5d8a"/><text x={90} y={9} fontSize={11}>효과 적용 후</text></g>
 </svg>;
}

function LegacyComparisonResults({record,experiment}:{record:Comparison;experiment:ReturnType<typeof useResource<Experiment>>}){
 const baseline=(experiment.data?.runs||[]).filter(r=>r.kind==='D0'||r.kind==='D1');
 const rows=record.cards.flatMap(c=>(c.runs||[]).map(r=>rowOf(r,c)));
 return <>
  <p className="muted">Retention 비이상성을 포함한 이전 방식 결과이며, 과거 기록 그대로 상세 표와 그래프를 보존해 보여줍니다.</p>
  <DataTable caption="공통 D0 / D1 기준" rows={baseline.map(r=>rowOf(r))}/>
  {record.cards.map(c=><div key={c.card_id} className="subsection"><h3>{c.display_name} · <Status value={c.status}/></h3><p>프로파일 {c.profile_ref?`${c.profile_ref.id}:r${c.profile_ref.revision}`:'업로드 필요'} · 후보 {c.candidate_ids?.join(', ')||'—'}{c.reason&&` · ${c.reason}`}</p></div>)}
  <DataTable caption="카드별 M0 / 효과 실행 · 누락값은 —" rows={rows}/>
  <JsonDetails title="저장된 카드별 원본 결과 · 실패와 건너뜀 포함" value={record.cards.map(c=>({name:c.display_name,status:c.status,reason:c.reason,runs:c.runs}))}/>
  {experiment.data&&<PlotArtifacts items={experiment.data.artifacts}/>}
 </>;
}

export function ComparisonResults({record}:{record:Comparison}){
 const experiment=useResource<Experiment>(record.experiment_id?`/experiments/${record.experiment_id}`:null);
 const previousLifecycle=useRef(record.lifecycle);
 useEffect(()=>{if(experimentNeedsReload(previousLifecycle.current,record.lifecycle))experiment.reload();previousLifecycle.current=record.lifecycle;},[record.lifecycle,record.experiment_id]);
 const legacy=isLegacyRetentionRecord(record);
 const d0=(experiment.data?.runs||[]).find(r=>r.kind==='D0');
 const d1=(experiment.data?.runs||[]).find(r=>r.kind==='D1');
 const rows=profileRows(record.cards);
 return <Panel title="비교 결과" aside={<Status value={record.outcome||record.lifecycle}/>}>
  <p>{record.name||'임시 결과'} · {record.comparison_id}</p>
  <ErrorNotice error={experiment.error} retry={experiment.reload}/>
  {record.job_id&&record.lifecycle==='running'&&<JobProgress id={record.job_id} onDone={experiment.reload}/>}
  {legacy?<LegacyComparisonResults record={record} experiment={experiment}/>:<>
   <p>{commonSummaryLine(record.common_settings||{})}</p>
   {d0&&<p>디지털(FP32) 기준 정확도 {pct(d0.accuracy)}{d1&&` · 입력 8bit 양자화만 적용 시 ${pct(d1.accuracy)}`}</p>}
   <AccuracyChart rows={rows} baseline={typeof d0?.accuracy==='number'?d0.accuracy:null}/>
   <DataTable caption="프로필별 정확도 비교" rows={rows.map(r=>({프로필:r.note?`${r.name} — ${r.note}`:r.name,'매핑 후 정확도':r.mapped!=null?pct(r.mapped):'—','효과 적용 후 정확도':r.applied!=null?pct(r.applied)+(r.n>1?` (반복 ${r.n}회 평균)`:''):'—','정확도 변화(%p)':r.delta!=null?pp(r.delta*100):'—'}))}/>
   <p className="muted">정확도 변화 = 효과 적용 후 − 매핑 후 (%p). 양수면 상승, 음수면 하락이며 값을 임의로 보정하지 않습니다.</p>
  </>}
  {experiment.data&&<><Notices items={experiment.data.warnings}/><Downloads items={experiment.data.artifacts}/><JsonDetails title="실행 추적 정보 (고급) · checkpoint·설정·상세 집계" value={{checkpoint_id:experiment.data.checkpoint_id,summary:experiment.data.summary,settings:record.common_settings,snapshot:record.snapshot}}/></>}
 </Panel>;
}

export function HistoricalExperiment({id}:{id:string}){const result=useResource<Experiment>(`/experiments/${id}`);return <><Heading eyebrow="HISTORICAL RESULT" title="이전 실험 결과">당시 저장된 설정과 PPA를 그대로 표시합니다.</Heading><Panel title="실험 결과"><ErrorNotice error={result.error} retry={result.reload}/>{result.loading&&<p>결과 불러오는 중…</p>}{result.data&&<><p>실험 {id} · <Status value={result.data.status}/></p><DataTable rows={(result.data.runs||[]).map(r=>rowOf(r))}/><JsonDetails title="당시 요청 · 설정 · 상세 집계" value={{request:result.data.request,summary:result.data.summary,hardware:result.data.hardware,engines:result.data.engines}}/><PpaPanel ppa={result.data.ppa}/><PlotArtifacts items={result.data.artifacts}/><Downloads items={result.data.artifacts}/></>}</Panel></>;}

export function ComparisonPage(){
 const idFromUrl=new URLSearchParams(location.search).get('comparison');
 const[id,setId]=useState<string|null>(idFromUrl),[record,setRecord]=useState<Comparison|null>(null),[form,setForm]=useState<CommonForm>(defaultCommon),[cards,setCards]=useState<Card[]>([]),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[notice,setNotice]=useState(''),[name,setName]=useState(''),[uploads,setUploads]=useState<Record<string,CardUpload>>({});
 const recordRef=useRef<Comparison|null>(null),editRef=useRef({form:defaultCommon,cards:[] as Card[],token:0,dirty:false}),saverRef=useRef<{flush:()=>Promise<void>}|null>(null),cloneOp=useRef<string|null>(null);
 const temporary=useResource<{items:Comparison[]}>('/comparisons?scope=temporary');
 const setCurrent=(r:Comparison,hydrate=true)=>{recordRef.current=r;setRecord(r);setId(r.comparison_id);history.replaceState(null,'',`/simulator?comparison=${r.comparison_id}`);if(hydrate){const nextForm=restoreCommon(r.common_settings),nextCards=r.cards.map(editableCard);editRef.current={form:nextForm,cards:nextCards,token:editRef.current.token+1,dirty:false};setForm(nextForm);setCards(nextCards);setDirty(false);}setName(r.name||'');};
 const reload=async()=>{if(!id)return;try{const r=await api.get<Comparison>(`/comparisons/${id}`);setCurrent(r);setError(null);}catch(e){setError(e);}};
 useEffect(()=>{if(id)void reload();},[id]);
 useEffect(()=>{if(!id||record?.lifecycle!=='running')return;const t=setInterval(()=>void reload(),2000);return()=>clearInterval(t);},[id,record?.lifecycle]);
 // A card already carrying a profile_ref (reload/clone/reopen) has no local File objects to show,
 // so its upload summary is fetched once from the published profile instead of re-uploading.
 useEffect(()=>{cards.forEach(card=>{if(!card.profile_ref||uploads[card.card_id]?.info||uploads[card.card_id]?.busy)return;api.get<Profile>(`/profiles/${card.profile_ref.id}/revisions/${card.profile_ref.revision}`).then(p=>{setUploads(x=>({...x,[card.card_id]:{...(x[card.card_id]||emptyUpload()),info:profileInfo(p)}}));}).catch(()=>{});});},[cards]);
 const changed=(nextCards:Card[],nextForm=form)=>{editRef.current={form:nextForm,cards:nextCards,token:editRef.current.token+1,dirty:true};setCards(nextCards);setForm(nextForm);setDirty(true);};
 const patchForm=(patch:Partial<CommonForm>)=>changed(cards,{...form,...patch});
 const patchCard=(cardId:string,patch:Partial<Card>)=>changed(cards.map(c=>c.card_id===cardId?{...c,...patch}:c));
 const persist=async():Promise<Comparison|null>=>{if(!saverRef.current)saverRef.current=createDraftSaver(()=>{const current=recordRef.current,edit=editRef.current;if(!current||current.lifecycle!=='drafting'||!edit.dirty)return null;return {token:edit.token,value:{id:current.comparison_id,version:current.version,settings:commonSettings(edit.form),cards:edit.cards.map(editableCard)}};},payload=>api.updateComparison(payload.id,payload.version,payload.settings,payload.cards),(saved,token)=>{if(recordRef.current?.comparison_id!==saved.comparison_id)return;recordRef.current=saved;setRecord(saved);if(editRef.current.token===token){editRef.current.dirty=false;setDirty(false);}});try{await saverRef.current.flush();setError(null);return recordRef.current;}catch(e){setError(e);if((e as {status?:number}).status===409){setNotice('다른 탭에서 초안이 바뀌었습니다. 서버 내용을 다시 불러오고 선택을 확인하세요.');await reload();}return null;}};
 useEffect(()=>{if(!dirty||record?.lifecycle!=='drafting')return;const t=setTimeout(()=>void persist(),650);return()=>clearTimeout(t);},[dirty,cards,form,record?.version,record?.lifecycle]);
 const create=async()=>{setBusy(true);setError(null);try{const draft=await api.createComparison();setCurrent(await api.updateComparison(draft.comparison_id,draft.version,commonSettings(defaultCommon),[]));setNotice('서버에 새 임시 초안을 만들었습니다.');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const run=async()=>{setBusy(true);setError(null);try{const saved=await persist();if(!saved)return;const r=await api.runComparison(saved.comparison_id,saved.version);setCurrent(r);setNotice(r.job_id?'실행을 시작했습니다.':'실행할 발행 프로파일이 없어 카드가 차단됐습니다.');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const save=async()=>{if(!record||!name.trim())return;setBusy(true);setError(null);try{setCurrent(await api.saveComparison(record.comparison_id,name.trim()));setNotice('현재 결과에 이름을 붙여 저장했습니다. 다시 실행하지 않았습니다.');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const clone=async()=>{if(!record)return;cloneOp.current??=crypto.randomUUID();setBusy(true);setError(null);try{setCurrent(await api.cloneComparison(record.comparison_id,cloneOp.current));cloneOp.current=null;setNotice('새 임시 초안으로 복제했습니다. 파일이나 수치를 바꿀 카드만 다시 업로드하세요.');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const discard=async()=>{if(!record)return;setBusy(true);setError(null);try{const r=await api.discardComparison(record.comparison_id);setRecord(r);recordRef.current=r;setNotice('임시 비교를 폐기했습니다.');temporary.reload();}catch(e){setError(e);}finally{setBusy(false);}};
 const patchUpload=(cardId:string,patch:Partial<CardUpload>)=>setUploads(x=>({...x,[cardId]:{...(x[cardId]||emptyUpload()),...patch}}));
 const uploadCard=async(card:Card)=>{
  const u=uploads[card.card_id]||emptyUpload();
  if(!u.ltp||!u.ltd){patchUpload(card.card_id,{error:'LTP와 LTD 파일을 모두 선택하세요.'});return;}
  if(!card.display_name.trim()){patchUpload(card.card_id,{error:'프로필 이름을 입력하세요.'});return;}
  patchUpload(card.card_id,{busy:true,error:null});
  try{
   const p=await api.createProfileQuick(u.ltp,u.ltd,card.display_name.trim());
   patchCard(card.card_id,{profile_ref:{id:p.profile_id,revision:p.revision}});
   patchUpload(card.card_id,{busy:false,error:null,info:profileInfo(p)});
   setNotice(`${card.display_name}: 업로드·분석·발행을 마쳤습니다 (조건 ${p.condition_id}, 상태 ${p.pools.combined?.state_ids.length||0}개).`);
  }catch(e){
   patchUpload(card.card_id,{busy:false,error:e instanceof ApiError?e.message:String(e)});
  }
 };
 if(!record||record.lifecycle==='discarded')return <><Heading eyebrow="CIM SIMULATION" title="비교 시뮬레이션">LTP/LTD 파일을 올리면 프로필을 자동으로 만들고, 공통 조건으로 비교합니다.</Heading><Panel title="임시 작업 시작 또는 이어서 열기"><ErrorNotice error={error}/><button className="primary" disabled={busy} onClick={()=>void create()}>새 비교 만들기</button>{temporary.data?.items.map(r=><p key={r.comparison_id}><a href={`/simulator?comparison=${r.comparison_id}`}>{r.name||`임시 비교 ${r.comparison_id.slice(0,8)}`}</a> · <Status value={r.lifecycle}/></p>)}</Panel></>;
 return <><Heading eyebrow="CIM SIMULATION" title="프로파일 비교">프로필 이름과 LTP/LTD 파일을 올리면 자동으로 인식·분석·발행한 뒤, 공통 64×64 조건에서 비교합니다.</Heading><p role="status" aria-live="polite">{notice|| (dirty?'변경 사항 자동 저장 대기 중':'서버 초안 저장됨')} · 버전 {record.version}</p><ErrorNotice error={error}/>{record.lifecycle==='drafting'&&<div className="workspace-grid"><div><Panel title="01 · 프로필 카드" aside={<button disabled={cards.length>=5||busy} onClick={()=>changed([...cards,{card_id:crypto.randomUUID(),display_name:`프로필 ${cards.length+1}`,c2c_approved_assumption:false,cross_condition_acknowledged:false}])}>프로필 추가</button>}><p>카드마다 LTP/LTD 파일 한 쌍을 올리면 서버가 자동으로 인식·분석하고 유효한 상태를 모두 채택해 발행까지 마칩니다. 다른 파일로 다시 올리면 그 카드만 새 프로필로 교체됩니다.</p>{cards.map((card,index)=>{const u=uploads[card.card_id]||emptyUpload();return <fieldset key={card.card_id} className="dataset"><legend>{index+1}. {card.display_name||'(이름 없음)'}</legend><div className="actions"><button disabled={index===0} onClick={()=>{const next=[...cards];[next[index-1],next[index]]=[next[index],next[index-1]];changed(next);}}>위로</button><button disabled={index===cards.length-1} onClick={()=>{const next=[...cards];[next[index+1],next[index]]=[next[index],next[index+1]];changed(next);}}>아래로</button><button onClick={()=>changed(cards.filter(c=>c.card_id!==card.card_id))}>카드 삭제</button></div><Field label="프로필 이름"><input value={card.display_name} onChange={e=>patchCard(card.card_id,{display_name:e.target.value})}/></Field>{card.profile_ref?<p className="notice">업로드 완료 · 조건 {u.info?.condition_id||card.condition_id||'—'} · 상태 {u.info?.n_states??'—'}개{u.info?.g_min_s!=null&&u.info?.g_max_s!=null&&` · 전도도 범위 ${show(u.info.g_min_s)} ~ ${show(u.info.g_max_s)} S`}</p>:<p className="muted">아직 업로드되지 않았습니다. LTP/LTD 파일을 함께 선택하세요.</p>}<Field label="LTP 파일"><input type="file" accept=".csv,.xlsx" onChange={e=>patchUpload(card.card_id,{ltp:e.target.files?.[0]||null,error:null})}/></Field><Field label="LTD 파일"><input type="file" accept=".csv,.xlsx" onChange={e=>patchUpload(card.card_id,{ltd:e.target.files?.[0]||null,error:null})}/></Field><button disabled={u.busy||busy} onClick={()=>void uploadCard(card)}>{card.profile_ref?'파일 다시 업로드':'업로드·분석'}</button>{u.busy&&<p className="muted">업로드·인식·분석 중입니다…</p>}<ErrorNotice error={u.error?new Error(u.error):null}/><Field label="C2C 상대 편차 CV(%)" hint="전류/전도도 기준 상대 표준편차를 퍼센트로 입력합니다(예: 5는 5%). 0 허용. 공통 설정에서 C2C가 꺼져 있으면 사용되지 않습니다."><input type="number" min="0" step="any" value={card.manual_c2c_cv_percent??''} onChange={e=>patchCard(card.card_id,{manual_c2c_cv_percent:e.target.value===''?null:Number(e.target.value)})}/></Field><Field label="D2D 상대 편차 CV(%)" hint="소자 간 전류/전도도 기준 상대 표준편차를 퍼센트로 입력합니다(예: 5는 5%). 0 허용. 공통 설정에서 D2D가 꺼져 있으면 사용되지 않습니다."><input type="number" min="0" step="any" value={card.manual_d2d_cv_percent??''} onChange={e=>patchCard(card.card_id,{manual_d2d_cv_percent:e.target.value===''?null:Number(e.target.value)})}/></Field><p><Status value={card.profile_ref?'published':'blocked'}/> {card.profile_ref?`${card.profile_ref.id}:r${card.profile_ref.revision}`:'LTP/LTD 업로드 필요'}</p>{u.info&&<JsonDetails title="프로필 상세 (고급)" value={u.info}/>}</fieldset>;})}</Panel><Panel title="02 · 공통 실행 조건"><p>배열 64 × 64 · 입력 unsigned 8 bit · 정확도 엔진 aihwkit_ideal 고정 · ADC 켤 때 각 경로를 변환한 뒤 차감 (adc_then_subtract). checkpoint와 seed는 서버가 내부적으로 고정·기록하며, 같은 비교 안의 모든 프로필과 ADC 조건에 동일하게 적용됩니다.</p><label className="check"><input type="checkbox" checked={form.adc} onChange={e=>patchForm({adc:e.target.checked})}/>ADC 양자화</label>{form.adc&&<Field label="ADC bit (3~8, 기본 5)"><select value={form.adcBits} onChange={e=>patchForm({adcBits:Number(e.target.value)})}>{[3,4,5,6,7,8].map(n=><option key={n} value={n}>{n} bit</option>)}</select></Field>}<label className="check"><input type="checkbox" checked={form.d2d} onChange={e=>patchForm({d2d:e.target.checked})}/>D2D 소자 간 편차</label>{form.d2d&&<Field label="배열 반복 횟수" hint="서로 다른 D2D 무작위 실현(배열)을 몇 개 독립적으로 시뮬레이션할지입니다."><input type="number" min="1" max="100" value={form.arrays} onChange={e=>patchForm({arrays:Number(e.target.value)})}/></Field>}<label className="check"><input type="checkbox" checked={form.c2c} onChange={e=>patchForm({c2c:e.target.checked})}/>C2C 재기록 편차</label>{form.c2c&&<Field label="재기록 반복 횟수" hint="같은 배열을 몇 번 다시 프로그램(재기록)해 C2C 편차를 다시 뽑을지입니다."><input type="number" min="1" max="100" value={form.nReprogram} onChange={e=>patchForm({nReprogram:Number(e.target.value)})}/></Field>}<p className="muted">Retention 비이상성 선택·적용은 이 비교 실행에서 제외됩니다(연수는 항상 0). 측정 Retention 분석과 외삽 조회는 측정 분석/프로필 화면에서 그대로 제공됩니다.</p><p className="muted">PPA는 이 비교에서 평가하지 않습니다.</p></Panel></div><aside><Panel title="임시 비교 제어"><p>카드 {cards.length} / 5 · 서버 버전 {record.version}</p><button className="primary full" disabled={busy||dirty||!cards.length} onClick={()=>void run()}>저장된 초안 실행</button><button className="full" disabled={busy||!dirty} onClick={()=>void persist()}>지금 저장</button><button className="subtle full" disabled={busy} onClick={()=>void discard()}>임시 비교 폐기</button><JsonDetails title="서버 저장 내용" value={{common_settings:record.common_settings,cards:record.cards}}/></Panel></aside></div>}{record.lifecycle!=='drafting'&&<><ComparisonResults record={record}/><Panel title="결과 보관 / 새 비교"><Field label="결과 이름"><input value={name} disabled={record.lifecycle==='saved'} onChange={e=>setName(e.target.value)}/></Field>{record.lifecycle==='temporary'&&<button className="primary" disabled={busy||!name.trim()} onClick={()=>void save()}>현재 결과 이름 붙여 저장</button>}<button disabled={busy} onClick={()=>void clone()}>설정 복제해 새 비교</button>{record.lifecycle==='temporary'&&<button className="subtle" disabled={busy} onClick={()=>void discard()}>임시 비교 폐기</button>}{record.lifecycle==='saved'&&<a href="/saved-results">저장한 결과 목록</a>}</Panel></>}</>;
}
