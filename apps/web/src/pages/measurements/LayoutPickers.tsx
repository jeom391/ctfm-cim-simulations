import type {Analysis, Dataset} from '../../lib/api';
import {c2cConditionFields, unitOptions} from '../../lib/payload';
import {DataTable, Field, Notices} from '../../shared';

type Update = (patch: Partial<Dataset>) => void;
const RETENTION_LABELS: [string, string][] = [['erase_time_s', 'Erase 시간 열'], ['erase_id_a', 'Erase 전류 열'], ['program_time_s', 'Program 시간 열'], ['program_id_a', 'Program 전류 열']];

export function IvBlockPicker({d, update}: {d: Dataset; update: Update}) {
  const layout = d.ivLayout;
  if (!layout) return null;
  const block = layout.blocks.find(b => String(b.index) === d.block);
  const usable = block?.status === 'ok' ? block : undefined;
  return <div className="layout-picker">
    <p className="notice">이 파일은 한 시트에 Vg/Id/Ig 블록이 <strong>{layout.block_count}개</strong> 반복되어 열 이름으로 구분할 수 없습니다. 분석할 <strong>블록과 Vg 구간을 직접 선택</strong>하세요. 첫 블록을 자동으로 사용하지 않습니다.</p>
    <div className="form-grid">
      <Field label="Vg/Id/Ig 블록" hint="블록마다 스윕 진폭(최대 |Vg|)이 다릅니다.">
        <select value={d.block || ''} onChange={e => {
          const next = layout.blocks.find(b => String(b.index) === e.target.value);
          update({block: e.target.value, segment: '', branch: '', sweep_amplitude_v: next?.status === 'ok' ? next.proposed_amplitude_v ?? '' : ''});
        }}>
          <option value="">블록 선택</option>
          {layout.blocks.map(b => <option key={b.index} value={String(b.index)} disabled={b.status !== 'ok'}>
            {b.status === 'ok' ? `#${b.index} · 진폭 ${b.proposed_amplitude_v} V · ${b.points}점` : `#${b.index} · 사용 불가 (${b.error})`}
          </option>)}
        </select>
      </Field>
      <Field label="Vg 구간" hint="상승 구간은 Erase, 하강 구간은 Program 분기입니다.">
        <select disabled={!usable} value={d.segment || ''} onChange={e => {
          const seg = usable?.segments?.find(s => String(s.index) === e.target.value);
          update({segment: e.target.value, branch: seg ? (seg.direction === 'increasing' ? 'erase' : 'program') : ''});
        }}>
          <option value="">{usable ? '구간 선택' : '먼저 블록을 선택하세요'}</option>
          {usable?.segments?.map(s => <option key={s.index} value={String(s.index)}>
            {`#${s.index} · ${s.direction === 'increasing' ? '상승 (Erase)' : '하강 (Program)'} · Vg ${s.vg_start} → ${s.vg_end} V · ${s.points}점 · 원본 행 ${s.source_row_start}–${s.source_row_end}`}
          </option>)}
        </select>
      </Field>
      <Field label="Vg 단위"><select value={d.units.vgs_v || ''} onChange={e => update({units: {...d.units, vgs_v: e.target.value}})}><option value="">단위 선택</option>{unitOptions('vgs_v').map(u => <option key={u}>{u}</option>)}</select></Field>
      <Field label="Id 단위"><select value={d.units.id_a || ''} onChange={e => update({units: {...d.units, id_a: e.target.value}})}><option value="">단위 선택</option>{unitOptions('id_a').map(u => <option key={u}>{u}</option>)}</select></Field>
    </div>
    <p className="muted">분기와 스윕 진폭은 선택한 구간과 블록에서 채워지며, 서버가 방향·진폭이 맞는지 다시 검사합니다.</p>
    <Notices items={layout.warnings} />
  </div>;
}

export function RetentionColumnPicker({d, update}: {d: Dataset; update: Update}) {
  const layout = d.retentionLayout;
  if (!layout) return null;
  const columns = d.retentionColumns || {};
  const setColumn = (role: string, value: string) => update({retentionColumns: {...columns, [role]: value}});
  const setUnits = (patch: Record<string, string>) => update({units: {...d.units, ...patch}});
  return <div className="layout-picker">
    <p className="notice">Erase와 Program이 <strong>서로 다른 시간 열</strong>을 씁니다. 네 열을 직접 지정하세요. 헤더 이름으로 한 열이 확실히 정해지는 경우만 미리 채웠습니다. 두 시트의 시간 값은 합치지 않고 방향별로 각자의 시간축에서 적합합니다.</p>
    <DataTable caption={`시트 ${layout.sheet} · 열 미리보기`} rows={layout.columns.map(c => ({열: `C${c.index}`, 헤더: c.header, 값수: c.non_empty, '처음 값': c.first.join(', ')}))} />
    <div className="form-grid">
      {RETENTION_LABELS.map(([role, label]) => <Field key={role} label={label}>
        <select value={columns[role] ?? ''} onChange={e => setColumn(role, e.target.value)}>
          <option value="">열 선택</option>
          {layout.columns.map(c => <option key={c.index} value={String(c.index)}>{`C${c.index} · ${c.header ?? '(헤더 없음)'}`}</option>)}
        </select>
      </Field>)}
      <Field label="시간 단위"><select value={d.units.erase_time_s || ''} onChange={e => setUnits({erase_time_s: e.target.value, program_time_s: e.target.value})}><option value="">단위 선택</option>{unitOptions('time_s').map(u => <option key={u}>{u}</option>)}</select></Field>
      <Field label="전류 단위"><select value={d.units.erase_id_a || ''} onChange={e => setUnits({erase_id_a: e.target.value, program_id_a: e.target.value})}><option value="">단위 선택</option>{unitOptions('id_a').map(u => <option key={u}>{u}</option>)}</select></Field>
    </div>
    {!!layout.embedded_source_headers.length && <details><summary>같은 파일의 다른 시트에 적힌 원본 이름 · 참고용</summary>
      <p className="muted">읽기 바이어스와 번호 표기의 출처 기록입니다. 이 값으로 열을 고르거나 데이터를 제외하지 않습니다. 원본 데이터 라벨(R1, R3(1) …)은 승인 문서의 조건 매핑을 따라 직접 입력하세요.</p>
      <DataTable rows={layout.embedded_source_headers.map(h => ({시트: h.sheet, 이름: h.header, '읽기 바이어스 (V)': h.read_bias_v.join(', '), '괄호 번호': h.embedded_numbers.join(', ')}))} />
    </details>}
    <Notices items={layout.warnings} />
  </div>;
}

export function C2cConditions({d, update}: {d: Dataset; update: Update}) {
  const conditions = d.conditions || {};
  return <div className="layout-picker">
    <p className="notice">열은 헤더(<code>Cycle</code>, <code>Program_Id_*</code>, <code>Erase_Id_*</code>, 선택 <code>Erase_minus_Program_*</code>)로 인식합니다: <strong>{d.preview?.columns.join(' · ') || '미리보기 없음'}</strong>. 상대 편차 분석은 아래 측정 조건을 모두 알지 못해도 실행됩니다. <strong>비워 둔 항목은 "미확인"으로 기록</strong>되며 LTP/LTD의 조건을 가져오지 않습니다. 절대 전도도로 바꾸려면 VDS가 필요합니다.</p>
    <div className="form-grid">
      {c2cConditionFields.map(f => <Field key={f.key} label={f.unit ? `${f.label} (${f.unit})` : f.label} hint={f.hint || undefined}>
        <input value={conditions[f.key] ?? ''} inputMode={f.kind === 'text' ? 'text' : 'decimal'} onChange={e => update({conditions: {...conditions, [f.key]: e.target.value}})} />
      </Field>)}
    </div>
  </div>;
}

const fixed = (v: unknown, digits: number) => typeof v === 'number' ? v.toFixed(digits) : '정의 불가';

export function C2cSummary({analysis}: {analysis: Analysis}) {
  const {program, erase} = analysis;
  if (!program || !erase) return null;
  const row = (name: string, b: NonNullable<Analysis['program']>) => ({
    분기: name, 상태: b.status, '추세 보정 후 상대 편차 (%)': fixed(b.primary.relative_residual_std_percent, 6), '3차 잔차 lag-1 상관': fixed(b.primary.residual_lag1_correlation, 3),
    '4차 vs 3차 변화 (%)': fixed(b.degree4_vs_degree3_change_percent, 1), '원본 상대 표준편차 (%)': fixed(b.raw_statistics.relative_std_percent, 3)});
  return <>
    <h4>C2C 분석 요약</h4>
    <DataTable rows={[row('Program (시뮬레이터 후보)', program), row('Erase (분석 전용)', erase)]} />
    <p className="notice">추세 보정 후 편차이며 <strong>독립 동일분포의 순수 C2C 추정이 아닙니다</strong>. 시뮬레이터에는 Program 값만 사용자 승인 후 적용할 수 있고, Erase는 적용·평균하지 않습니다.</p>
    <p className="muted">원본 전류와 추세, 상대 잔차 그래프는 아래 그림에서, 회차별 값은 접힌 표(50행씩) 또는 다운로드 파일에서 확인하세요. <a href="/simulator">시뮬레이터</a>에서 C2C 출처로 선택합니다.</p>
  </>;
}
