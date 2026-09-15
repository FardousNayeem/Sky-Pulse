import Link from "next/link";
import { ArrowRight, LinkSimple } from "@phosphor-icons/react/dist/ssr";

import type { Alert } from "@/lib/types";
import { dateTime, linkLabel, percent, relativeTime, severity } from "@/lib/format";

const BAR = {
  high: "bg-sev-high",
  medium: "bg-sev-med",
  low: "bg-line-strong",
} as const;

const VALUE = {
  high: "text-sev-high",
  medium: "text-sev-med",
  low: "text-ink",
} as const;

export default function AlertRow({
  alert,
  threshold,
  bucketMinutes,
}: {
  alert: Alert;
  /** The z-threshold of the horizon that raised it, for relative severity. */
  threshold?: number;
  /** Bucket size of that horizon, so the detail view opens the right window. */
  bucketMinutes?: number;
}) {
  const tone = severity(alert.zscore, threshold);
  // A term and a topic are counted differently and live behind different
  // endpoints, so they lead to different detail views.
  const base = alert.kind === "term" ? "/terms" : "/topics";
  const query = new URLSearchParams({ start: String(alert.bucket) });
  if (bucketMinutes) query.set("bucket", String(bucketMinutes));
  const href = `${base}/${encodeURIComponent(alert.subject)}?${query}`;

  return (
    <div className="group flex items-stretch gap-3 border-b border-line transition-colors hover:bg-sunk">
      {/* Severity is real state, so it earns a visual channel. */}
      <span className={`w-[3px] shrink-0 ${BAR[tone]}`} aria-hidden />

      <div className="flex min-w-0 flex-1 flex-col gap-1.5 py-3 pr-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <Link href={href} className="font-mono text-[13px] font-medium hover:text-accent">
            {alert.subject}
          </Link>
          <span className={`num text-[15px] ${VALUE[tone]}`}>
            {/* A zero baseline has no multiple to report. The subject was
                silent, which is a stronger statement than any number. */}
            {alert.baseline <= 0
              ? "new"
              : alert.multiple >= 100
                ? "100x+"
                : `${alert.multiple.toFixed(1)}x`}
          </span>
          <span className="num text-[11px] text-faint">z {alert.zscore.toFixed(1)}</span>
          {/* The z-score says how far from normal. Confidence says whether it
              will hold, which is the question a person actually has. They
              disagree often enough to be worth showing side by side. */}
          {alert.confidence !== null && (
            <span
              title="Learned probability this spike holds rather than reverting"
              className={`num rounded-inst px-1.5 py-0.5 text-[11px] ${
                alert.confidence >= 0.6
                  ? "bg-accent-soft text-accent"
                  : alert.confidence >= 0.35
                    ? "text-dim"
                    : "text-faint"
              }`}
            >
              {(alert.confidence * 100).toFixed(0)}% holds
            </span>
          )}
          <span className="rounded-inst border border-line px-1 font-mono text-[10px] text-faint">
            {alert.kind}
          </span>
          <span className="rounded-inst border border-line px-1 font-mono text-[10px] text-faint">
            {alert.mode}
          </span>
          <span className="num ml-auto text-[11px] text-faint">{relativeTime(alert.bucket)}</span>
        </div>

        <div className="text-[12px] text-dim">
          <span className="num text-ink">{alert.hits}</span> posts at{" "}
          <span className="num">{percent(alert.share)}</span> of conversation, against a{" "}
          <span className="num">{alert.baseline > 0 ? percent(alert.baseline) : "silent"}</span>{" "}
          baseline
        </div>

        {alert.terms.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {alert.terms.map((term) => (
              <span
                key={term}
                className="rounded-inst bg-accent-soft px-1.5 py-0.5 font-mono text-[11px] text-accent"
              >
                {term}
              </span>
            ))}
          </div>
        )}

        {/* The most-shared link in a spike is usually the story itself, so it
            is the one thing here worth leaving the dashboard for. */}
        {alert.links.length > 0 && (
          <div className="flex flex-col gap-0.5">
            {alert.links.map((url) => (
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

        <div className="num text-[11px] text-faint">{dateTime(alert.bucket)}</div>
      </div>

      <Link href={href} aria-label={`Open ${alert.subject}`} className="flex items-start">
        <ArrowRight
          size={14}
          weight="regular"
          className="mr-3 mt-3.5 shrink-0 text-faint opacity-0 transition-opacity group-hover:opacity-100"
        />
      </Link>
    </div>
  );
}
