export default function SectionHeading({
  children,
  count,
}: {
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <h2 className="flex items-baseline gap-2 pt-6 pb-2 text-[13px] font-medium">
      {children}
      {count !== undefined && count > 0 && (
        <span className="num text-[11px] text-faint">{count}</span>
      )}
    </h2>
  );
}
