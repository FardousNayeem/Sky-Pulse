import {
  Broadcast,
  ChatCircleDots,
  Clock,
  Database,
  Hash,
  Newspaper,
  WarningDiamond,
} from "@phosphor-icons/react/dist/ssr";

import type { CorpusStats } from "@/lib/types";
import { compactNumber, durationFromMinutes, lagLabel } from "@/lib/format";

const ICON = { size: 14, weight: "regular" } as const;

function Readout({
  icon,
  label,
  value,
  sub,
  tone = "ink",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  tone?: "ink" | "accent" | "faint";
}) {
  const color = tone === "accent" ? "text-accent" : tone === "faint" ? "text-faint" : "text-ink";
  return (
    <div className="flex flex-col gap-1 px-4 py-3 first:pl-0">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-faint">
        {icon}
        {label}
      </div>
      <div className={`num text-[19px] leading-none ${color}`}>{value}</div>
      {sub && <div className="num text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

export default function StatsBar({ stats }: { stats: CorpusStats }) {
  return (
    <div className="flex flex-wrap divide-x divide-line border-b border-line">
      <Readout
        icon={<Broadcast {...ICON} />}
        label="Ingest"
        value={stats.collecting ? "live" : "stopped"}
        sub={
          stats.collecting && stats.lag_seconds !== null && stats.lag_seconds > 90
            ? lagLabel(stats.lag_seconds)
            : undefined
        }
        tone={stats.collecting ? "accent" : "faint"}
      />
      <Readout
        icon={<Clock {...ICON} />}
        label="Collected"
        value={durationFromMinutes(stats.minutes_collected)}
      />
      <Readout
        icon={<Database {...ICON} />}
        label="Posts scanned"
        value={compactNumber(stats.posts_scanned)}
      />
      <Readout
        icon={<ChatCircleDots {...ICON} />}
        label="Matches"
        value={compactNumber(stats.matches_stored)}
      />
      <Readout
        icon={<Hash {...ICON} />}
        label="Terms found"
        value={compactNumber(stats.terms_tracked)}
        sub={stats.trends_tracked ? `${stats.trends_tracked} Bluesky Trends` : undefined}
      />
      <Readout
        icon={<Newspaper {...ICON} />}
        label="Stories"
        value={String(stats.events_found)}
        tone={stats.events_found > 0 ? "accent" : "faint"}
      />
      <Readout
        icon={<WarningDiamond {...ICON} />}
        label="Alerts"
        value={String(stats.alerts)}
        tone={stats.alerts > 0 ? "accent" : "faint"}
      />
    </div>
  );
}
