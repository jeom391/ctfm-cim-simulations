import {analysisId,analysisKind,analysisCondition,type Analysis,type Capabilities} from '../../lib/api';
import type {Comparison} from '../../lib/workflows';
import {Heading,Panel,Status,useResource} from '../../shared';
import {kindLabels} from '../measurements/Recognition';

export function Home(){
 const caps=useResource<Capabilities>('/capabilities');
 const analyses=useResource<{items:Analysis[]}>('/analyses');
 const saved=useResource<{items:Comparison[]}>('/comparisons?scope=saved');
 const aihwkit=caps.data?.engines?.aihwkit_ideal;
 return <><Heading title="측정 분석과 CIM 시뮬레이션">측정 파일에서 소자 특성을 정리하고, LTP/LTD 파일로 만든 프로필의 MNIST 추론 정확도를 비교합니다.</Heading>
  <div className="entry-links">
   <a href="/measurements"><h2>측정 분석</h2><p>LTP/LTD, Vth/MW, D2D, C2C, Retention 파일을 올려 결과 표와 그래프를 받습니다.</p></a>
   <a href="/simulator"><h2>시뮬레이션</h2><p>소자별 LTP/LTD 파일과 C2C·D2D 편차로 64×64 배열 정확도를 비교합니다.</p></a>
  </div>
  {caps.data&&<p className={'notice'+(aihwkit?.available?'':' error')}>{aihwkit?.available?`정확도 엔진 AIHWKit ${aihwkit.version||''} 사용 가능`:`정확도 엔진 AIHWKit 사용 불가 · ${aihwkit?.reason||'엔진 환경을 확인하세요'} · 시뮬레이션 실행이 차단됩니다.`}</p>}
  <div className="two-columns">
   <Panel title="최근 분석" aside={<a href="/measurements">전체 보기</a>}>{!analyses.data?<p className="empty">{analyses.error?'분석 목록을 불러오지 못했습니다.':'불러오는 중…'}</p>:!analyses.data.items.length?<p className="empty">아직 분석이 없습니다.</p>:<ul className="activity-list">{analyses.data.items.slice(0,6).map(a=><li key={analysisId(a)}><a href={'/measurements?analysis='+analysisId(a)}><strong>{kindLabels[analysisKind(a)]||analysisKind(a)} · {analysisCondition(a)}</strong><small>{String(a.finished_at||a.created_at||'').slice(0,16).replace('T',' ')}</small></a><Status value={a.status}/></li>)}</ul>}</Panel>
   <Panel title="저장한 결과" aside={<a href="/saved-results">전체 보기</a>}>{!saved.data?<p className="empty">{saved.error?'저장한 결과를 불러오지 못했습니다.':'불러오는 중…'}</p>:!saved.data.items.length?<p className="empty">저장한 시뮬레이션이 없습니다.</p>:<ul className="activity-list">{saved.data.items.slice(0,6).map(r=><li key={r.comparison_id}><a href={`/saved-results?comparison=${r.comparison_id}`}><strong>{r.name}</strong><small>{r.cards.length}개 프로필 · {r.updated_at.slice(0,16).replace('T',' ')}</small></a><Status value={r.outcome||r.lifecycle}/></li>)}</ul>}</Panel>
  </div>
 </>;
}
