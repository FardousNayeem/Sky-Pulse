# Setup

Works on Windows, macOS and Linux. Nothing here costs money to run.

## Prerequisites

| | Minimum | Check with |
|---|---|---|
| Python | 3.11 | `python --version` |
| Node.js | 20 | `node --version` |

On Windows, install Python from [python.org](https://python.org) and tick
**"Add python.exe to PATH"** during setup. Node from [nodejs.org](https://nodejs.org).

---

## 1. Backend

<details open>
<summary><b>Windows</b> (PowerShell)</summary>

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

If you would rather activate the environment first:

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell blocks that with a script-execution error, allow it for this
window only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Calling `.venv\Scripts\python.exe` directly avoids the issue entirely.
</details>

<details open>
<summary><b>macOS / Linux</b></summary>

```bash
cd sky-pulse/backend
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements-dev.txt
```
</details>

Confirm it works:

```
pytest tests/ -q          # expect: 16 passed
```
(prefix with `.venv\Scripts\python.exe -m` or `./.venv/bin/python -m` if you did not activate)

## 2. Frontend

```bash
cd frontend
npm install
```

Same command on every platform.

---

## Running

Three processes. The collector is the only one that must stay running.

### Terminal 1 - collector

Streams the firehose into SQLite. Stop and start it freely; it saves a cursor
and resumes where it left off.

```powershell
# Windows
cd backend
.venv\Scripts\python.exe run_collector.py
```
```bash
# macOS / Linux
cd backend
./.venv/bin/python run_collector.py
```

### Terminal 2 - API

```powershell
# Windows
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```
```bash
# macOS / Linux
cd backend
./.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Interactive API docs: <http://localhost:8000/docs>

### Terminal 3 - dashboard

```bash
cd frontend
npm run dev
```

Open <http://localhost:3000>.

> **Shortcut on macOS/Linux:** `make collect`, `make api`, `make web`,
> `make detect`, `make train` and `make test` from the project root do the same
> thing. `make` is not available on Windows by default, so use the commands
> above.

---

## First run: what to expect

The dashboard shows **Building the first baseline** with a progress bar for the
first hour. This is normal and it is not an error.

A spike only means something measured against normal, so detection waits until
it has a trailing window of history. How long depends on the horizon, and three
run at once:

| horizon | ready after | finds |
|---|---|---|
| `fast` | **1 hour** | flash spikes, breaking news |
| `mid` | **4 hours** | developing stories |
| `deep` | **9 hours** | slow builds, over the steadiest baseline |

The collector scores everything it has once a minute, so alerts appear on their
own. The horizon strip at the top of the dashboard filters between them and
shows how long the unfinished ones have left.

Scoring is retroactive: each pass reads history back out of SQLite, so a
horizon that unlocks later still scores everything collected before it did.
Collection time is never wasted.

To score right now without waiting for the next pass:

```bash
curl -X POST "localhost:8000/api/detect"           # every ready horizon
curl -X POST "localhost:8000/api/detect?mode=fast" # just one
curl "localhost:8000/api/horizons"                 # what is ready, what is not
```

Or against a database you already have, with nothing else running:

```bash
cd backend
./.venv/bin/python run_detect.py             # score and print
./.venv/bin/python run_detect.py --list      # readiness only
./.venv/bin/python run_detect.py --kind term # only terms found in the stream
```

## Stories

The dashboard leads with **Stories**: terms that spiked together in the same
posts, grouped into the thing that actually happened, chained across windows,
each carrying the post that said it first.

A story dimmed and marked *seen before* has run previously with nearly the same
wording — a nightly show, a recurring fixture. It is flagged rather than hidden.

```bash
curl "localhost:8000/api/events?mode=fast"      # stories, newest first
curl -X POST "localhost:8000/api/events/rebuild" # regroup now
```

The collector regroups after every detection pass, so this happens on its own.

### Why a story sometimes has no first post

Every story carries the earliest post that did not resemble anything already
being said. When every post in the window looks like the chatter before it, the
spike is a continuation rather than a beginning — the earliest post is still
shown, with a novelty of 0 to say so.

## Two kinds of alert

`watchlist` alerts come from `backend/topics.json`. `discovered` alerts come
from terms the collector pulled out of the stream itself — these are the ones
that can surface a name nobody configured. The **Source** tabs on the dashboard
filter between them.

## Confidence

Once enough history exists, sky-pulse fits a model on whether past spikes held
or reverted, and each alert gets a **% holds** figure. Sort by *most likely
real* on the dashboard to use it.

```bash
cd backend
./.venv/bin/python run_train.py --dry-run   # how many labels exist
./.venv/bin/python run_train.py             # fit and save
```

Or `make train`. It needs 150 labelled spikes with at least 20 of each
outcome, and refuses with a reason below that. Every spike becomes a label
three buckets after it happens, so this fills in on its own while the collector
runs. Retrain whenever you like; the API and collector pick up a new model
without restarting.

What it predicts, how it is scored and where it falls down:
**[MODEL_CARD.md](MODEL_CARD.md)**.

## Is it any good?

The dashboard's **vs Bluesky trends** page scores this detector against
Bluesky's own trending list, which is public and needs no key. The number that
matters is lead time: how many minutes before the platform listed the same
story. It fills in as the collector runs.

---

## Configuration

Optional. Every setting has a working default; see `backend/.env.example`
for the full list. To override, create `backend/.env`:

```
PULSE_DETECT_SECONDS=60        # how often the collector scores; 0 disables
PULSE_TERMS_ENABLED=true       # discover terms from the stream
PULSE_SAMPLE_RATE=0.08         # fraction of posts kept to explain term spikes
PULSE_TRENDS_ENABLED=true      # poll Bluesky's trending list as ground truth
```

Bucket size, baseline length, z-threshold and the min-hits floor are **not**
environment settings. They are per-horizon and live in
`backend/app/core/horizons.py`, because warm-up is derived from them — one
global value would fix the tool at a single answer speed, which is the thing
horizons exist to avoid.

Topics live in `backend/topics.json`. Restart the collector after editing.

The dashboard reads the API at `http://localhost:8000` by default. To point it
elsewhere, create `frontend/.env.local`:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Troubleshooting

**Dashboard says "API not reachable"**
The FastAPI process is not running, or it is on a different port. Check
<http://localhost:8000/health> returns `{"status":"ok"}`.

**Dashboard says Ingest: stopped**
The collector is not running. Note this reads a wall-clock heartbeat, so a
collector that is merely catching up after a reconnect still shows *live*, with
the delay reported as lag underneath.

**Linux: `next dev` fails with "OS file watch limit reached"**
Your inotify watch limit is too low for Next.js.

```bash
sudo sysctl fs.inotify.max_user_watches=524288
```

To persist it across reboots, add `fs.inotify.max_user_watches=524288` to
`/etc/sysctl.conf`. Or skip the dev server and use `npm run build && npm run start`.

**Port already in use**
Pass a different port: `--port 8001` for the API, `npm run dev -- -p 3001` for
the dashboard. If you move the API, update `NEXT_PUBLIC_API_URL`.

**Windows: "running scripts is disabled on this system"**
PowerShell's execution policy is blocking venv activation. Either run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, or skip
activation and call `.venv\Scripts\python.exe` directly.

**Database is getting large**
Stored post text is pruned to a rolling window; counts are kept forever and are
tiny. To prune now:

```
python run_collector.py --prune
```
