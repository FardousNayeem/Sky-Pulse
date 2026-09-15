"""Unit tests for the pure core. No database, no network, no FastAPI."""
import random
from pathlib import Path

import pytest

from app.core.detector import Bucket, DetectionConfig, Spike, find_spikes
from app.core.features import FEATURE_NAMES, persistence_label, spike_features
from app.core.horizons import HORIZONS, get_horizon
from app.core.logistic import LogisticModel, auc_score, train
from app.core.matcher import Topic, TopicMatcher
from app.core.terms import TopTerms, extract_terms
from app.core.novelty import distinctive_terms, top_links


def _matcher():
    return TopicMatcher([
        Topic("outage", ("outage", "is down")),
        Topic("ai", (" ai ", "chatgpt")),
    ])


def test_matches_phrase_on_word_boundary():
    assert _matcher().match("Reddit is down again") == ["outage"]


def test_does_not_match_inside_a_longer_word():
    # "downtown" must not trigger "is down"; "said" must not trigger " ai "
    assert _matcher().match("walking downtown, he said hello") == []


def test_padded_phrase_still_matches():
    assert "ai" in _matcher().match("the ai debate continues")


def test_multiple_topics_can_match_one_post():
    assert sorted(_matcher().match("chatgpt is down")) == ["ai", "outage"]


def _flat(n, hits, total=10_000):
    return [Bucket(start=i * 900, hits=hits, total=total, coverage=1.0) for i in range(n)]


def test_no_spike_on_flat_series():
    config = DetectionConfig(window=10, gap=1, z_threshold=4.0, min_hits=5)
    assert find_spikes(_flat(30, 20), config) == []


def test_detects_a_real_spike():
    config = DetectionConfig(window=10, gap=1, z_threshold=4.0, min_hits=5)
    buckets = _flat(30, 20)
    buckets[25] = Bucket(start=25 * 900, hits=400, total=10_000, coverage=1.0)
    spikes = find_spikes(buckets, config)
    assert len(spikes) == 1
    assert spikes[0].bucket_start == 25 * 900
    assert spikes[0].multiple > 15


def test_small_counts_are_ignored_even_when_relatively_huge():
    """2 -> 9 posts is a 4.5x jump but must not page anyone."""
    config = DetectionConfig(window=10, gap=1, z_threshold=4.0, min_hits=25)
    buckets = _flat(30, 2)
    buckets[25] = Bucket(start=25 * 900, hits=9, total=10_000, coverage=1.0)
    assert find_spikes(buckets, config) == []


def test_low_coverage_buckets_are_excluded():
    """Collector downtime must not read as a dip or a spike."""
    config = DetectionConfig(window=10, gap=1, z_threshold=4.0, min_hits=5)
    buckets = _flat(30, 20)
    buckets[25] = Bucket(start=25 * 900, hits=400, total=10_000, coverage=0.2)
    assert find_spikes(buckets, config) == []


def test_share_not_raw_count():
    """Network-wide surge lifts every raw count; share stays flat, so no alert."""
    config = DetectionConfig(window=10, gap=1, z_threshold=4.0, min_hits=5)
    buckets = _flat(30, 20)
    buckets[25] = Bucket(start=25 * 900, hits=200, total=100_000, coverage=1.0)
    assert find_spikes(buckets, config) == []


def test_distinctive_terms_surface_the_new_subject():
    inside = ["stadium roof collapsed", "roof collapsed during the match"] * 3
    outside = ["great match tonight", "good game", "what a match"] * 20
    assert "collapsed" in distinctive_terms(inside, outside)


def test_apostrophe_is_not_a_word_boundary():
    """French \"j'ai\" must not match the standalone token \"ai\"."""
    matcher = TopicMatcher([Topic("ai", ("ai",))])
    assert matcher.match("J'ai bien aime ce film") == []
    assert matcher.match("j’ai une regle stricte") == []


def test_bare_token_still_matches_with_punctuation():
    matcher = TopicMatcher([Topic("ai", ("ai",))])
    assert matcher.match("everything is about AI.") == ["ai"]
    assert matcher.match("the (AI) hype") == ["ai"]
    assert matcher.match("AI, again") == ["ai"]


def test_bare_token_does_not_match_inside_a_word():
    matcher = TopicMatcher([Topic("ai", ("ai",))])
    assert matcher.match("she said aimlessly") == []
    assert matcher.match("a pair of chairs") == []


def test_language_scoped_topic_ignores_other_languages():
    matcher = TopicMatcher([Topic("ai", ("ai",), langs=("en",))])
    assert matcher.match("Ai amg kkkkkk te entendo", lang="pt") == []
    assert matcher.match("all about AI now", lang="en") == ["ai"]


def test_language_scoped_topic_still_matches_untagged_posts():
    """~a third of the firehose has no lang tag; excluding it would lose real hits."""
    matcher = TopicMatcher([Topic("ai", ("ai",), langs=("en",))])
    assert matcher.match("all about AI now", lang=None) == ["ai"]


def test_unscoped_topic_matches_any_language():
    matcher = TopicMatcher([Topic("earthquake", ("earthquake",))])
    assert matcher.match("earthquake now", lang="ja") == ["earthquake"]


# --------------------------------------------------------------- sigma floor

def test_zero_baseline_does_not_produce_an_absurd_zscore():
    """A silent topic that wakes up must not outrank every real spike.

    MAD is zero when every baseline bucket holds no hits, which is the normal
    state of a sparse topic. Dividing by an epsilon there returned z-scores in
    the hundreds of thousands; the Poisson floor keeps them readable.
    """
    config = DetectionConfig(window=10, gap=1, z_threshold=4.0, min_hits=5)
    buckets = _flat(30, 0)
    buckets[25] = Bucket(start=25 * 900, hits=8, total=10_000, coverage=1.0)
    spikes = find_spikes(buckets, config)
    assert len(spikes) == 1
    assert spikes[0].zscore < 100


def test_a_bigger_jump_off_a_flat_baseline_still_scores_higher():
    """The floor must preserve ordering, not flatten everything to one number."""
    config = DetectionConfig(window=10, gap=1, z_threshold=4.0, min_hits=5)
    small, big = _flat(30, 0), _flat(30, 0)
    small[25] = Bucket(start=25 * 900, hits=8, total=10_000, coverage=1.0)
    big[25] = Bucket(start=25 * 900, hits=80, total=10_000, coverage=1.0)
    assert find_spikes(big, config)[0].zscore > find_spikes(small, config)[0].zscore


def test_noise_floor_scales_with_the_size_of_the_window():
    """The same share is better evidence when measured over more posts."""
    config = DetectionConfig(window=10, gap=1, z_threshold=1.0, min_hits=1)
    thin = [Bucket(i * 900, 0, 1_000, 1.0) for i in range(30)]
    thick = [Bucket(i * 900, 0, 100_000, 1.0) for i in range(30)]
    thin[25] = Bucket(25 * 900, 5, 1_000, 1.0)
    thick[25] = Bucket(25 * 900, 500, 100_000, 1.0)
    assert find_spikes(thick, config)[0].zscore > find_spikes(thin, config)[0].zscore


# ------------------------------------------------------------------ horizons

def test_every_horizon_warmup_matches_the_formula():
    for horizon in HORIZONS.values():
        expected = (horizon.window + horizon.gap + 1) * horizon.bucket_minutes
        assert horizon.warmup_minutes == expected


def test_horizons_land_on_the_advertised_hours():
    """1h, 4h and 9h are the product promise, so they are asserted, not assumed."""
    assert HORIZONS["fast"].warmup_minutes == 60
    assert HORIZONS["mid"].warmup_minutes == 240
    assert HORIZONS["deep"].warmup_minutes == 540


def test_shorter_horizons_take_more_shots_so_they_demand_more_evidence():
    """More buckets means more chances to clear the bar by luck."""
    assert HORIZONS["fast"].z_threshold >= HORIZONS["deep"].z_threshold


def test_horizon_builds_a_matching_detection_config():
    horizon = HORIZONS["fast"]
    config = horizon.config(min_coverage=0.8)
    assert config.window == horizon.window
    assert config.z_threshold == horizon.z_threshold
    assert config.min_buckets * horizon.bucket_minutes == horizon.warmup_minutes


def test_unknown_horizon_is_rejected_by_name():
    with pytest.raises(ValueError, match="unknown horizon"):
        get_horizon("hourly")


# --------------------------------------------------------------------- terms

def test_bare_hostnames_do_not_become_terms():
    """Bluesky renders links without a scheme, so stripping http:// is not enough.

    Left alone, "com", "www" and "org" are the heaviest terms in the feed.
    """
    terms = extract_terms("story at mesonet.agron.iastate.edu/p.php?pid=1 about flooding")
    assert "com" not in terms and "www" not in terms
    assert "mesonet" not in terms
    assert "flooding" in terms


def test_urls_and_mentions_are_not_terms():
    terms = extract_terms("look https://example.com/a-very-long-story @someone.bsky.social quake")
    assert "quake" in terms
    assert not any(t.startswith("http") for t in terms)
    assert "someone" not in terms


def test_calendar_and_function_words_are_excluded():
    terms = extract_terms("Sep 12 Friday que die und i'm sure about the eruption")
    singles = {t for t in terms if " " not in t}
    assert "eruption" in singles
    for junk in ("sep", "friday", "que", "die", "und", "i'm"):
        assert junk not in singles


def test_bigrams_survive_when_only_one_half_carries_content():
    """"lady gaga" is a subject; "lady" and "gaga" alone are noise."""
    terms = extract_terms("lady gaga announced it")
    assert "lady gaga" in terms


def test_hashtags_are_terms_from_text_and_from_the_tags_field():
    terms = extract_terms("power cut again #outage", ("Blackout",))
    assert "#outage" in terms
    assert "#blackout" in terms


def test_a_term_repeated_in_one_post_counts_once():
    """One person ranting is one post talking about it, not ten."""
    counter = TopTerms()
    counter.add(extract_terms("quake quake quake quake"), "did:a")
    assert counter.top(5)["quake"] == 1


def test_one_account_posting_repeatedly_cannot_manufacture_a_spike():
    counter = TopTerms()
    for _ in range(50):
        counter.add({"template"}, "did:bot")
    for i in range(5):
        counter.add({"earthquake"}, f"did:person{i}")
    top = counter.top(5)
    assert top["template"] == 1
    assert top["earthquake"] == 5


def test_counter_stays_bounded_and_keeps_the_heaviest():
    counter = TopTerms(capacity=50)
    for i in range(5_000):
        counter.add({f"rare{i}"})
    for _ in range(200):
        counter.add({"heavy"})
    assert len(counter) <= 100  # capacity, pruned at twice it
    assert "heavy" in counter.top(10)


def test_min_hits_filters_terms_only_one_person_used():
    counter = TopTerms()
    counter.add({"solo"}, "did:a")
    for i in range(4):
        counter.add({"shared"}, f"did:{i}")
    assert counter.top(10, min_hits=3) == {"shared": 4}


# --------------------------------------------------------------------- links

def test_the_most_shared_link_in_a_spike_is_surfaced():
    fields = ["https://news.example/story"] * 20 + ["https://other.example/x"]
    assert top_links(fields)[0] == "https://news.example/story"


def test_a_link_from_one_or_two_posts_is_not_the_reason_for_anything():
    fields = ["https://a.example/x"] + ["https://b.example/y"] * 200
    assert "https://a.example/x" not in top_links(fields)


def test_posts_without_links_do_not_break_the_explanation():
    assert top_links(["", "", ""]) == []


# ----------------------------------------------------------------- the model

def _learnable(n=300, seed=5):
    """Rows where two features carry the signal and a third is pure noise."""
    rng = random.Random(seed)
    rows, labels = [], []
    for _ in range(n):
        strength = rng.uniform(0, 1)
        noise = rng.uniform(0, 1)
        rows.append([strength * 40, strength * 500, noise])
        labels.append(1 if strength + rng.gauss(0, 0.1) > 0.5 else 0)
    return rows, labels


def test_the_model_learns_which_features_matter_and_which_do_not():
    rows, labels = _learnable()
    model = train(rows, labels, ["zscore", "hits", "noise"])
    weights = dict(zip(model.feature_names, model.weights))
    assert abs(weights["noise"]) < abs(weights["zscore"])
    assert model.auc > 0.85


def test_a_model_that_cannot_separate_anything_scores_like_a_coin():
    rng = random.Random(1)
    rows = [[rng.uniform(0, 1), rng.uniform(0, 1)] for _ in range(300)]
    labels = [rng.randint(0, 1) for _ in range(300)]
    model = train(rows, labels, ["a", "b"])
    assert 0.4 < model.auc < 0.65


def test_predictions_are_probabilities():
    rows, labels = _learnable()
    model = train(rows, labels, ["zscore", "hits", "noise"])
    assert all(0.0 <= model.predict(r) <= 1.0 for r in rows)


def test_the_minority_class_is_not_simply_ignored():
    """Without class weighting the cheapest way to cut the loss is to answer
    "no" forever, which scores well on accuracy and is useless."""
    labels = [1 if i < 40 else 0 for i in range(400)]
    rows = [[40.0, 500.0, 0.5] if labels[i] else [4.0, 20.0, 0.5] for i in range(400)]
    model = train(rows, labels, ["zscore", "hits", "noise"])
    assert any(model.predict(r) >= 0.5 for r, y in zip(rows, labels) if y == 1)


def test_a_model_survives_a_round_trip_through_disk(tmp_path):
    rows, labels = _learnable()
    model = train(rows, labels, ["zscore", "hits", "noise"])
    path = tmp_path / "model.json"
    model.save(path)
    loaded = LogisticModel.load(path)
    assert loaded is not None
    assert loaded.predict(rows[0]) == pytest.approx(model.predict(rows[0]))


def test_a_missing_model_file_is_not_an_error():
    """No model is the normal state until enough history exists."""
    assert LogisticModel.load(Path("/nonexistent/model.json")) is None


def test_auc_rewards_ranking_not_thresholds():
    assert auc_score([0, 0, 1, 1], [0.1, 0.2, 0.3, 0.4]) == 1.0
    assert auc_score([0, 0, 1, 1], [0.4, 0.3, 0.2, 0.1]) == 0.0
    assert auc_score([0, 1], [0.5, 0.5]) == 0.5


def test_a_spike_that_holds_is_labelled_differently_from_one_that_reverts():
    flat = [Bucket(i * 240, 2, 50_000, 1.0) for i in range(40)]
    spike = Spike(bucket_start=20 * 240, hits=400, total=50_000, share=0.008,
                  baseline=0.00004, zscore=30.0, coverage=1.0)

    reverts = list(flat)
    assert persistence_label(spike, reverts, 20) == 0

    holds = list(flat)
    for i in (21, 22, 23):
        holds[i] = Bucket(i * 240, 380, 50_000, 1.0)
    assert persistence_label(spike, holds, 20) == 1


def test_a_spike_too_recent_to_judge_is_not_training_data():
    """Labelling it would mean guessing, and a guessed label is worse than none."""
    flat = [Bucket(i * 240, 2, 50_000, 1.0) for i in range(40)]
    spike = Spike(bucket_start=39 * 240, hits=400, total=50_000, share=0.008,
                  baseline=0.00004, zscore=30.0, coverage=1.0)
    assert persistence_label(spike, flat, 39) is None


def test_features_never_read_a_bucket_later_than_the_spike():
    """A feature that peeks at the future trains a model that cannot be run."""
    buckets = [Bucket(i * 240, 5, 50_000, 1.0) for i in range(40)]
    spike = Spike(bucket_start=20 * 240, hits=300, total=50_000, share=0.006,
                  baseline=0.0001, zscore=22.0, coverage=1.0)
    before = spike_features(spike, buckets, 20, 4, "term", "harbour bridge", ["traffic"], [])

    altered = list(buckets)
    for i in range(21, 40):
        altered[i] = Bucket(i * 240, 99_999, 50_000, 1.0)
    after = spike_features(spike, altered, 20, 4, "term", "harbour bridge", ["traffic"], [])
    assert before == after


def test_every_feature_has_a_name():
    buckets = [Bucket(i * 240, 5, 50_000, 1.0) for i in range(40)]
    spike = Spike(20 * 240, 300, 50_000, 0.006, 0.0001, 22.0, 1.0)
    row = spike_features(spike, buckets, 20, 4, "term", "x", [], [])
    assert len(row) == len(FEATURE_NAMES)


# ---------------------------------------------------------------- trend poll

def test_a_broken_trend_response_is_a_warning_not_a_crash():
    """Observed live: a truncated response raises http.client.IncompleteRead,
    which is an HTTPException rather than an OSError, so the obvious handler
    misses it and a routine network hiccup surfaces as a traceback."""
    import http.client
    import urllib.request

    from app.ingest import trends

    def explode(request, timeout=None):
        raise http.client.IncompleteRead(b"half", 400)

    original = urllib.request.urlopen
    urllib.request.urlopen = explode
    try:
        assert trends.fetch_trends("https://example.invalid/x", 5, 0) == []
    finally:
        urllib.request.urlopen = original


def test_an_unreachable_host_returns_no_trends():
    from app.ingest import trends
    assert trends.fetch_trends("https://nonexistent.invalid/xrpc", 5, 0) == []
