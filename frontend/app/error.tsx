"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mt-10 max-w-[65ch] border-l-2 border-sev-high pl-4">
      <h2 className="text-[14px] font-medium">Something failed while rendering</h2>
      <p className="mt-1.5 text-[13px] leading-relaxed text-dim">
        This is usually the API going away mid-request. Check that the backend is
        still running, then retry.
      </p>
      <button
        onClick={reset}
        className="mt-3 rounded-inst border border-line-strong px-3 py-1.5 text-[12px] transition-colors hover:bg-sunk active:translate-y-[1px]"
      >
        Retry
      </button>
    </main>
  );
}
