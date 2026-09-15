import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";

import SectionHeading from "@/components/SectionHeading";
import { getBenchmark } from "@/lib/api";
import { compactNumber, dateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

function Readout({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3 first:pl-0">
      <div className="text-[11px] uppercase tracking-wider text-faint">{label}</div>
      <div className="num text-[19px] leading-none">{value}</div>
      {sub && <div className="num text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

export default async function BenchmarkPage() {
  const report = await getBenchmark();

  return (
    <main className="pb-16">
      <div className="flex h-10 items-center">
        <Link
          href="/"
          className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-faint transition-colors hover:text-accent"
        >
          <ArrowLeft size={12} weight="regular" />
          Overview
        </Link>
      </div>

      <div className="border-b border-line pb-4">
        <h1 className="text-[22px] font-medium tracking-tight">Against Bluesky&apos;s own trends</h1>
        <p className="mt-1.5 max-w-[68ch] text-[13px] leading-relaxed text-dim">
          Bluesky publishes what it considers trending, free and without a key.
          That makes it the one available answer to whether any of this is real.
          The measure that matters is <strong className="text-ink">lead time</strong>:
          minutes between Sky Pulse raising a spike and the platform listing the
          same story. Positive means ahead.
        </p>
      </div>

      {!report ? (
        <p className="py-6 text-[13px] text-dim">
          No benchmark available. The API must be running for this page to load.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap divide-x divide-line border-b border-line">
            <Readout label="Trends tracked" value={String(report.trends_tracked)} />
            <Readout
              label="Found"
              value={String(report.matched)}
              sub={`${(report.coverage * 100).toFixed(0)}% of them`}
            />
            <Readout
              label="Median lead"
              value={
                report.median_lead_minutes === null
                  ? "-"
                  : `${report.median_lead_minutes.toFixed(0)}m`
              }
            />
            <Readout
              label="Best lead"
              value={report.best_lead_minutes === null ? "-" : `${report.best_lead_minutes}m`}
            />
          </div>

          {report.trends_tracked === 0 && (
            <p className="max-w-[68ch] py-4 text-[13px] leading-relaxed text-dim">
              No trends collected yet. The collector polls Bluesky every few
              minutes while it runs, leave it going and this fills in.
            </p>
          )}

          <SectionHeading count={report.rows.length}>Trends</SectionHeading>
          <div className="border-t border-line">
            {report.rows.map((row) => (
              <div
                key={row.topic}
                className="flex items-stretch gap-3 border-b border-line"
              >
                <span
                  className={`w-[3px] shrink-0 ${row.matched ? "bg-sev-med" : "bg-line"}`}
                  aria-hidden
                />
                <div className="flex min-w-0 flex-1 flex-col gap-1 py-3 pr-3">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="text-[13px] font-medium">{row.display_name}</span>
                    {row.lead_minutes !== null && (
                      <span
                        className={`num text-[15px] ${
                          row.lead_minutes > 0 ? "text-accent" : "text-dim"
                        }`}
                      >
                        {row.lead_minutes > 0
                          ? `${row.lead_minutes}m ahead`
                          : `${Math.abs(row.lead_minutes)}m behind`}
                      </span>
                    )}
                    <span className="num ml-auto text-[11px] text-faint">
                      {compactNumber(row.post_count)} posts
                    </span>
                  </div>

                  <div className="text-[12px] text-dim">
                    {row.matched ? (
                      <>
                        found as{" "}
                        <Link
                          href={`/${row.alert_kind === "term" ? "terms" : "topics"}/${encodeURIComponent(
                            row.alert_subject ?? "",
                          )}`}
                          className="font-mono text-ink hover:text-accent"
                        >
                          {row.alert_subject}
                        </Link>{" "}
                        <span className="text-faint">
                          ({row.alert_kind}, {row.alert_mode}, matched on {row.match_basis})
                        </span>
                      </>
                    ) : (
                      <span className="text-faint">Not Detected</span>
                    )}
                  </div>

                  <div className="num text-[11px] text-faint">
                    {row.category || "uncategorised"} · {row.status} · first seen{" "}
                    {dateTime(row.first_seen)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
