import Link from "next/link";

/**
 * Order alerts by recency or by learned confidence.
 *
 * Only offered once a model exists. Sorting by a column that is null for every
 * row is not a choice, it is a broken control.
 */
export default function SortTabs({
  sort,
  mode,
  kind,
}: {
  sort?: string;
  mode?: string;
  kind?: string;
}) {
  const options = [
    { key: "", label: "newest" },
    { key: "confidence", label: "most likely real" },
  ];

  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] uppercase tracking-wider text-faint">Order</span>
      {options.map(({ key, label }) => {
        const selected = (sort ?? "") === key;
        const query = new URLSearchParams();
        if (key) query.set("sort", key);
        if (mode) query.set("mode", mode);
        if (kind) query.set("kind", kind);
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
