import Link from "next/link";

import type { HorizonStatus } from "@/lib/types";
import { durationFromMinutes } from "@/lib/format";

/**
 * The three detection horizons, as a filter and as a progress readout.
 *
 * Warm-up is (window + gap + 1) * bucket_minutes, so a short bucket answers
 * sooner and a long one answers better. Showing all three is the point: an
 * hour in there is already something to read, and the deeper horizons fill in
 * behind it rather than gating the whole dashboard on the slowest one.
 */
export default function HorizonBar({
  horizons,
  active,
}: {
  horizons: HorizonStatus[];
  active?: string;
}) {
  if (horizons.length === 0) return null;

  return (
    <section className="border-b border-line py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
        <span className="text-[11px] uppercase tracking-wider text-faint">Horizon</span>

        <Link
          href="/"
          aria-current={active ? undefined : "true"}
          className={`rounded-inst border px-2 py-1 font-mono text-[11px] transition-colors ${
            active
              ? "border-line text-dim hover:border-line-strong hover:text-ink"
              : "border-accent bg-accent-soft text-accent"
          }`}
        >
          all
        </Link>

        {horizons.map((h) => {
          const selected = active === h.mode;
          const progress = h.ready
            ? 100
            : Math.min(100, ((h.warmup_minutes - h.minutes_remaining) / h.warmup_minutes) * 100);

          return (
            <Link
              key={h.mode}
              href={`/?mode=${h.mode}`}
              aria-current={selected ? "true" : undefined}
              title={`${h.description} ${h.bucket_minutes}-minute buckets, ${h.baseline_window}-bucket baseline, z ≥ ${h.z_threshold}.`}
              className={`group relative overflow-hidden rounded-inst border px-2 py-1 transition-colors ${
                selected
                  ? "border-accent bg-accent-soft"
                  : "border-line hover:border-line-strong"
              } ${h.ready ? "" : "opacity-70"}`}
            >
              {/* Warm-up progress sits behind the label rather than in its own
                  row, so a horizon that is not ready still reads as one item. */}
              {!h.ready && (
                <span
                  className="absolute inset-y-0 left-0 bg-line"
                  style={{ width: `${progress}%` }}
                  aria-hidden
                />
              )}

              <span className="relative flex items-baseline gap-1.5">
                <span
                  className={`font-mono text-[11px] ${selected ? "text-accent" : "text-ink"}`}
                >
                  {h.mode}
                </span>
                <span className="num text-[10px] text-faint">{h.warmup_hours}h</span>
                {h.ready ? (
                  <span className="num text-[10px] text-dim">{h.alerts}</span>
                ) : (
                  <span className="num text-[10px] text-faint">
                    +{durationFromMinutes(h.minutes_remaining)}
                  </span>
                )}
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
