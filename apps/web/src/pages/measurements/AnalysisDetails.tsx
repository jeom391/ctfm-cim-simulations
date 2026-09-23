import {useState} from 'react';
import type {Analysis, Row} from '../../lib/api';
import {DataTable} from '../../shared';
import {compactValue, pageRows, PAGE_SIZE} from './resultView';

function PagedTable({title, rows}: {title: string; rows: Row[]}) {
  const [open, setOpen] = useState(false);
  const [requested, setPage] = useState(0);
  const {page, pages, rows: visible} = pageRows(rows, requested);
  return <details onToggle={e => setOpen(e.currentTarget.open)}>
    <summary>{title} · {rows.length.toLocaleString()}행</summary>
    {open && <>
      <div className="actions" aria-label={`${title} 페이지 이동`}>
        <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>이전</button>
        <span aria-live="polite">{page + 1} / {pages}페이지 · 최대 {PAGE_SIZE}행</span>
        <button type="button" disabled={page + 1 === pages} onClick={() => setPage(page + 1)}>다음</button>
      </div>
      <DataTable rows={visible.map(row => Object.fromEntries(Object.entries(row).map(([k,v]) => [k, compactValue(v)])))}/>
    </>}
  </details>;
}

export function AnalysisDetails({analysis}: {analysis: Analysis}) {
  const summary = analysis.summaries || {};
  const pools = summary.pools as Record<string, {available?: boolean; reason?: string; state_ids?: string[]; g_min_s?: number; g_max_s?: number}> | undefined;
  const exclusions = analysis.exclusions || [];
  const counts = new Map<string, number>();
  for (const item of exclusions) {
    const reason = item && typeof item === 'object' && 'reason' in item ? String(item.reason) : '기타';
    counts.set(reason, (counts.get(reason) || 0) + 1);
  }
  return <>
    <h4>계산 요약</h4>
    <DataTable rows={Object.entries(summary).filter(([key]) => key !== 'pools').map(([key, value]) => ({항목: ({candidate_count:'추출 후보 수',positive_candidate_count:'양의 전도도 후보 수'} as Record<string,string>)[key] || key, 값: compactValue(value)}))}/>
    {pools && <DataTable caption="전도도 풀 · 상태 수는 후보 개수이며 고유 전도도 수준 수와 다릅니다" rows={Object.entries(pools).map(([name, p]) => ({풀: name, 사용가능: p.available ? '가능' : '불가', 상태수: p.state_ids?.length ?? 0, 'Gmin (S)': p.g_min_s, 'Gmax (S)': p.g_max_s, 사유: p.reason}))}/>}
    <p className="muted">상세 표는 펼칠 때만 표시하며 50행씩 조회합니다. 긴 값과 중첩 목록은 요약합니다. 원본 전체 값은 아래 다운로드 파일에서 확인하세요.</p>
    {Object.entries(analysis.tables || {}).map(([name, rows]) => <PagedTable key={name} title={name} rows={rows}/>)}
    <h4>제외 기록 · {exclusions.length}건</h4>
    <p className="muted">기록 한 건이 여러 행 또는 구간을 나타낼 수 있습니다. 제외된 측정 행 수와 같지 않습니다.</p>
    <DataTable rows={Array.from(counts, ([reason, count]) => ({사유: reason, 기록수: count}))}/>
    <PagedTable title="제외 사유 상세" rows={exclusions.map(item => item && typeof item === 'object' ? item as Row : {내용: item})}/>
    <PagedTable title="적용된 설정과 출처" rows={[{설정: analysis.settings, 출처: analysis.provenance}]}/>
  </>;
}
