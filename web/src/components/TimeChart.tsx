import { scaleLinear } from "d3-scale";
import { area, line } from "d3-shape";
import { type ReactNode, useId, useMemo, useState } from "react";

import { useWidth } from "./useWidth";

export interface TimeSeries {
  id: string;
  label: string;
  color: string; // a CSS custom property reference, e.g. "var(--a)"
  values: (number | null)[]; // index i is month x0 + i
  dashed?: boolean;
}

/** A vertical bracket: the spread across model families at one month (not a confidence interval). */
export interface Bracket {
  month: number;
  low: number;
  high: number;
  color: string;
  label: string;
}

interface Props {
  title: string;
  summary: string;
  series: TimeSeries[];
  /** Month of values[0] (0 when the series starts at the as-of point). */
  x0: number;
  /** Last month on the axis. */
  n: number;
  yFormat: (value: number) => string;
  yTickFormat?: (value: number) => string;
  yDomain?: [number, number];
  includeZero?: boolean;
  height?: number;
  /** Shared cursor month (1..n); the chart reports moves through onCursor. */
  cursor: number;
  onCursor: (month: number) => void;
  band?: [string, string] | undefined;
  refs?: { y: number; label: string }[];
  marks?: { month: number; label: string }[];
  brackets?: Bracket[];
  endLabels?: boolean;
  /** Floating readout while the pointer or keyboard is on the chart. */
  tooltip?: (month: number) => ReactNode;
  monthLabel: (month: number) => string;
  compact?: boolean;
  testId?: string;
}

function monthTicks(n: number, width: number): number[] {
  const target = Math.max(2, Math.floor(width / 64));
  const steps = [1, 2, 3, 6, 12, 24, 60, 120];
  const step = steps.find((s) => n / s <= target) ?? 120;
  const ticks: number[] = [];
  for (let m = 0; m <= n; m += step) ticks.push(m);
  return ticks;
}

/** Month-indexed line chart with a cursor shared across the lab; pointer and keyboard readable. */
export function TimeChart(props: Props) {
  const {
    title, summary, series, x0, n, yFormat, yTickFormat = yFormat, yDomain, includeZero = false, height = 260,
    cursor, onCursor, band, refs = [], marks = [], brackets = [], endLabels = false, tooltip, monthLabel, compact = false, testId,
  } = props;
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState(false);
  const [announce, setAnnounce] = useState("");
  const descriptionId = useId();
  const margin = { top: 14, right: endLabels ? 74 : 14, bottom: 26, left: compact ? 44 : 52 };
  const innerWidth = Math.max(40, width - margin.left - margin.right);
  const innerHeight = height - margin.top - margin.bottom;

  const { x, y, yTicks } = useMemo(() => {
    let low: number;
    let high: number;
    if (yDomain) [low, high] = yDomain;
    else {
      const all = [
        ...series.flatMap((s) => s.values.filter((v): v is number => v !== null && Number.isFinite(v))),
        ...refs.map((r) => r.y),
        ...brackets.flatMap((b) => [b.low, b.high]),
      ];
      low = all.length ? Math.min(...all) : 0;
      high = all.length ? Math.max(...all) : 1;
      if (includeZero) low = Math.min(low, 0);
      if (high - low < 1e-9) {
        high += Math.abs(high) * 0.05 + 1e-6;
        low -= Math.abs(low) * 0.05 + 1e-6;
      }
    }
    const yScale = scaleLinear().domain([low, high]).nice(compact ? 3 : 4).range([innerHeight, 0]);
    const xScale = scaleLinear().domain([0, Math.max(n, 1)]).range([0, innerWidth]);
    return { x: xScale, y: yScale, yTicks: yScale.ticks(compact ? 3 : 4) };
  }, [series, refs, brackets, yDomain, includeZero, innerHeight, innerWidth, n, compact]);

  const valueAt = (s: TimeSeries, month: number): number | null => s.values[month - x0] ?? null;
  const path = line<number | null>()
    .defined((v) => v !== null && Number.isFinite(v))
    .x((_, i) => x(i + x0))
    .y((v) => y(v ?? 0));
  const bandSeries = band ? [series.find((s) => s.id === band[0]), series.find((s) => s.id === band[1])] : [];
  const bandPath =
    bandSeries[0] && bandSeries[1]
      ? area<number>()
          .x((i) => x(i + x0))
          .y0((i) => y(bandSeries[0]?.values[i] ?? 0))
          .y1((i) => y(bandSeries[1]?.values[i] ?? 0))(
          Array.from({ length: Math.min(bandSeries[0].values.length, bandSeries[1].values.length) }, (_, i) => i),
        )
      : null;

  // Direct end labels, nudged apart so they never overlap.
  const ends = endLabels
    ? series
        .map((s) => {
          const last = s.values[s.values.length - 1];
          return last === null || last === undefined ? null : { s, last, y: y(last) };
        })
        .filter((e): e is { s: TimeSeries; last: number; y: number } => e !== null)
        .sort((p, q) => p.y - q.y)
    : [];
  for (let i = 1; i < ends.length; i++) {
    const prev = ends[i - 1];
    const cur = ends[i];
    if (prev && cur && cur.y - prev.y < 16) cur.y = prev.y + 16;
  }

  function moveTo(month: number, speak: boolean) {
    const m = Math.max(1, Math.min(n, Math.round(month)));
    onCursor(m);
    if (speak) {
      setAnnounce(`${monthLabel(m)}: ${series.map((s) => `${s.label} ${formatOr(valueAt(s, m), yFormat)}`).join(", ")}`);
    }
  }

  function onPointer(event: React.PointerEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    moveTo(x.invert(Math.min(Math.max(event.clientX - box.left, 0), innerWidth)), false);
    setHover(true);
  }

  function onKey(event: React.KeyboardEvent<SVGSVGElement>) {
    const steps: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, PageUp: 12, PageDown: -12 };
    let next: number;
    if (event.key in steps) next = cursor + (steps[event.key] ?? 0);
    else if (event.key === "Home") next = 1;
    else if (event.key === "End") next = n;
    else return;
    event.preventDefault();
    setHover(true);
    moveTo(next, true);
  }

  const cx = x(cursor);
  const flip = cx > innerWidth * 0.55;
  const ticks = monthTicks(n, innerWidth);

  return (
    <div className={`tchart${compact ? " compact" : ""}`} ref={ref} data-testid={testId}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={title}
        aria-describedby={descriptionId}
        tabIndex={0}
        onKeyDown={onKey}
        onFocus={() => setHover(true)}
        onBlur={() => setHover(false)}
      >
        <desc id={descriptionId}>
          {summary} Arrow keys move one month, Page Up and Page Down one year; every chart and the inspector follow.
        </desc>
        <g transform={`translate(${margin.left},${margin.top})`}>
          {yTicks.map((t) => (
            <g key={t}>
              <line className="grid" x1={0} x2={innerWidth} y1={y(t)} y2={y(t)} />
              <text className="tick" x={-8} y={y(t)} dy="0.32em" textAnchor="end">
                {yTickFormat(t)}
              </text>
            </g>
          ))}
          <line className="axis" x1={0} x2={innerWidth} y1={innerHeight} y2={innerHeight} />
          {ticks.map((m) => (
            <text key={m} className="tick" x={x(m)} y={innerHeight + 17} textAnchor="middle">
              {m}
            </text>
          ))}
          {marks.map((mk) => (
            <g key={mk.label}>
              <line className="mark" x1={x(mk.month)} x2={x(mk.month)} y1={0} y2={innerHeight} />
              <text className="mark-label" x={x(mk.month) + 5} y={innerHeight - 6}>
                {mk.label}
              </text>
            </g>
          ))}
          {refs.map((r) => (
            <g key={r.label}>
              <line className="ref" x1={0} x2={innerWidth} y1={y(r.y)} y2={y(r.y)} />
              <text className="ref-label" x={6} y={y(r.y) - 5}>
                {r.label}
              </text>
            </g>
          ))}
          {bandPath && <path className="gap-band" d={bandPath} />}
          {series.map((s) => (
            <path
              key={s.id}
              d={path(s.values) ?? ""}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeDasharray={s.dashed ? "6 4" : undefined}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
          {brackets.map((b) => (
            <g key={`${b.label}-${b.month}`} className="bracket" stroke={b.color}>
              <title>{b.label}</title>
              <line x1={x(b.month)} x2={x(b.month)} y1={y(b.low)} y2={y(b.high)} />
              <line x1={x(b.month) - 4} x2={x(b.month) + 4} y1={y(b.low)} y2={y(b.low)} />
              <line x1={x(b.month) - 4} x2={x(b.month) + 4} y1={y(b.high)} y2={y(b.high)} />
            </g>
          ))}
          <line className="cursor" x1={cx} x2={cx} y1={0} y2={innerHeight} />
          {series.map((s) => {
            const v = valueAt(s, cursor);
            return v === null ? null : <circle key={s.id} className="dot" cx={cx} cy={y(v)} r={4} fill={s.color} />;
          })}
          {ends.map((e) => (
            <g key={e.s.id}>
              <circle cx={innerWidth + 6} cy={e.y} r={3} fill={e.s.color} />
              <text className="end-label" x={innerWidth + 13} y={e.y} dy="0.32em">
                {e.s.id.toUpperCase()} {yFormat(e.last)}
              </text>
            </g>
          ))}
          <rect
            className="hit"
            x={0}
            y={0}
            width={innerWidth}
            height={innerHeight}
            onPointerMove={onPointer}
            onPointerDown={onPointer}
            onPointerLeave={() => setHover(false)}
          />
        </g>
      </svg>
      {tooltip && hover && (
        <div
          className="tip"
          role="presentation"
          style={flip ? { right: width - margin.left - cx + 12, top: margin.top } : { left: margin.left + cx + 12, top: margin.top }}
        >
          {tooltip(cursor)}
        </div>
      )}
      <div className="sr-only" aria-live="polite">
        {announce}
      </div>
    </div>
  );
}

function formatOr(v: number | null, f: (v: number) => string): string {
  return v === null ? "n/a" : f(v);
}
