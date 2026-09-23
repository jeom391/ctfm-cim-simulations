export const PAGE_SIZE = 50;

// Keep nested arrays out of the display model without changing the server result.
export function compactValue(value: unknown, depth = 0): unknown {
  if (Array.isArray(value)) return `${value.length}개 · 전체 파일에서 확인`;
  if (value && typeof value === 'object') {
    if (depth >= 3) return '상세 객체 · 전체 파일에서 확인';
    return Object.fromEntries(Object.entries(value).slice(0, 30).map(([k, v]) => [k, compactValue(v, depth + 1)]));
  }
  if (typeof value === 'string' && value.length > 180) return value.slice(0, 180) + '…';
  return value;
}
export function pageRows<T>(rows: T[], requested: number) {
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const page = Math.min(Math.max(0, requested), pages - 1);
  return {page, pages, rows: rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)};
}
