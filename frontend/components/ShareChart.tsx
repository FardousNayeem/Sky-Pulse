import type { SeriesPoint } from "@/lib/types";
import { clockTime, percent } from "@/lib/format";

/**
 * Share of conversation over time, with the median as a reference line.
 * Buckets where the collector was not fully running are shaded rather than
 * dropped, so gaps stay visible instead of being silently smoothed over.
 */
export default function ShareChart({
  points,
  height = 200,
}: {
  points: SeriesPoint[];
  height?: number;
}) {
  if (points.length < 2) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center border border-line text-[13px] text-faint"
      >
        Not enough data yet
      </div>
    );
  }

  const width = 1000;
  const pad = 8;
  const shares = points.map((p) => p.share);
  const max = Math.max(...shares) || 1;
  const sorted = [...shares].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const step = width / (points.length - 1);
  const y = (share: number) => height - pad - (share / max) * (height - pad * 2);

  const line = points.map((p, i) => `${(i * step).toFixed(1)},${y(p.share).toFixed(1)}`).join(" ");
  const peak = points.reduce((a, b) => (b.share > a.share ? b : a));

  return (
    <figure className="space-y-1.5">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{ height }}
        className="w-full border border-line bg-panel"
        role="img"
        aria-label={`Share of conversation across ${points.length} buckets, peaking at ${percent(peak.share)}`}
      >
        {points.map((p, i) =>
          p.coverage < 0.8 ? (
            <rect
              key={p.t}
              x={i * step - step / 2}
              y={0}
              width={step}
              height={height}
              className="fill-sev-med-soft"
            />
          ) : null,
        )}
        <polygon points={`0,${height} ${line} ${width},${height}`} className="fill-accent-soft" />
        <line
          x1={0}
          x2={width}
          y1={y(median)}
          y2={y(median)}
          className="stroke-line-strong"
          strokeWidth={1}
          strokeDasharray="3 5"
          vectorEffect="non-scaling-stroke"
        />
        <polyline
          points={line}
          fill="none"
          className="stroke-accent"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      <figcaption className="flex justify-between font-mono text-[11px] text-faint">
        <span>{clockTime(points[0].t)}</span>
        <span>
          median {percent(median)} · peak {percent(peak.share)}
        </span>
        <span>{clockTime(points[points.length - 1].t)}</span>
      </figcaption>
    </figure>
  );
}
