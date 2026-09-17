import Link from "next/link";

import type { TopicSummary } from "@/lib/types";
import { compactNumber } from "@/lib/format";

export default function TopicGrid({ topics }: { topics: TopicSummary[] }) {
  const ordered = [...topics].sort((a, b) => b.total_hits - a.total_hits);
  const peak = ordered[0]?.total_hits || 1;

  return (
    <div className="grid grid-cols-1 gap-x-8 border-t border-line sm:grid-cols-2 lg:grid-cols-3">
      {ordered.map((topic) => (
        <Link
          key={topic.name}
          href={`/topics/${encodeURIComponent(topic.name)}`}
          className="group flex items-center gap-3 border-b border-line px-1 py-2.5 transition-colors hover:bg-sunk"
        >
          <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{topic.name}</span>

          {topic.langs.length > 0 && (
            <span className="shrink-0 font-mono text-[10px] uppercase text-faint">
              {topic.langs.join("/")}
            </span>
          )}

          {/* Bare proportion bar, no filled track: this is a relative reading,
              not a progress meter. */}
          <span className="hidden h-[3px] w-16 shrink-0 sm:block">
            <span
              className="block h-full bg-accent"
              style={{ width: `${Math.max(2, (topic.total_hits / peak) * 100)}%` }}
            />
          </span>

          <span className="num w-14 shrink-0 text-right text-[12px] text-dim">
            {compactNumber(topic.total_hits)}
          </span>
        </Link>
      ))}
    </div>
  );
}
