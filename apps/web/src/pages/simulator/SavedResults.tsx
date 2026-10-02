import {useState} from 'react';
import {api} from '../../lib/api';
import {c2cBasisLabels,type C2cBasis,type Comparison} from '../../lib/workflows';
import {ErrorNotice,Heading,Panel,Status,useResource} from '../../shared';
import {ComparisonResults} from './Comparison';

const when=(r:Comparison)=>r.updated_at.slice(0,16).replace('T',' ');
const summary=(r:Comparison)=>{const e=(r.common_settings?.effects||{}) as Record<string,boolean>;return [`${r.cards.length}개 프로필`,e.adc?`ADC ${(r.common_settings?.hardware as {adc_bits?:number})?.adc_bits} bit`:'ADC OFF',e.d2d?'D2D ON':'',e.c2c?`C2C ON${r.c2c_basis?` (${c2cBasisLabels[r.c2c_basis as C2cBasis]})`:''}`:''].filter(Boolean).join(' · ');};

export function SavedResults(){
 const saved=useResource<{items:Comparison[]}>('/comparisons?scope=saved'),temporary=useResource<{items:Comparison[]}>('/comparisons?scope=temporary');
 const[id,setId]=useState<string|null>(new URLSearchParams(location.search).get('comparison')),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[cloneOp,setCloneOp]=useState<string|null>(null);
 const selected=useResource<Comparison>(id?`/comparisons/${id}`:null);
 const clone=async()=>{if(!id)return;setBusy(true);setError(null);const operation=cloneOp||crypto.randomUUID();setCloneOp(operation);try{const r=await api.cloneComparison(id,operation);location.href=`/simulator?comparison=${r.comparison_id}`;}catch(e){setError(e);}finally{setBusy(false);}};
 const discard=async(target:string)=>{setBusy(true);setError(null);try{await api.discardComparison(target);temporary.reload();if(id===target)setId(null);}catch(e){setError(e);}finally{setBusy(false);}};
 const open=(r:Comparison)=>{setId(r.comparison_id);history.replaceState(null,'',`/saved-results?comparison=${r.comparison_id}`);};
 return <><Heading title="저장한 결과">이름 붙여 저장한 시뮬레이션을 다시 열거나 복제합니다. 임시 작업은 저장 전까지 따로 보관됩니다.</Heading><ErrorNotice error={error}/>
  <div className="two-columns">
   <Panel title="저장한 시뮬레이션" aside={<button onClick={saved.reload}>새로고침</button>}><ErrorNotice error={saved.error} retry={saved.reload}/>
    {!saved.data?<p className="empty">{saved.error?'불러오지 못했습니다.':'불러오는 중…'}</p>:!saved.data.items.length?<p className="empty">저장한 결과가 없습니다.</p>:<ul className="activity-list">{saved.data.items.map(r=><li key={r.comparison_id} className={r.comparison_id===id?'current':''}><button type="button" className="link" onClick={()=>open(r)}><strong>{r.name}</strong><small>{summary(r)} · {when(r)}</small></button><Status value={r.outcome||r.lifecycle}/></li>)}</ul>}
   </Panel>
   <Panel title="임시 작업" aside={<button onClick={temporary.reload}>새로고침</button>}><ErrorNotice error={temporary.error} retry={temporary.reload}/>
    {!temporary.data?<p className="empty">{temporary.error?'불러오지 못했습니다.':'불러오는 중…'}</p>:!temporary.data.items.length?<p className="empty">임시 작업이 없습니다.</p>:<ul className="activity-list">{temporary.data.items.map(r=><li key={r.comparison_id}><a href={`/simulator?comparison=${r.comparison_id}`}><strong>{r.cards.map(c=>c.display_name).join(', ')||'빈 시뮬레이션'}</strong><small>{summary(r)} · {when(r)}</small></a><span><Status value={r.lifecycle}/> <button disabled={busy} onClick={()=>void discard(r.comparison_id)}>폐기</button></span></li>)}</ul>}
    <p className="muted">폐기는 그 임시 결과만 지웁니다. 올린 파일과 저장한 결과는 남습니다.</p>
   </Panel>
  </div>
  {selected.data&&<><ComparisonResults record={selected.data}/><Panel title="이 결과로 다시 실행"><button disabled={busy} onClick={()=>void clone()}>설정 복제해 새 시뮬레이션</button><p className="muted">같은 파일·설정을 가진 새 임시 작업이 만들어집니다. 저장된 이 결과는 바뀌지 않습니다.</p></Panel></>}
 </>;
}
