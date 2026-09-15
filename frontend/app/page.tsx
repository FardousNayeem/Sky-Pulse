import Link from "next/link";
import { PlugsConnected } from "@phosphor-icons/react/dist/ssr";

import AlertRow from "@/components/AlertRow";
import AutoRefresh from "@/components/AutoRefresh";
import CollectionProgress from "@/components/CollectionProgress";
import EventRow from "@/components/EventRow";
import HorizonBar from "@/components/HorizonBar";
import KindTabs from "@/components/KindTabs";
import ModelCard from "@/components/ModelCard";
import ScoreNow from "@/components/ScoreNow";
import SectionHeading from "@/components/SectionHeading";
import SortTabs from "@/components/SortTabs";
import StatsBar from "@/components/StatsBar";
import TopicGrid from "@/components/TopicGrid";
import { getAlerts, getEvents, getModel, getStats, getTopics } from "@/lib/api";
import type { HorizonStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

function BackendOffline() {
  return (
    <div className="mt-10 max-w-[65ch] border-l-2 border-sev-high pl-4">
      <h2 className="flex items-center gap-2 text-[14px] font-medium">
        <PlugsConnected size={15} weight="regular" className="text-sev-high" />
        API not reachable
      </h2>
      <p className="mt-1.5 text-[13px] leading-relaxed text-dim">
        The dashboard reads from the FastAPI service on port 8000. Start it with:
      </p>
      <pre className="mt-2 overflow-x-auto border border-line bg-sunk p-3 font-mono text-[12px] text-ink">
        cd backend{"\n"}./.venv/bin/python -m uvicorn app.main:app --port 8000
      </pre>
    </div>
  );
}

/** What to say when the list is empty, which depends on why it is empty. */
function emptyReason(active: HorizonStatus | undefined, ready: boolean): string {
  if (active && !active.ready) {
    return `The ${active.mode} horizon needs ${active.warmup_hours}h of collection before it can score anything. ${active.minutes_remaining} minutes to go.`;
  }
  if (!ready) {
    return "Detection starts once the first baseline is filled. Ingest is running in the meantime.";
  }
  return "Nothing unusual right now. Quiet is the expected reading, an empty list means the baseline is holding.";
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ mode?: string; kind?: string; sort?: string }>;
}) {
  const { mode, kind, sort } = await searchParams;
  const [stats, events, alerts, topics, model] = await Promise.all([
    getStats(),
    getEvents(25, mode),
    getAlerts(40, undefined, mode, kind, sort),
    getTopics(),
    getModel(),
  ]);

  if (!stats) return <BackendOffline />;

  const active = stats.horizons.find((h) => h.mode === mode);
  const byMode = new Map(stats.horizons.map((h) => [h.mode, h]));

  return (
    <main className="pb-16">
      <div className="flex h-10 items-center justify-between gap-3">
        <span className="text-[11px] uppercase tracking-wider text-faint">Overview</span>
        <div className="flex items-center gap-2">
          <Link
            href="/benchmark"
            className="rounded-inst border border-line px-2 py-1 text-[11px] text-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            Bluesky Trends Now
          </Link>
          <ScoreNow />
          <AutoRefresh seconds={30} />
        </div>
      </div>

      <StatsBar stats={stats} />

      <HorizonBar horizons={stats.horizons} active={active?.mode} />

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line py-3">
        <KindTabs kind={kind} mode={mode} />
        {model && <SortTabs sort={sort} mode={mode} kind={kind} />}
      </div>

      <ModelCard model={model} />

      {!stats.ready_for_detection && <CollectionProgress stats={stats} />}

      {/* Stories lead. An alert is a word that moved; a story is the thing
          that happened, which is what anyone actually came here for. */}
      <SectionHeading count={events?.length}>Stories</SectionHeading>
      {events && events.length > 0 ? (
        <div className="border-t border-line">
          {events.map((event) => (
            <EventRow key={`${event.mode}/${event.key}`} event={event} />
          ))}
        </div>
      ) : (
        <div className="border-t border-line py-4">
          <p className="max-w-[65ch] text-[13px] leading-relaxed text-dim">
            No stories yet. Terms that spike together in the same posts are
            grouped into one, so this fills in once discovery has something to
            group.
          </p>
        </div>
      )}

      <SectionHeading count={alerts?.length}>
        {active ? `Alerts · ${active.mode}` : "Alerts"}
      </SectionHeading>
      {alerts && alerts.length > 0 ? (
        <div className="border-t border-line">
          {alerts.map((alert) => {
            const horizon = byMode.get(alert.mode);
            return (
              <AlertRow
                key={alert.id}
                alert={alert}
                threshold={horizon?.z_threshold}
                bucketMinutes={horizon?.bucket_minutes}
              />
            );
          })}
        </div>
      ) : (
        <div className="border-t border-line py-4">
          <p className="max-w-[65ch] text-[13px] leading-relaxed text-dim">
            {emptyReason(active, stats.ready_for_detection)}
          </p>
        </div>
      )}

      <SectionHeading count={topics?.length}>Watchlist topics</SectionHeading>
      {topics && <TopicGrid topics={topics} />}
    </main>
  );
}
