"""Tests that need SQLite. Still no network and no FastAPI.

The pure core is covered in test_core.py; what is covered here is everything
that only goes wrong once a real database is involved - transactions,
migrations from older schemas, and the queries detection is built on.
"""
import random
import sqlite3
import time

import pytest

from app.config import Settings
from app.db.database import create_connection
from app.db.repositories import (
    EventsRepository,
    AlertsRepository,
    CountsRepository,
    MatchesRepository,
    SamplesRepository,
    TermsRepository,
    TrendsRepository,
)
from app.services.benchmark_service import BenchmarkService
from app.services.detection_service import DetectionService
from app.services.event_service import EventService
from app.services.training_service import TrainingService


class FakeSpike:
    def __init__(self, start, hits=100, zscore=9.0):
        self.bucket_start = start
        self.hits = hits
        self.total = 50_000
        self.share = hits / 50_000
        self.baseline = 0.0001
        self.zscore = zscore


@pytest.fixture
def db(tmp_path):
    connection = create_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def _settings(tmp_path, **overrides):
    return Settings(
        database_path=tmp_path / "test.db",
        model_path=tmp_path / "model.json",
        **overrides,
    )


# ---------------------------------------------------------------- persistence

def test_alerts_survive_the_process_that_wrote_them(tmp_path):
    """sqlite3 opens an implicit transaction and never commits it by itself.

    An INSERT outside an explicit `with` block is visible to the connection
    that wrote it and to nobody else, then rolled back when it closes. That is
    indistinguishable from working until something reads the file later.
    """
    path = tmp_path / "test.db"
    first = create_connection(path)
    AlertsRepository(first).save_all([("quake", "term", "fast", FakeSpike(600), ["jma"], [], None)])
    first.close()

    second = create_connection(path)
    assert second.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 1


def test_the_same_spike_is_not_alerted_twice(db):
    alerts = AlertsRepository(db)
    pending = [("quake", "term", "fast", FakeSpike(600), [], [], None)]
    assert alerts.save_all(pending) == 1
    assert alerts.save_all(pending) == 0


def test_one_bucket_can_alert_at_several_horizons_and_kinds(db):
    alerts = AlertsRepository(db)
    assert alerts.save_all([
        ("quake", "topic", "fast", FakeSpike(600), [], [], None),
        ("quake", "topic", "deep", FakeSpike(600), [], [], None),
        ("quake", "term", "fast", FakeSpike(600), [], [], None),
    ]) == 3


# ------------------------------------------------------------------ migration

LEGACY_V1 = """
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bucket INTEGER NOT NULL, topic TEXT NOT NULL,
    hits INTEGER NOT NULL, total INTEGER NOT NULL, share REAL NOT NULL,
    baseline REAL NOT NULL, zscore REAL NOT NULL, novelty TEXT,
    created_at INTEGER NOT NULL, UNIQUE(bucket, topic));
CREATE TABLE matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, topic TEXT NOT NULL,
    did TEXT NOT NULL, rkey TEXT NOT NULL, lang TEXT, text TEXT NOT NULL);
INSERT INTO alerts(bucket,topic,hits,total,share,baseline,zscore,novelty,created_at)
    VALUES(900,'earthquake',33,60000,0.00055,0.000065,5.0,'jma,japan',1700000000);
"""


def test_a_database_from_before_horizons_is_carried_forward(tmp_path):
    """The oldest shape: UNIQUE(bucket, topic), a `novelty` column, no mode."""
    path = tmp_path / "legacy.db"
    seed = sqlite3.connect(path)
    seed.executescript(LEGACY_V1)
    seed.commit()
    seed.close()

    db = create_connection(path)
    row = db.execute("SELECT * FROM alerts").fetchone()
    assert row["subject"] == "earthquake"      # topic -> subject
    assert row["terms"] == "jma,japan"         # novelty -> terms
    assert row["kind"] == "topic"
    assert row["mode"] == "deep"
    assert "links" in [c[1] for c in db.execute("PRAGMA table_info(matches)")]
    assert "confidence" in [c[1] for c in db.execute("PRAGMA table_info(alerts)")]
    db.close()


def test_migrating_twice_changes_nothing(tmp_path):
    path = tmp_path / "legacy.db"
    seed = sqlite3.connect(path)
    seed.executescript(LEGACY_V1)
    seed.commit()
    seed.close()

    create_connection(path).close()
    db = create_connection(path)
    assert db.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 1
    db.close()


# ------------------------------------------------------------------- contrast

def test_a_sustained_spike_is_not_contrasted_against_its_own_overflow(db):
    """An event running longer than one bucket spills either side of it.

    Contrasting a spike against its own tail finds nothing distinctive, because
    every word is equally common on both sides.
    """
    samples = SamplesRepository(db)
    spike_text = "bridge closed after the crash"
    normal_text = "crossing the bridge on my way home"
    rows = []
    for minute in range(120):
        ts = minute * 60
        text = spike_text if 60 <= minute < 75 else normal_text
        rows.append((ts, "did:a", f"r{minute}", "en", text, ""))
    samples.bulk_add(rows)
    db.commit()

    start, end = 62 * 60, 66 * 60
    without_guard = samples.outside("bridge", start, end, guard=0)
    with_guard = samples.outside("bridge", start, end, guard=3 * 4 * 60)
    assert spike_text in without_guard        # the tail leaks in
    assert spike_text not in with_guard       # the guard band keeps it out
    assert normal_text in with_guard


# ------------------------------------------------------------ term detection

def _plant_term_spike(db, minutes=180, spike_at=160, length=8):
    random.seed(11)
    counts, terms, samples = [], [], []
    for i in range(minutes):
        minute = i * 60
        counts.append((minute, 4000))
        terms.append((minute, "football", 40))
        in_spike = spike_at <= i < spike_at + length
        hits = 180 if in_spike else random.randint(0, 2)
        if hits:
            terms.append((minute, "harbour bridge", hits))
            text = ("harbour bridge closed after the crash"
                    if in_spike else "crossing the harbour bridge home")
            link = "https://news.example/closed" if in_spike else ""
            for n in range(12):
                samples.append((minute + n, f"did:{n}", f"r{i}-{n}", "en", text, link))
    CountsRepository(db).bulk_add(dict(counts), {})
    TermsRepository(db).bulk_add({(m, t): h for m, t, h in terms})
    SamplesRepository(db).bulk_add(samples)
    db.commit()


def _service(db, tmp_path):
    return DetectionService(
        CountsRepository(db), MatchesRepository(db), AlertsRepository(db),
        TermsRepository(db), SamplesRepository(db), _settings(tmp_path),
    )


def test_a_term_nobody_configured_is_found_and_explained(db, tmp_path):
    """The point of term discovery: no entry for this in topics.json."""
    _plant_term_spike(db)
    runs = [r for r in _service(db, tmp_path).run_all() if r.kind == "term" and r.ran]
    assert runs and sum(r.new_alerts for r in runs) > 0

    alerts = _service(db, tmp_path).list_alerts(kind="term")
    assert alerts
    found = alerts[0]
    assert found.subject == "harbour bridge"
    assert "https://news.example/closed" in found.links
    assert {"closed", "crash"} & set(found.terms)


def test_a_steady_term_never_alerts(db, tmp_path):
    _plant_term_spike(db)
    _service(db, tmp_path).run_all()
    assert _service(db, tmp_path).list_alerts(subject="football") == []


def test_candidates_exclude_terms_too_small_to_ever_clear_min_hits(db):
    TermsRepository(db).bulk_add({(60, "loud"): 500, (60, "whisper"): 1})
    db.commit()
    assert TermsRepository(db).candidates(since=0, min_total_hits=20, limit=100) == ["loud"]


# ------------------------------------------------------------------ benchmark

def _trend(db, topic, display, first_seen, description=""):
    TrendsRepository(db).upsert([
        (topic, display, description, "news", "hot", 500, first_seen, first_seen, first_seen)
    ])
    db.commit()


def test_lead_time_is_measured_against_when_bluesky_listed_it(db):
    now = int(time.time())
    _trend(db, "t1", "Farage donations reporting", now)
    AlertsRepository(db).save_all([
        ("farage donations", "term", "fast", FakeSpike(now - 23 * 60), ["reporting"], [], None),
    ])
    report = BenchmarkService(AlertsRepository(db), TrendsRepository(db)).report()
    assert report.matched == 1
    assert report.rows[0].lead_minutes == 23
    assert report.rows[0].match_basis == "subject"


def test_a_single_common_word_is_not_enough_to_claim_a_trend(db):
    """Measured against a real trending list, the bare word "users" matched
    three unrelated headlines. One word is a coincidence, not a detection."""
    now = int(time.time())
    _trend(db, "t1", "Users name non-LOTR characters", now, "Users joked about the ring.")
    AlertsRepository(db).save_all([("users", "term", "fast", FakeSpike(now - 600), [], [], None)])
    assert BenchmarkService(AlertsRepository(db), TrendsRepository(db)).report().matched == 0


def test_a_bare_word_corroborated_by_its_own_terms_does_count(db):
    now = int(time.time())
    _trend(db, "t1", "Farage donations reporting", now)
    AlertsRepository(db).save_all([
        ("farage", "term", "fast", FakeSpike(now - 600), ["donations", "reporting"], [], None),
    ])
    assert BenchmarkService(AlertsRepository(db), TrendsRepository(db)).report().matched == 1


def test_an_alert_from_last_week_did_not_predict_todays_trend(db):
    now = int(time.time())
    _trend(db, "t1", "Farage donations reporting", now)
    AlertsRepository(db).save_all([
        ("farage donations", "term", "fast", FakeSpike(now - 40 * 3600), [], [], None),
    ])
    assert BenchmarkService(AlertsRepository(db), TrendsRepository(db)).report().matched == 0


def test_the_earliest_matching_alert_is_the_one_that_counts(db):
    now = int(time.time())
    _trend(db, "t1", "Farage donations reporting", now)
    AlertsRepository(db).save_all([
        ("farage donations", "term", "fast", FakeSpike(now - 5 * 60), [], [], None),
        ("farage donations", "term", "deep", FakeSpike(now - 30 * 60), [], [], None),
    ])
    assert BenchmarkService(AlertsRepository(db), TrendsRepository(db)).report().rows[0].lead_minutes == 30


# ------------------------------------------------------------------ training

def test_training_refuses_on_thin_history_and_says_why(db, tmp_path):
    """Fitting on a handful of rows produces a model that describes those rows
    and nothing else. Refusing is the correct answer, with a reason."""
    _plant_term_spike(db)
    trainer = TrainingService(_service(db, tmp_path), _settings(tmp_path))
    report = trainer.fit()
    assert not report.trained
    assert "labelled spikes" in report.reason or "each outcome" in report.reason
    assert not (tmp_path / "model.json").exists()


def test_confidence_is_null_until_a_model_exists(db, tmp_path):
    _plant_term_spike(db)
    service = _service(db, tmp_path)
    service.run_all()
    alerts = service.list_alerts(kind="term")
    assert alerts
    assert all(a.confidence is None for a in alerts)


def test_alerts_can_be_ordered_by_confidence(db):
    alerts = AlertsRepository(db)
    alerts.save_all([
        ("low", "term", "fast", FakeSpike(600), [], [], 0.1),
        ("high", "term", "fast", FakeSpike(1200), [], [], 0.9),
        ("unscored", "term", "fast", FakeSpike(1800), [], [], None),
    ])
    ordered = [r["subject"] for r in alerts.list(sort="confidence")]
    # Unscored last: no model has judged it, which is not the same as judging
    # it unlikely.
    assert ordered == ["high", "low", "unscored"]


def test_an_unknown_sort_is_rejected(db, tmp_path):
    with pytest.raises(ValueError, match="unknown sort"):
        _service(db, tmp_path).list_alerts(sort="whatever")


# --------------------------------------------------------------------- events

DAY = 86_400


def _story(db, day, hour, terms, text, minutes=12, hits=200, post_ids=None):
    """Plant a story: several terms spiking together in the same posts."""
    base = day * DAY + hour * 3600
    term_rows, samples = [], []
    for m in range(minutes):
        minute = base + m * 60
        for term in terms:
            term_rows.append((minute, term, hits))
        for n in range(10):
            samples.append((minute + n, f"did:{post_ids or terms[0]}{n}",
                            f"rk{day}{hour}{m}{n}", "en", text, ""))
    TermsRepository(db).bulk_add({(m, t): h for m, t, h in term_rows})
    SamplesRepository(db).bulk_add(samples)


def _event_world(db):
    """Three days of quiet, with two stories and one repeat planted in it."""
    counts = {}
    quiet = {}
    for minute in range(0, 3 * DAY + 12 * 3600, 60):
        counts[minute] = 4000
        quiet[(minute, "weather")] = 30
    CountsRepository(db).bulk_add(counts, {})
    TermsRepository(db).bulk_add(quiet)
    SamplesRepository(db).bulk_add([
        (m, "did:bg", f"bg{m}", "en", "an ordinary afternoon nothing much happening", "")
        for m in range(0, 3 * DAY, 900)
    ])

    _story(db, 0, 5, ["harbour", "bridge closed", "#trafficchaos"],
           "harbour bridge closed after a crash emergency services #trafficchaos")
    _story(db, 1, 8, ["earthquake", "jma"],
           "strong earthquake felt across the region jma issues advisory",
           post_ids="q")
    # the same story again two days later: a repeat, not news
    _story(db, 2, 5, ["harbour", "bridge closed", "#trafficchaos"],
           "harbour bridge closed after a crash emergency services #trafficchaos",
           post_ids="r")
    db.commit()


def _events(db, tmp_path):
    return EventService(
        AlertsRepository(db), EventsRepository(db), SamplesRepository(db), _settings(tmp_path)
    )


def test_terms_that_spike_together_become_one_story(db, tmp_path):
    """Three words, one event. Reporting them separately makes the reader
    reassemble the story by eye, which is the job the tool exists to do."""
    _event_world(db)
    _service(db, tmp_path).run_all()
    _events(db, tmp_path).rebuild("fast")

    events = _events(db, tmp_path).list_events(limit=50, mode="fast")
    bridge = [e for e in events if "harbour" in e.terms]
    assert bridge, "the bridge story was not detected at all"
    assert set(bridge[0].terms) == {"harbour", "bridge closed", "#trafficchaos"}


def test_an_unrelated_story_is_a_separate_event(db, tmp_path):
    _event_world(db)
    _service(db, tmp_path).run_all()
    _events(db, tmp_path).rebuild("fast")

    events = _events(db, tmp_path).list_events(limit=50, mode="fast")
    quake = [e for e in events if "earthquake" in e.terms]
    assert quake
    assert "harbour" not in quake[0].terms


def test_a_story_running_over_several_windows_is_one_event(db, tmp_path):
    """Twelve minutes of spiking is three 4-minute buckets and one story."""
    _event_world(db)
    _service(db, tmp_path).run_all()
    _events(db, tmp_path).rebuild("fast")

    events = _events(db, tmp_path).list_events(limit=50, mode="fast")
    bridge = [e for e in events if "harbour" in e.terms][0]
    assert bridge.buckets > 1
    assert bridge.last_bucket > bridge.first_bucket


def test_an_event_carries_the_post_that_said_it_first(db, tmp_path):
    _event_world(db)
    _service(db, tmp_path).run_all()
    _events(db, tmp_path).rebuild("fast")

    bridge = [e for e in _events(db, tmp_path).list_events(limit=50, mode="fast")
              if "harbour" in e.terms][0]
    assert bridge.story_rkey
    assert "bridge closed" in (bridge.story_text or "")
    assert bridge.story_url and bridge.story_url.startswith("https://bsky.app/profile/")
    # Nothing like it was in the background, so it really was a first telling.
    assert bridge.story_novelty and bridge.story_novelty > 0.5


def test_the_same_story_two_days_later_is_flagged_as_a_repeat(db, tmp_path):
    """A show that airs nightly trends nightly. The second time is not news."""
    _event_world(db)
    _service(db, tmp_path).run_all()
    _events(db, tmp_path).rebuild("fast")

    events = sorted(
        [e for e in _events(db, tmp_path).list_events(limit=200, mode="fast")
         if "harbour" in e.terms],
        key=lambda e: e.first_bucket,
    )
    assert len(events) == 2, "the repeat should be its own event, not a continuation"
    assert events[0].recurs_from is None
    assert events[1].recurs_from == events[0].key
    assert events[1].recurrence and events[1].recurrence >= 0.6


def test_events_compress_the_alert_list(db, tmp_path):
    _event_world(db)
    service = _service(db, tmp_path)
    service.run_all()
    _events(db, tmp_path).rebuild("fast")

    alerts = service.list_alerts(limit=2000, mode="fast", kind="term")
    events = _events(db, tmp_path).list_events(limit=2000, mode="fast")
    assert len(events) < len(alerts)


def test_regrouping_twice_does_not_fail_or_duplicate(db, tmp_path):
    """The second pass reads back the events the first one wrote.

    The first rebuild of any database reads an empty events table, so anything
    it gets wrong about reading them back goes unnoticed until the pass after.
    """
    _event_world(db)
    _service(db, tmp_path).run_all()
    events = _events(db, tmp_path)

    events.rebuild("fast")
    first = len(events.list_events(limit=500, mode="fast"))
    events.rebuild("fast")
    assert len(events.list_events(limit=500, mode="fast")) == first
