import {useState} from 'react';
import type {Analysis, Row} from '../../lib/api';
import {DataTable} from '../../shared';

const num = (v: unknown, digits = 4) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—';
const sci = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? v.toExponential(3) : '—';
const YEAR = 365.25 * 86400;
const years = (s: unknown) => typeof s !== 'number' ? '—' : s >= YEAR ? `${(s / YEAR).toPrecision(3)}년 (${s.toExponential(2)} s)`
  : s >= 86400 ? `${(s / 86400).toPrecision(3)}일 (${s.toExponential(2)} s)` : `${s.toPrecision(4)} s`;

export function CopyValue({value, label}: {value: number | null | undefined; label: string}) {
  const [done, setDone] = useState(false);
  if (value == null) return <span className="muted">계산 불가</span>;
  const text = value.toFixed(4);
  return <span className="copy-value"><strong>{text}%</strong><button type="button" className="subtle" aria-label={`${label} ${text}% 복사`}
    onClick={() => void navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); })}>{done ? '복사됨' : '복사'}</button></span>;
}

interface SweepPoint {point: string; label: string; status: string; n: number; cell_range?: string | null; reason?: string | null;
  mean_a?: number; sd_a?: number; cv_overall_percent?: number | null; cv_residual_percent?: number | null; residual_reason?: string | null;
  trend_slope_a_per_cycle?: number; residual_lag1_correlation?: number | null}

export function C2cSweepSummary({analysis}: {analysis: Analysis}) {
  const points = ((analysis.summaries as {points?: SweepPoint[]})?.points) || [];
  const method = analysis.method as {overall: string; residual: string} | undefined;
  return <>
    <p>같은 {points[0]?.n ?? '—'}-cycle 데이터에서 구간별로 두 값을 계산했습니다. 어느 쪽도 자동 선택하지 않습니다. 시뮬레이터에 쓸 값을 복사해 프로필의 C2C CV(%) 칸에 넣고, 저장할 때 어떤 값을 썼는지 고르세요.</p>
    <div className="table-scroll"><table>
      <caption>C2C · Vg = 0 V 전류 · 상승/하강 구간 별도 분석</caption>
      <thead><tr><th scope="col">구간</th><th scope="col">원본 셀</th><th scope="col">N</th><th scope="col">평균 (µA)</th><th scope="col">표본 SD (µA)</th><th scope="col">전체 변동 CV</th><th scope="col">추세 제거 후 상대 잔차 SD</th><th scope="col">비고</th></tr></thead>
      <tbody>{points.map(p => <tr key={p.point}>
        <th scope="row">{p.label}</th><td>{p.cell_range || '—'}</td><td>{p.n}</td>
        <td>{p.mean_a == null ? '—' : num(p.mean_a * 1e6, 6)}</td><td>{p.sd_a == null ? '—' : num(p.sd_a * 1e6, 6)}</td>
        <td>{p.status === 'ok' ? <CopyValue value={p.cv_overall_percent} label={`${p.label} 전체 변동`}/> : '—'}</td>
        <td>{p.status === 'ok' ? <CopyValue value={p.cv_residual_percent} label={`${p.label} 추세 제거 후`}/> : '—'}</td>
        <td>{p.status !== 'ok' ? p.reason : p.residual_reason || (p.residual_lag1_correlation != null ? `잔차 lag-1 상관 ${num(p.residual_lag1_correlation, 3)}` : '')}</td>
      </tr>)}</tbody>
    </table></div>
    {method && <p className="muted">전체 변동: {method.overall}. 추세 제거: {method.residual}. 최초 0 V는 상승·하강 중 0 V와 섞지 않습니다. 초기 사이클이나 튀는 값을 제외하지 않았습니다.</p>}
  </>;
}

interface D2dCondition {sweep_amplitude_v: number; branch: string; cv: number | null; included: boolean; reason: string | null; mean_g_s: number | null;
  device_values: ({device_id: string; id_a: number | null; conductance_s: number | null} | null)[]}

export function D2dSummary({analysis}: {analysis: Analysis}) {
  const summary = analysis.summaries as {cv?: number | null; matched_conditions?: number; status?: string};
  const rows = (analysis.tables?.d2d_conditions || []) as unknown as D2dCondition[];
  const files = ((analysis.provenance || []) as {device_id: string; filename: string}[]).reduce<Record<string, string>>((m, p) => ({...m, [p.device_id]: p.filename}), {});
  const devices = rows[0]?.device_values.map(d => d?.device_id || '') || [];
  const recognitionExcluded = ((analysis.recognition as {sources?: {name: string; issues: {code: string; detail: string}[]}[]} | undefined)?.sources || [])
    .flatMap(s => s.issues.filter(i => i.code === 'd2d_condition_excluded').map(i => ({파일: s.name, 사유: i.detail})));
  return <>
    <div className="metric-row">
      <div><span>대표 D2D CV (RMS)</span><CopyValue value={summary.cv == null ? null : 100 * summary.cv} label="대표 D2D CV"/></div>
      <div><span>유효 비교 조건 K</span><strong>{summary.matched_conditions ?? 0}</strong></div>
      <div><span>비교 소자</span><strong>{devices.map(d => files[d] || d).join(' ↔ ') || '—'}</strong></div>
    </div>
    <p className="muted">조건마다 G = Id(Vg=0 V) / 0.1 V, 두 소자의 표본 SD(N−1)를 평균으로 나눈 CV를 구하고, 유효 조건의 RMS √(ΣCV²/K)를 대표값으로 씁니다. 선택한 물리 소자 2개 기준이며 소자 집단 분포를 확정한 값이 아닙니다.</p>
    <DataTable caption="조건별 두 소자 비교" rows={rows.map(r => ({'진폭 (V)': r.sweep_amplitude_v, 분기: r.branch,
      ...Object.fromEntries(r.device_values.flatMap((d, i) => [[`소자${i + 1} G (S)`, sci(d?.conductance_s)]])),
      '평균 G (S)': sci(r.mean_g_s), 'CV (%)': r.cv == null ? '—' : num(100 * r.cv), 포함: r.included ? '예' : '아니오', 사유: r.reason || ''}) as Row)}/>
    {recognitionExcluded.length > 0 && <DataTable caption="짝짓기 단계에서 제외한 조건" rows={recognitionExcluded}/>}
  </>;
}

interface Extrapolation {model: string; measured_end_s: number; horizon_s: number; note: string; window_closing_s: number | null; window_closing_note: string;
  program: {ten_year_a: number; ten_year_valid: boolean; zero_crossing_s: number | null}; erase: {ten_year_a: number; ten_year_valid: boolean; zero_crossing_s: number | null}}
interface Fit {a: number; b: number; r_squared: number | null; n: number; time_min_s: number; time_max_s: number}

export function RetentionSummary({analysis}: {analysis: Analysis}) {
  const s = analysis.summaries as {program_fit?: Fit; erase_fit?: Fit; extrapolation?: Extrapolation; read_vgs_v?: number; vds_v?: number; source_label?: string};
  const e = s.extrapolation;
  return <>
    <DataTable caption={`실측 구간 적합 · I(t) = a + b·log10(t/1 s) · 원본 ${s.source_label || '—'} · 읽기 VGS ${s.read_vgs_v ?? '—'} V · VDS ${s.vds_v ?? '—'} V`}
      rows={(['program', 'erase'] as const).map(d => { const f = s[`${d}_fit`]; return {방향: d, 'a (A)': sci(f?.a), 'b (A/decade)': sci(f?.b), R2: num(f?.r_squared, 4), 점수: f?.n ?? '—', '측정 기간 (s)': f ? `${f.time_min_s} – ${f.time_max_s}` : '—'}; })}/>
    {e ? <>
      <DataTable caption="외삽 (모델 결과 · 실측 아님)" rows={(['program', 'erase'] as const).map(d => ({방향: d, '10년 예측 Id (A)': sci(e[d].ten_year_a),
        '모델 유효': e[d].ten_year_valid ? '예' : '아니오 (예측 전류 ≤ 0)', '예측 전류가 0이 되는 시점': e[d].zero_crossing_s == null ? '해당 없음' : years(e[d].zero_crossing_s)}))}/>
      <p className="notice">측정 종료 {years(e.measured_end_s)} 이후는 실선이 아닌 점선 외삽입니다. Program·Erase 적합선이 만나는 시점: {e.window_closing_s == null ? '측정 이후 만나지 않음' : years(e.window_closing_s)}. 교차 시점과 10년 값은 로그-선형 모델에 의존한 외삽이며 실제 수명이나 실측 검증이 아닙니다. 0 이하 예측은 0으로 자르지 않고 모델 유효성 문제로 표시합니다. 정확도 시뮬레이터에는 Retention을 적용하지 않습니다.</p>
    </> : <p className="muted">이전 버전에서 실행한 분석이라 외삽 정보가 없습니다. 같은 파일로 다시 분석하면 표시됩니다.</p>}
  </>;
}
