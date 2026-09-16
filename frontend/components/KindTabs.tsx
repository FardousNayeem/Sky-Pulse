import Link from "next/link";

const KINDS = [
  { key: "", label: "all" },
  { key: "term", label: "discovered" },
  { key: "topic", label: "watchlist" },
] as const;

/**
 * Filter between the two ways a spike can be found.
 *
 * "watchlist" is topics.json - precise, and limited to what somebody thought
 * to write down in advance. "discovered" is terms taken from the stream
 * itself, which is the only way a name nobody predicted can show up at all.
 */
export default function KindTabs({ kind, mode }: { kind?: string; mode?: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] uppercase tracking-wider text-faint">Source</span>
      {KINDS.map(({ key, label }) => {
        const selected = (kind ?? "") === key;
        const query = new URLSearchParams();
        if (key) query.set("kind", key);
        if (mode) query.set("mode", mode);
        const href = query.toString() ? `/?${query}` : "/";
        return (
          <Link
            key={label}
            href={href}
            aria-current={selected ? "true" : undefined}
            className={`rounded-inst border px-2 py-1 font-mono text-[11px] transition-colors ${
              selected
                ? "border-accent bg-accent-soft text-accent"
                : "border-line text-dim hover:border-line-strong hover:text-ink"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </div>
  );
}
