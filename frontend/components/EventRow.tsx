import { ArrowsClockwise, LinkSimple, Quotes } from "@phosphor-icons/react/dist/ssr";

import type { PulseEvent } from "@/lib/types";
import { dateTime, linkLabel, relativeTime } from "@/lib/format";

/**
 * One story, not the three words that gave it away.
 *
 * The first post leads, because it is the only thing here that answers the
 * question a person actually arrived with. The terms are demoted to evidence.
 */
export default function EventRow({ event }: { event: PulseEvent }) {
  const repeat = Boolean(event.recurs_from);
  const minutes = Math.max(1, Math.round((event.last_bucket - event.first_bucket) / 60));

  return (
    <article
      className={`flex items-stretch gap-3 border-b border-line ${repeat ? "opacity-60" : ""}`}
    >
      <span
        className={`w-[3px] shrink-0 ${repeat ? "bg-line" : "bg-sev-med"}`}
        aria-hidden
      />

      <div className="flex min-w-0 flex-1 flex-col gap-2 py-3 pr-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-mono text-[13px] font-medium">
            {event.terms.slice(0, 3).join(" · ")}
          </span>
          {event.terms.length > 3 && (
            <span className="num text-[11px] text-faint">+{event.terms.length - 3} more</span>
          )}
          {event.confidence !== null && (
            <span
              className={`num rounded-inst px-1.5 py-0.5 text-[11px] ${
                event.confidence >= 0.6 ? "bg-accent-soft text-accent" : "text-dim"
              }`}
            >
              {(event.confidence * 100).toFixed(0)}% holds
            </span>
          )}
          <span className="num text-[11px] text-faint">z {event.zscore.toFixed(0)}</span>
          <span className="rounded-inst border border-line px-1 font-mono text-[10px] text-faint">
            {event.mode}
          </span>
          <span className="num ml-auto text-[11px] text-faint">
            {relativeTime(event.last_bucket)}
          </span>
        </div>

        {/* A story that has run before is not news the second time. Saying so
            is the difference between a feed worth reading and one worth muting. */}
        {repeat && (
          <div className="flex items-center gap-1.5 text-[11px] text-faint">
            <ArrowsClockwise size={11} weight="regular" />
            seen before — {((event.recurrence ?? 0) * 100).toFixed(0)}% the same wording as an
            earlier run
          </div>
        )}

        {event.story_text && (
          <a
            href={event.story_url ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="group/story flex gap-2 border-l-2 border-line pl-2.5 hover:border-accent"
          >
            <Quotes size={12} weight="fill" className="mt-1 shrink-0 text-faint" />
            <span className="min-w-0">
              <span className="block text-[12px] leading-relaxed text-ink group-hover/story:text-accent">
                {event.story_text}
              </span>
              <span className="num mt-0.5 block text-[11px] text-faint">
                first said {event.story_ts ? dateTime(event.story_ts) : "—"}
                {event.story_novelty !== null &&
                  ` · ${(event.story_novelty * 100).toFixed(0)}% unlike anything before it`}
              </span>
            </span>
          </a>
        )}

        <div className="text-[12px] text-dim">
          <span className="num text-ink">{event.hits}</span> posts over{" "}
          <span className="num">{minutes}m</span> and{" "}
          <span className="num">{event.buckets}</span> window
          {event.buckets === 1 ? "" : "s"}
        </div>

        {event.links.length > 0 && (
          <div className="flex flex-col gap-0.5">
            {event.links.map((url) => (
              <a
                key={url}
                href={url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="flex items-center gap-1.5 text-[11px] text-dim hover:text-accent"
              >
                <LinkSimple size={11} weight="regular" className="shrink-0" />
                <span className="truncate font-mono">{linkLabel(url)}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
