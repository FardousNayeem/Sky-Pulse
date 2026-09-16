import type { CorpusStats } from "@/lib/types";
import { durationFromMinutes } from "@/lib/format";

/** Shown until enough history exists for a baseline. A spike is only
 *  meaningful against normal, so detection waits for a trailing window. */
export default function CollectionProgress({ stats }: { stats: CorpusStats }) {
  const needed = stats.minutes_collected + stats.minutes_needed;
  const pct = Math.min(100, (stats.minutes_collected / Math.max(needed, 1)) * 100);

  return (
    <section className="border-b border-line py-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-[13px] font-medium">Building the first baseline</h2>
        <span className="num text-[12px] text-accent">{pct.toFixed(0)}%</span>
        <span className="num ml-auto text-[11px] text-faint">
          {durationFromMinutes(stats.minutes_collected)} of{" "}
          {durationFromMinutes(needed)}
        </span>
      </div>

      <p className="mt-1.5 max-w-[65ch] text-[12px] leading-relaxed text-dim">
        Every horizon scores a bucket against the buckets before it, so the
        shortest one still needs an hour of history. About{" "}
        {durationFromMinutes(stats.minutes_needed)} to go; the deeper horizons
        fill in behind it and score this same history retroactively.
      </p>

      <div className="mt-3 h-[3px] w-full bg-line">
        <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </section>
  );
}
