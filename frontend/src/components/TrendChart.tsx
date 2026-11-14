import { useId, useMemo, useState, type PointerEvent } from "react";

/**
 * Small multi-series line chart (one shared axis — every series must share a unit).
 * Palette: validated categorical slots 1–3 (light surface #ffffff, validate_palette.js: all checks pass; slot 3 is
 * below 3:1 contrast, so series are direct-labelled at line ends and a table view is always available).
 */
export type TrendSeries = { key: string; label: string; values: (number | null)[] };

const COLORS = ["#2a78d6", "#eb6834", "#1baf7a"];
const W = 720;
const H = 240;
const M = { top: 12, right: 150, bottom: 28, left: 44 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / p) * p;
}

export function TrendChart({
  title,
  unit,
  xLabels,
  series,
}: {
  title: string;
  unit: string;
  xLabels: string[];
  series: TrendSeries[];
}) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const max = useMemo(() => niceMax(Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v !== null)))), [series]);
  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;
  const n = xLabels.length;
  const x = (i: number) => M.left + (n <= 1 ? innerW / 2 : (i * innerW) / (n - 1));
  const y = (v: number) => M.top + innerH - (v / max) * innerH;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(t * max));

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * innerW;
    setHover(n <= 1 ? 0 : Math.max(0, Math.min(n - 1, Math.round((px / innerW) * (n - 1)))));
  };

  if (n === 0) return null;
  return (
    <figure className="rounded border border-slate-200 bg-white p-3" aria-labelledby={`${id}-t`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <figcaption id={`${id}-t`} className="text-sm font-semibold text-slate-700">
          {title} <span className="font-normal text-slate-500">({unit})</span>
        </figcaption>
        <div className="flex items-center gap-3 text-xs text-slate-600">
          <ul className="flex gap-3" aria-label="Legend">
            {series.map((s, i) => (
              <li key={s.key} className="flex items-center gap-1">
                <span aria-hidden="true" className={`inline-block h-0.5 w-4 legend-swatch-${i}`} />
                {s.label}
              </li>
            ))}
          </ul>
          <button type="button" className="underline" aria-pressed={showTable} onClick={() => setShowTable((v) => !v)}>
            {showTable ? "Show chart" : "Show table"}
          </button>
        </div>
      </div>
      {showTable ? (
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr>
                <th scope="col" className="px-2 py-1 text-left">Day (UTC)</th>
                {series.map((s) => <th key={s.key} scope="col" className="px-2 py-1 text-right">{s.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {xLabels.map((label, i) => (
                <tr key={`${label}-${i}`} className="border-t border-slate-100">
                  <th scope="row" className="px-2 py-1 text-left font-normal">{label}</th>
                  {series.map((s) => <td key={s.key} className="px-2 py-1 text-right">{s.values[i] ?? "n/a"}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="h-auto max-h-72 w-full" role="img" aria-label={`${title}. Use “Show table” for the values.`}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} stroke="#e2e8f0" strokeWidth={1} />
                <text x={M.left - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="#64748b">{t}</text>
              </g>
            ))}
            {[0, n - 1].filter((v, i, a) => a.indexOf(v) === i).map((i) => (
              <text key={i} x={x(i)} y={H - 8} textAnchor={i === 0 && n > 1 ? "start" : "end"} fontSize={10} fill="#64748b">
                {xLabels[i]}
              </text>
            ))}
            {series.map((s, si) => {
              type Pt = { px: number; py: number; v: number; i: number };
              const segments: Pt[][] = [];
              let current: Pt[] = [];
              s.values.forEach((v, i) => {
                if (v === null) {
                  if (current.length) segments.push(current);
                  current = [];
                } else {
                  current.push({ px: x(i), py: y(v), v, i });
                }
              });
              if (current.length) segments.push(current);
              const last = segments.at(-1)?.at(-1);
              return (
                <g key={s.key}>
                  {segments.map((seg, k) => {
                    const first = seg[0];
                    if (seg.length === 1 && first) {
                      return <circle key={k} cx={first.px} cy={first.py} r={3} fill={COLORS[si]} />;
                    }
                    return (
                      <polyline key={k} points={seg.map((p) => `${p.px},${p.py}`).join(" ")} fill="none" stroke={COLORS[si]}
                                strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                    );
                  })}
                  {last ? (
                    <text x={last.px + 6} y={last.py + 3} fontSize={10} fill="#334155">
                      {s.label}: {last.v}
                    </text>
                  ) : null}
                </g>
              );
            })}
            {hover !== null ? (
              <g>
                <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + innerH} stroke="#94a3b8" strokeWidth={1} />
                {series.map((s, si) => {
                  const v = s.values[hover];
                  return v === null || v === undefined ? null : (
                    <circle key={s.key} cx={x(hover)} cy={y(v)} r={4.5} fill={COLORS[si]} stroke="#ffffff" strokeWidth={2} />
                  );
                })}
              </g>
            ) : null}
            <rect x={M.left} y={M.top} width={innerW} height={innerH} fill="transparent"
                  onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
          </svg>
          {hover !== null ? (
            <div role="status" className="pointer-events-none absolute left-14 top-1 rounded border border-slate-200 bg-white px-2 py-1 text-xs shadow">
              <div className="font-medium text-slate-800">{xLabels[hover]}</div>
              {series.map((s, si) => (
                <div key={s.key} className="flex items-center gap-1 text-slate-700">
                  <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full legend-dot-${si}`} />
                  {s.label}: <span className="font-medium">{s.values[hover] ?? "n/a"}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </figure>
  );
}
