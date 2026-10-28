import type { ReactNode } from "react";

/** Stat tile: label, value, optional detail line. Values arrive already formatted with units. */
export function StatTile({ label, value, detail }: { label: string; value: string; detail?: ReactNode }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {detail !== undefined && <div className="detail">{detail}</div>}
    </div>
  );
}

/** Single-series horizontal bars as accessible HTML (one color; the length carries the value). */
export function BarList({ items, format, label }: { items: [string, number][]; format: (v: number) => string; label: string }) {
  const max = Math.max(...items.map(([, v]) => v), 1e-9);
  return (
    <div className="bar-list" role="list" aria-label={label}>
      {items.map(([name, value]) => (
        <div className="bar-row" role="listitem" key={name} aria-label={`${name}: ${format(value)}`}>
          <span>{name}</span>
          <span className="track">
            <span className="fill" style={{ display: "block", width: `${(value / max) * 100}%` }} />
          </span>
          <span className="val">{format(value)}</span>
        </div>
      ))}
    </div>
  );
}

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  text?: boolean; // left-aligned text column (numbers stay right-aligned)
}

export function DataTable<T>({ caption, columns, rows, rowKey, emphasis }: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  emphasis?: (row: T) => boolean;
}) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={caption}>
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.header} scope="col" className={c.text ? "text" : undefined}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className={emphasis?.(row) ? "emphasis" : undefined}>
              {columns.map((c) => (
                <td key={c.header} className={c.text ? "text" : undefined}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
