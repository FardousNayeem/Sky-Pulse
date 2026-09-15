import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";

import AlertRow from "@/components/AlertRow";
import PostList from "@/components/PostList";
import SectionHeading from "@/components/SectionHeading";
import ShareChart from "@/components/ShareChart";
import { getAlerts, getTermPosts, getTermSeries } from "@/lib/api";
import { compactNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ term: string }>;
  searchParams: Promise<{ start?: string; bucket?: string }>;
}

/**
 * Detail view for a term nobody configured.
 *
 * Mirrors the topic page, with one honest difference: the posts come from the
 * sample rather than the full stream, because there is no way to know in
 * advance which terms will matter and keeping every post is not affordable.
 */
export default async function TermPage({ params, searchParams }: PageProps) {
  const { term: raw } = await params;
  const term = decodeURIComponent(raw);
  const { start, bucket } = await searchParams;

  const bucketMinutes = Number(bucket) || 4;
  const series = await getTermSeries(term, bucketMinutes, 200);

  const windowStart = start ? Number(start) : undefined;
  const window = windowStart
    ? { start: windowStart, end: windowStart + bucketMinutes * 60 }
    : undefined;

  const [alerts, posts] = await Promise.all([
    getAlerts(20, term),
    getTermPosts(term, 50, window),
  ]);
  const totalHits = series?.points.reduce((sum, point) => sum + point.hits, 0) ?? 0;

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

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line pb-4">
        <h1 className="font-mono text-[22px] font-medium tracking-tight">{term}</h1>
        <span className="rounded-inst border border-line px-1.5 py-0.5 font-mono text-[10px] text-faint">
          discovered
        </span>
        <span className="num text-[12px] text-dim">
          {compactNumber(totalHits)} posts across {series?.points.length ?? 0} buckets of{" "}
          {bucketMinutes}m
        </span>
      </div>

      <SectionHeading>Share of Conversation</SectionHeading>
      {series && series.points.length > 0 ? (
        <ShareChart points={series.points} />
      ) : (
        <p className="max-w-[65ch] py-4 text-[13px] leading-relaxed text-dim">
          No counts stored for this term. Only the heaviest terms of each minute
          are kept, and terms age out faster than topic counters do.
        </p>
      )}

      {alerts && alerts.length > 0 && (
        <>
          <SectionHeading count={alerts.length}>Alerts</SectionHeading>
          <div className="border-t border-line">
            {alerts.map((alert) => (
              <AlertRow key={alert.id} alert={alert} bucketMinutes={bucketMinutes} />
            ))}
          </div>
        </>
      )}

      <SectionHeading count={posts?.length}>
        {window ? "Sampled posts from the spike" : "Recent sampled posts"}
      </SectionHeading>
      {posts && posts.length > 0 ? (
        <PostList posts={posts} />
      ) : (
        <p className="max-w-[65ch] py-4 text-[13px] leading-relaxed text-dim">
          No sampled posts survive for this window. The sample is kept for a few
          hours only, the counts above go back further.
        </p>
      )}
    </main>
  );
}
