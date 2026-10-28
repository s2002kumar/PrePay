import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { useId, useMemo, useState } from "react";

import { useWidth } from "./useWidth";

export interface Series {
  id: string;
  label: string;
  color: string; // a CSS custom property reference, e.g. "var(--series-1)"
  values: (number | null)[];
}

interface Props {
  title: string;
  xLabels: string[];
  series: Series[];
  yFormat: (value: number) => string;
  height?: number;
  includeZero?: boolean;
  summary: string;
}

const MARGIN = { top: 12, right: 64, bottom: 28, left: 56 };

function xTicks(labels: string[], width: number): number[] {
  const n = labels.length;
  if (n <= 1) return [0];
  const target = Math.max(2, Math.floor(width / 90));
  const yearly = n > 36;
  const step = yearly ? Math.max(12, Math.ceil(n / target / 12) * 12) : Math.max(1, Math.ceil(n / target));
  const ticks: number[] = [];
  const first = yearly ? labels.findIndex((l) => l.endsWith("-01")) : 0;
  for (let i = Math.max(first, 0); i < n; i += step) ticks.push(i);
  return ticks;
}

export function LineChart({ title, xLabels, series, yFormat, height = 220, includeZero = false, summary }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const [announce, setAnnounce] = useState("");
  const descriptionId = useId();
  const n = xLabels.length;
  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = height - MARGIN.top - MARGIN.bottom;

  const { x, y, yTicks } = useMemo(() => {
    const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null && Number.isFinite(v)));
    let low = all.length ? Math.min(...all) : 0;
    let high = all.length ? Math.max(...all) : 1;
    if (includeZero) low = Math.min(low, 0);
    if (high - low < 1e-9) {
      high += Math.abs(high) * 0.05 + 1e-6;
      low -= Math.abs(low) * 0.05 + 1e-6;
    }
    const yScale = scaleLinear().domain([low, high]).nice(4).range([innerHeight, 0]);
    const xScale = scaleLinear().domain([0, Math.max(n - 1, 1)]).range([0, innerWidth]);
    return { x: xScale, y: yScale, yTicks: yScale.ticks(4) };
  }, [series, includeZero, innerHeight, innerWidth, n]);

  const path = line<number | null>()
    .defined((v) => v !== null && Number.isFinite(v))
    .x((_, i) => x(i))
    .y((v) => y(v ?? 0));

  // Direct end labels only when they don't collide; otherwise legend + tooltip carry identity.
  const ends = series.map((s) => {
    const last = [...s.values].reverse().find((v) => v !== null && Number.isFinite(v));
    return last === undefined || last === null ? null : y(last);
  });
  const endsCollide = ends.some((a, i) => ends.some((b, j) => i < j && a !== null && b !== null && Math.abs(a - b) < 14));

  function readout(index: number): string {
    return `${xLabels[index] ?? ""}: ${series
      .map((s) => `${s.label} ${s.values[index] === null || s.values[index] === undefined ? "n/a" : yFormat(s.values[index])}`)
      .join(", ")}`;
  }

  function onPointer(event: React.PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - box.left - MARGIN.left;
    const index = Math.round(x.invert(Math.min(Math.max(px, 0), innerWidth)));
    setActive(Math.min(Math.max(index, 0), n - 1));
  }

  function onKey(event: React.KeyboardEvent<SVGSVGElement>) {
    let next = active ?? n - 1;
    if (event.key === "ArrowRight") next = Math.min(n - 1, next + 1);
    else if (event.key === "ArrowLeft") next = Math.max(0, next - 1);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = n - 1;
    else if (event.key === "Escape") {
      setActive(null);
      return;
    } else return;
    event.preventDefault();
    setActive(next);
    setAnnounce(readout(next));
  }

  const ticks = xTicks(xLabels, innerWidth);
  const tooltipLeft = active === null ? 0 : MARGIN.left + x(active);
  const flip = active !== null && x(active) > innerWidth * 0.6;

  return (
    <div className="chart" ref={ref}>
      {series.length > 1 && (
        <div className="legend" aria-hidden="true">
          {series.map((s) => (
            <span key={s.id}>
              <i className="key-line" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={title}
        aria-describedby={descriptionId}
        tabIndex={0}
        onPointerMove={onPointer}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        <desc id={descriptionId}>{summary} Use the left and right arrow keys to read values.</desc>
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={0} x2={innerWidth} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
              <text x={-8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--ink-muted)">
                {yFormat(t)}
              </text>
            </g>
          ))}
          <line x1={0} x2={innerWidth} y1={innerHeight} y2={innerHeight} stroke="var(--axis)" strokeWidth={1} />
          {ticks.map((i) => (
            <text key={i} x={x(i)} y={innerHeight + 18} textAnchor="middle" fontSize={11} fill="var(--ink-muted)">
              {n > 36 ? (xLabels[i] ?? "").slice(0, 4) : xLabels[i]}
            </text>
          ))}
          {series.map((s) => (
            <path
              key={s.id}
              d={path(s.values) ?? ""}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
          {!endsCollide &&
            series.map((s, i) => {
              const end = ends[i];
              const last = [...s.values].reverse().find((v) => v !== null);
              if (end === null || end === undefined || last === null || last === undefined) return null;
              return (
                <text key={s.id} x={innerWidth + 6} y={end} dy="0.32em" fontSize={11} fill="var(--ink-2)">
                  {yFormat(last)}
                </text>
              );
            })}
          {active !== null && (
            <g pointerEvents="none">
              <line x1={x(active)} x2={x(active)} y1={0} y2={innerHeight} stroke="var(--axis)" strokeWidth={1} />
              {series.map((s) => {
                const v = s.values[active];
                if (v === null || v === undefined) return null;
                return (
                  <circle key={s.id} cx={x(active)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                );
              })}
            </g>
          )}
        </g>
      </svg>
      {active !== null && (
        <div
          className="tooltip"
          style={{ top: 8, left: flip ? undefined : tooltipLeft + 12, right: flip ? width - tooltipLeft + 12 : undefined }}
          role="presentation"
        >
          <div className="when">{xLabels[active]}</div>
          {series.map((s) => {
            const v = s.values[active];
            return (
              <div className="row" key={s.id}>
                <i className="key-line" style={{ background: s.color }} />
                <span>{s.label}</span>
                <strong>{v === null || v === undefined ? "n/a" : yFormat(v)}</strong>
              </div>
            );
          })}
        </div>
      )}
      <div className="sr-only" aria-live="polite">
        {announce}
      </div>
    </div>
  );
}
