"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { ArrowsClockwise } from "@phosphor-icons/react";

import { runDetection } from "@/lib/api";

/**
 * Score what has already been collected, right now.
 *
 * The collector scores on a timer, so this is not the only path to an alert -
 * but it is the only one when the API is running against a database nobody is
 * collecting into any more, which is exactly what happens when you open an
 * archive and want to know what is in it.
 */
export default function ScoreNow() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);

  async function score() {
    setBusy(true);
    const runs = await runDetection();
    setBusy(false);
    if (runs) startTransition(() => router.refresh());
  }

  const working = busy || pending;
  return (
    <button
      type="button"
      onClick={score}
      disabled={working}
      className="flex items-center gap-1.5 rounded-inst border border-line px-2 py-1 text-[11px] text-dim transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
    >
      <ArrowsClockwise size={11} weight="regular" className={working ? "animate-spin" : ""} />
      {working ? "Scoring" : "Score Now"}
    </button>
  );
}
