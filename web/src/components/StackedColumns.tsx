import { scaleLinear } from "d3-scale";
import { useId, useMemo, useState } from "react";

import { useWidth } from "./useWidth";

export interface Part {
  id: string;
  label: string;
  color: string;
}

interface Props {
  title: string;
  summary: string;
  categories: string[]; // x labels (months or years)
  parts: Part[];
  values: number[][]; // values[category][part], non-negative
  format: (value: number) => string;
  height?: number;
}

const MARGIN = { top: 12, right: 12, bottom: 28, left: 56 };
const GAP = 2;

/** Stacked columns for part-to-whole over time: 2px surface gaps, rounded top, one baseline. */
export function StackedColumns({ title, summary, categories, parts, values, format, height = 220 }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const descriptionId = useId();
  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = height - MARGIN.top - MARGIN.bottom;
  const totals = values.map((row) => row.reduce((a, b) => a + b, 0));
  const y = useMemo(
    () => scaleLinear().domain([0, Math.max(...totals, 1)]).nice(4).range([innerHeight, 0]),
    [totals, innerHeight],
  );
  const band = innerWidth / Math.max(categories.length, 1);
  const barWidth = Math.max(2, Math.min(24, band - GAP));
  const labelEvery = Math.max(1, Math.ceil(categories.length / Math.max(2, Math.floor(innerWidth / 70))));

  return (
    <div className="chart" ref={ref}>
      <div className="legend" aria-hidden="true">
        {parts.map((p) => (
          <span key={p.id}>
            <i className="key-box" style={{ background: p.color }} />
            {p.label}
          </span>
        ))}
      </div>
      <svg width={width} height={height} role="img" aria-label={title} aria-describedby={descriptionId}>
        <desc id={descriptionId}>{summary}</desc>
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {y.ticks(4).map((t) => (
            <g key={t}>
              <line x1={0} x2={innerWidth} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
              <text x={-8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--ink-muted)">
                {format(t)}
              </text>
            </g>
          ))}
          {values.map((row, i) => {
            const cx = band * i + band / 2;
            let base = innerHeight;
            const topPart = row.reduce((last, v, j) => (v > 0 ? j : last), -1);
            return (
              <g
                key={categories[i]}
                tabIndex={0}
                role="graphics-symbol"
                aria-label={`${categories[i]}: ${parts.map((p, j) => `${p.label} ${format(row[j] ?? 0)}`).join(", ")}`}
                onPointerEnter={() => setActive(i)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
                opacity={active === null || active === i ? 1 : 0.55}
              >
                <rect x={cx - band / 2} y={0} width={band} height={innerHeight} fill="transparent" />
                {row.map((v, j) => {
                  if (v <= 0) return null;
                  const h = innerHeight - y(v);
                  const top = base - h;
                  const drawn = Math.max(h - (j === topPart ? 0 : GAP), 0.5);
                  base = top;
                  const part = parts[j];
                  if (!part) return null;
                  if (j === topPart) {
                    const r = Math.min(4, barWidth / 2, drawn);
                    const x0 = cx - barWidth / 2;
                    const x1 = cx + barWidth / 2;
                    const yb = top + drawn;
                    return (
                      <path
                        key={part.id}
                        fill={part.color}
                        d={`M${x0},${yb} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x1 - r} Q${x1},${top} ${x1},${top + r} V${yb} Z`}
                      />
                    );
                  }
                  return <rect key={part.id} x={cx - barWidth / 2} y={top + GAP} width={barWidth} height={drawn} fill={part.color} />;
                })}
                {i % labelEvery === 0 && (
                  <text x={cx} y={innerHeight + 18} textAnchor="middle" fontSize={11} fill="var(--ink-muted)">
                    {categories[i]}
                  </text>
                )}
              </g>
            );
          })}
          <line x1={0} x2={innerWidth} y1={innerHeight} y2={innerHeight} stroke="var(--axis)" strokeWidth={1} />
        </g>
      </svg>
      {active !== null && (
        <div
          className="tooltip"
          style={{
            top: 8,
            left: band * active + MARGIN.left > width * 0.6 ? undefined : band * active + MARGIN.left + band,
            right: band * active + MARGIN.left > width * 0.6 ? width - (band * active + MARGIN.left) + 4 : undefined,
          }}
          role="presentation"
        >
          <div className="when">{categories[active]}</div>
          {parts.map((p, j) => (
            <div className="row" key={p.id}>
              <i className="key-box" style={{ background: p.color }} />
              <span>{p.label}</span>
              <strong>{format(values[active]?.[j] ?? 0)}</strong>
            </div>
          ))}
          <div className="row">
            <i />
            <span>Total</span>
            <strong>{format(totals[active] ?? 0)}</strong>
          </div>
        </div>
      )}
    </div>
  );
}
