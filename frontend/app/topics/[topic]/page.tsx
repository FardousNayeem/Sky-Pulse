import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";

import AlertRow from "@/components/AlertRow";
import PostList from "@/components/PostList";
import SectionHeading from "@/components/SectionHeading";
import ShareChart from "@/components/ShareChart";
import { getAlerts, getPosts, getSeries } from "@/lib/api";
import { compactNumber, dateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ topic: string }>;
  searchParams: Promise<{ start?: string; bucket?: string }>;
}

export default async function TopicPage({ params, searchParams }: PageProps) {
  const { topic } = await params;
  const { start, bucket } = await searchParams;

  const bucketMinutes = Number(bucket) || 15;
  const series = await getSeries(topic, bucketMinutes, 200);
  if (!series) notFound();

  // ?start=<bucket> arrives from an alert row: scope posts to that window.
  const windowStart = start ? Number(start) : undefined;
  const window = windowStart
    ? { start: windowStart, end: windowStart + bucketMinutes * 60 }
    : undefined;

  const [alerts, posts] = await Promise.all([getAlerts(20, topic), getPosts(topic, 50, window)]);
  const totalHits = series.points.reduce((sum, point) => sum + point.hits, 0);

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
        <h1 className="font-mono text-[22px] font-medium tracking-tight">{topic}</h1>
        <span className="num text-[12px] text-dim">
          {compactNumber(totalHits)} posts across {series.points.length} buckets of{" "}
          {bucketMinutes}m
        </span>
      </div>

      <SectionHeading>Share of Conversation</SectionHeading>
      <ShareChart points={series.points} />

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
        {window ? `Posts from ${dateTime(window.start)}` : "Recent posts"}
      </SectionHeading>
      <PostList posts={posts ?? []} />
    </main>
  );
}
