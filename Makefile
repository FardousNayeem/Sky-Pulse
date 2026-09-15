.PHONY: help install collect detect train api web test clean

help:
	@echo "sky-pulse"
	@echo "  make install   install backend and frontend dependencies"
	@echo "  make collect   stream the firehose into SQLite (run first, leave running)"
	@echo "  make detect    score history already collected, at every ready horizon"
	@echo "  make train     fit the confidence model from spikes that held or reverted"
	@echo "  make api       FastAPI on :8000"
	@echo "  make web       Next.js on :3000"
	@echo "  make test      run the core unit tests"
	@echo ""
	@echo "Windows has no make by default. See SETUP.md."

install:
	cd backend && python3 -m venv .venv && ./.venv/bin/pip install -q --upgrade pip \
		&& ./.venv/bin/pip install -q -r requirements-dev.txt
	cd frontend && npm install

collect:
	cd backend && ./.venv/bin/python run_collector.py

detect:
	cd backend && ./.venv/bin/python run_detect.py

train:
	cd backend && ./.venv/bin/python run_train.py

api:
	cd backend && ./.venv/bin/python -m uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

test:
	cd backend && ./.venv/bin/python -m pytest tests/ -q

clean:
	rm -rf backend/.venv frontend/node_modules frontend/.next
