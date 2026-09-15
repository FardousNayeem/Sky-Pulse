/** Skeleton mirrors the real layout: a readout strip, then stacked rows. */
export default function Loading() {
  return (
    <div className="animate-pulse pb-16" aria-busy="true" aria-label="Loading">
      <div className="h-10" />
      <div className="flex divide-x divide-line border-b border-line">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex flex-1 flex-col gap-2 px-4 py-3 first:pl-0">
            <div className="h-2.5 w-16 bg-line" />
            <div className="h-4 w-12 bg-line" />
          </div>
        ))}
      </div>
      <div className="h-6" />
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex gap-3 border-b border-line py-3">
          <div className="w-[3px] bg-line" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-40 bg-line" />
            <div className="h-2.5 w-72 max-w-full bg-line" />
          </div>
        </div>
      ))}
    </div>
  );
}
