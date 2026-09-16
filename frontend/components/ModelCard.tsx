import type { ModelInfo } from "@/lib/types";

/**
 * What the confidence model is, and how well it does.
 *
 * Shown with its holdout score rather than its training score. A model
 * evaluated on the rows it was fitted to always looks better than it is, and
 * quoting that number would be the same mistake as trusting a spike measured
 * against its own baseline.
 */
export default function ModelCard({ model }: { model: ModelInfo | null }) {
  if (!model) {
    return (
      <section className="border-b border-line py-4">
        <h2 className="text-[13px] font-medium">No confidence model yet</h2>
        <p className="mt-1.5 max-w-[68ch] text-[12px] leading-relaxed text-dim">
          Every past spike becomes a training example once three buckets have
          passed after it, because by then it is visible whether it held or
          reverted. Keep collecting, then run{" "}
          <code className="font-mono text-ink">make train</code>.
        </p>
      </section>
    );
  }

  const holdout =
    model.holdout_auc === null ? null : (model.holdout_auc * 100).toFixed(0);

  return (
    <section className="border-b border-line py-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-[13px] font-medium">Confidence model</h2>
        <span className="num text-[12px] text-accent">
          {holdout === null ? "unmeasured" : `${holdout}% AUC`}
        </span>
        <span className="num ml-auto text-[11px] text-faint">
          {model.trained_on} spikes · {model.positives} held
        </span>
      </div>

      <p className="mt-1.5 max-w-[68ch] text-[12px] leading-relaxed text-dim">
        Trained on whether past spikes held or reverted, scored on{" "}
        {model.holdout_size} later ones it never saw. It predicts persistence,
        which is a proxy for importance rather than importance itself — but it
        is the property that decides whether an alert was worth showing you.
      </p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {model.top_factors.map(([name, weight]) => (
          <span
            key={name}
            title={weight > 0 ? "higher makes it more likely to hold" : "higher makes it more likely to revert"}
            className="rounded-inst border border-line px-1.5 py-0.5 font-mono text-[11px] text-dim"
          >
            {name}
            <span className={`num ml-1 ${weight > 0 ? "text-accent" : "text-faint"}`}>
              {weight > 0 ? "+" : ""}
              {weight.toFixed(2)}
            </span>
          </span>
        ))}
      </div>
    </section>
  );
}
