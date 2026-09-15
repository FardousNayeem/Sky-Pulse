# Model card — sky-pulse confidence model

The one model in sky-pulse. Everything else in the project is counting and
descriptive statistics; this is the only component that is fitted to data.

---

## What it predicts

Given a spike that the detector has already found, the probability that it
**holds** rather than reverting to baseline within the next three buckets.

It does not predict importance, newsworthiness, or truth. It predicts
persistence. Those are related but not the same thing, and the distinction is
the most important line on this page.

## Why it exists

A z-score answers "how far from normal is this". That is not the question a
person reading an alert has, which is "is this worth my attention". The two
come apart routinely — on the validation corpus a single blip scored z = 106
with 306 posts and was gone by the next bucket — the model scores it 0.01.

Before this model, every decision boundary in the project was a hand-set
constant: roughly fifteen numbers picked by judgement. This replaces the most
consequential of them with a calibrated probability, and makes alerts
*rankable* instead of merely gated.

## Architecture

| | |
|---|---|
| Type | Binary logistic regression |
| Implementation | `backend/app/core/logistic.py`, plain Python |
| Dependencies | none — no numpy, no scikit-learn, nothing in `requirements.txt` |
| Parameters | 16 weights + 1 bias |
| Optimiser | full-batch gradient descent, lr 0.3, 4000 epochs |
| Regularisation | L2, λ = 0.01 |
| Class balance | inverse-frequency instance weighting |
| Preprocessing | per-feature standardisation, stored with the model |
| Serialisation | JSON, `backend/data/model.json` |

Inference is one dot product per candidate spike per detection pass — not per
post. At default settings that is a few thousand multiplications a minute. The
project's zero-running-cost constraint is unaffected.

## Inputs

Sixteen features, all computable at the moment the spike is scored
(`backend/app/core/features.py`):

`log_hits`, `zscore` (capped at 50), `log_multiple`, `baseline_silent`,
`share_per_mille`, `coverage`, `is_term`, `is_multiword`, `is_hashtag`,
`n_terms`, `n_links`, `log_bucket_minutes`, `history_density`,
`log_window_posts`, `hour_sin`, `hour_cos`.

The z-score is capped because it is unbounded off a near-silent baseline and
would otherwise be the only feature with meaningful weight.

**No feature may read a bucket later than the spike.** A feature that peeks at
the future produces a model that evaluates beautifully and cannot be run live.
This is enforced by a test
(`test_features_never_read_a_bucket_later_than_the_spike`), which alters every
subsequent bucket and asserts the feature vector is unchanged.

## Labels

Self-supervised, from data already on disk. A spike is labelled **held** when
at least 2 of the following 3 buckets stay at ≥ 50% of the spike's excess over
its baseline; otherwise **reverted**.

A spike with fewer than 3 subsequent buckets is left **unlabelled** and
excluded from training. Guessing a label is worse than having none.

This is the design decision that made a model possible at all. Bluesky's
trending endpoint supplies real labels, but only as they accumulate over days.
Persistence labels exist the moment a spike is three buckets old, which means
the first model can be trained from history already collected.

## Training procedure

`python run_train.py` (or `make train`) walks every horizon and kind, re-runs
detection over stored history, and labels every spike old enough to judge.

Evaluation uses a **chronological** holdout: earliest 70% fits, latest 30%
scores. Not a random split — several spikes come from the same event, so a
random split puts siblings on both sides of the line and the resulting score
measures memorisation rather than generalisation.

The shipped model is then refitted on all rows. The holdout existed to produce
an honest number, not to be discarded.

Training refuses below **150 labelled spikes** with at least **20 of each
outcome**, and returns a reason. A model fitted on a handful of rows describes
those rows and nothing else; a model fitted on one class predicts that class
forever.

## Evaluation

Measured on a synthetic 12-hour corpus (720 minutes, 240 distinct terms, 45
sustained events and 45 blips with **deliberately overlapping magnitudes**, so
the classes cannot be separated by peak size alone):

| | |
|---|---|
| Labelled spikes | 768 (475 held, 293 reverted) |
| In-sample AUC | 0.806 |
| In-sample accuracy | 0.717 |
| **Chronological holdout AUC** | **0.771** on 231 later spikes |
| Mean confidence, planted events | 0.592 (n=624) |
| Mean confidence, planted blips | 0.271 (n=146) |

The small gap between in-sample and holdout is the signal worth reading: the
model generalises rather than memorising.

It also recovered a planted relationship without being told — `n_links` carried
a strong positive weight, matching the corpus in which real events carried
links and blips largely did not.

> **These numbers describe a synthetic corpus.** They validate that the
> pipeline learns, and nothing more. They are not a claim about performance on
> the live firehose, which has not yet been measured. Retrain on real history
> and read the holdout AUC that `run_train.py` prints.

## Known limitations

- **Persistence is a proxy.** A story can be brief and important; a bot can be
  persistent and worthless. The label is chosen because it is available and
  checkable, not because it is the ideal target.
- **Synthetic evaluation only**, as above.
- **Diurnal features may be spurious.** `hour_sin` / `hour_cos` carried weight
  on a 12-hour corpus, which is too short a window for a genuine daily cycle.
  Over real multi-day history this may be real signal or may shrink to nothing;
  L2 will handle it either way, but treat those weights sceptically for now.
- **Topic and term hits are not the same unit.** Term hits are distinct authors
  per minute; topic hits are posts per minute. The `is_term` flag lets the model
  compensate, but the underlying inconsistency is real and worth unifying.
- **It cannot rescue a spike the detector never found.** It re-ranks candidates;
  it does not generate them. Recall is still set by the horizon thresholds.
- **No per-subject personalisation.** One global model across all horizons,
  kinds and subjects.
- **It scores terms, not stories.** Events inherit the highest confidence among
  their member terms. A story-level model would need story-level labels, which
  only exist once events have been running long enough to be judged.

## Ethical and operational notes

- Trained only on aggregate counts and a sampled corpus of public Bluesky
  posts. No profile data, no follower graph, no private content.
- Author identifiers are used transiently for per-minute deduplication and are
  reduced to hashes; no per-author model or score is built or stored.
- The model influences ordering and a displayed percentage. It gates nothing —
  an alert below any confidence is still listed and still reachable.
- Absence of a model is a supported state. Every alert simply carries a null
  confidence and the rest of the system is unchanged.

## Maintenance

Retrain whenever there is meaningfully more history. The collector and API
reload `model.json` on mtime, so a new model takes effect without restarting
ingest.

When enough confirmed trends have accumulated via `/api/benchmark`, the same
pipeline can be retrained against *those* labels instead — the features,
optimiser, holdout policy and serving path are unchanged. Only the label
function moves.
