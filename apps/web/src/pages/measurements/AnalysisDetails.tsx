import {useState} from 'react';
import type {Analysis, Row} from '../../lib/api';
import {DataTable} from '../../shared';
import {compactValue, pageRows, PAGE_SIZE} from './resultView';
import {C2cSummary} from './LayoutPickers';
import {C2cSweepSummary, D2dSummary, RetentionSummary} from './KindSummaries';

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

const tableNames: Record<string, string> = {raw: '원본 측정 행', states: '추출 상태', vth: 'Vth', memory_window: 'Memory window', by_amplitude: '진폭별 요약',
  d2d_conditions: '조건별 D2D', retention_fit: '실측·적합값', retention_extrapolation: '외삽 표본', cycles: '사이클별 값', c2c_points: '구간별 C2C'};

function GenericSummary({analysis}: {analysis: Analysis}) {
  const summary = analysis.summaries || {};
  const pools = summary.pools as Record<string, {available?: boolean; reason?: string; state_ids?: string[]; g_min_s?: number; g_max_s?: number}> | undefined;
  return <>
    <DataTable rows={Object.entries(summary).filter(([key]) => key !== 'pools').map(([key, value]) => ({항목: ({candidate_count:'추출 후보 수',positive_candidate_count:'양의 전도도 후보 수',valid_vth_count:'유효 Vth 수',valid_mw_count:'유효 MW 수'} as Record<string,string>)[key] || key, 값: compactValue(value)}))}/>
    {pools && <DataTable caption="전도도 풀 · 상태 수는 후보 개수이며 고유 전도도 수준 수와 다릅니다" rows={Object.entries(pools).map(([name, p]) => ({풀: name, 사용가능: p.available ? '가능' : '불가', 상태수: p.state_ids?.length ?? 0, 'Gmin (S)': p.g_min_s, 'Gmax (S)': p.g_max_s, 사유: p.reason}))}/>}
  </>;
}

export function AnalysisDetails({analysis}: {analysis: Analysis}) {
  const exclusions = analysis.exclusions || [];
  const counts = new Map<string, number>();
  for (const item of exclusions) {
    const reason = item && typeof item === 'object' && 'reason' in item ? String(item.reason) : '기타';
    counts.set(reason, (counts.get(reason) || 0) + 1);
  }
  const kind = analysis.kind;
  return <>
    {kind === 'c2c_sweep' ? <C2cSweepSummary analysis={analysis}/> : kind === 'c2c_detrended' ? <C2cSummary analysis={analysis}/>
      : kind === 'd2d' ? <D2dSummary analysis={analysis}/> : kind === 'retention' ? <RetentionSummary analysis={analysis}/> : <GenericSummary analysis={analysis}/>}
    {exclusions.length > 0 && <DataTable caption={`제외 기록 ${exclusions.length}건 · 한 기록이 여러 행이나 구간을 뜻할 수 있음`} rows={Array.from(counts, ([reason, count]) => ({사유: reason, 기록수: count}))}/>}
    <details><summary>상세 표 · 원본 행 · 적용 설정 (고급)</summary>
      {Object.entries(analysis.tables || {}).map(([name, rows]) => <PagedTable key={name} title={tableNames[name] || name} rows={rows}/>)}
      {exclusions.length > 0 && <PagedTable title="제외 사유 상세" rows={exclusions.map(item => item && typeof item === 'object' ? item as Row : {내용: item})}/>}
      <PagedTable title="적용된 설정과 출처" rows={[{설정: analysis.settings, 출처: analysis.provenance}]}/>
    </details>
  </>;
}
