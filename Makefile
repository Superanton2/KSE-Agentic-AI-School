# «Встигну?» — one entry point. `make help` lists the targets.
SHELL := /bin/bash
.DEFAULT_GOAL := help

export AIRALERT_UID ?= $(shell id -u)
export AIRALERT_GID ?= $(shell id -g)
export AIRALERT_CODE_SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)

PORT ?= 8000
OPEN ?= 1
DEMO_AT ?= 2026-10-07T11:30:00Z
DEMO_ALERT_AT ?= 2026-10-07T13:45:00Z
COMPOSE := docker compose --profile serve
FALLBACK := data/work/replay/latest/model_final.pkl
DIR ?= /opt/airalert
DATE := $(shell date +%Y-%m-%d)

.PHONY: help setup test demo demo-alert login up down logs ps model model-fallback snapshot deploy

help:  ## this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-15s %s\n", $$1, $$2}'

setup:  ## uv sync --frozen; checks node >= 20 (or deno) and docker
	uv sync --frozen
	@if command -v node >/dev/null; then \
	  v=$$(node -p 'process.versions.node.split(".")[0]'); [ $$v -ge 20 ] || { echo "node >= 20 needed (have $$v)"; exit 1; }; \
	  echo "node $$(node --version) ok"; \
	elif command -v deno >/dev/null; then echo "no node; web tests will run with deno"; \
	else echo "warning: neither node >= 20 nor deno: make test skips the web tests"; fi
	@command -v docker >/dev/null && echo "docker ok" || echo "warning: no docker (needed only for make up)"

test:  ## pytest + web unit tests (node --test, or deno test without node)
	uv run pytest -q
	@if command -v node >/dev/null; then node --test tests/web/*.test.mjs; \
	elif command -v deno >/dev/null; then deno test tests/web/; \
	else echo "skipped web tests: no node/deno"; fi

demo:  ## replay without Telegram (committed data, calm moment) on http://127.0.0.1:8000
	uv run airalert model-fit --until $(DEMO_AT)
	@[ "$(OPEN)" = 0 ] || (sleep 4; open http://127.0.0.1:$(PORT) 2>/dev/null || xdg-open http://127.0.0.1:$(PORT) 2>/dev/null || true) &
	uv run airalert serve --port $(PORT) --replay $(DEMO_AT)

demo-alert:  ## the same, during an air raid
	$(MAKE) demo DEMO_AT=$(DEMO_ALERT_AT)

login:  ## Telegram login (interactive); the session lives outside the repo
	uv run airalert tg-login

model-fallback: $(FALLBACK)  ## model from the committed data (used by the API when data/processed has none)
$(FALLBACK):
	uv run airalert model-fit --until latest --out data/work/replay/latest

up:  ## collector, sitrep, api, nightly in Docker; waits until healthy
	@test -f .env || { echo "no .env: cp .env.example .env and fill TG_*"; exit 1; }
	@test -f data/processed/model_final.pkl || $(MAKE) model-fallback
	mkdir -p data/live data/work/replay
	$(COMPOSE) up -d --build collector sitrep api nightly
	@echo "waiting for the API…"; for i in $$(seq 1 60); do \
	  curl -sf http://127.0.0.1:$(PORT)/api/health >/dev/null && { curl -s http://127.0.0.1:$(PORT)/api/health; echo; \
	  echo "http://127.0.0.1:$(PORT)"; exit 0; }; sleep 5; done; echo "API not up after 5 min"; $(COMPOSE) ps; exit 1

down:  ## stop everything
	$(COMPOSE) down

logs:  ## follow the logs
	$(COMPOSE) logs -f --tail=100

ps:  ## container status + health
	$(COMPOSE) ps

model:  ## refit from the live DB: snapshot inside the collector -> model-features -> model-fit
	docker compose exec collector airalert db-snapshot --db alerts
	@test -f data/raw/vadimkin/datasets/volunteer_data_en.csv || uv run airalert fetch-dataset
	uv run airalert model-features
	uv run airalert model-fit --no-rebuild

snapshot:  ## consistent copies of all live DBs into data/work/backup/<date>/
	mkdir -p data/work/backup/$(DATE)
	for db in alerts drones sitrep; do \
	  docker compose exec collector airalert db-snapshot --db $$db --out /app/data/live/snapshots/backup-$$db.sqlite && \
	  mv data/live/snapshots/backup-$$db.sqlite data/work/backup/$(DATE)/$$db.sqlite; done
	find data/work/backup -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

deploy:  ## rsync the code to HOST:DIR (no data/live, data/work, .env, sessions) and make up there
	@test -n "$(HOST)" || { echo "usage: make deploy HOST=user@host DIR=/opt/airalert"; exit 1; }
	rsync -az --delete --exclude .git --exclude .venv --exclude 'data/live/' --exclude 'data/work/' \
	  --exclude 'data/raw/' --exclude .env --exclude '*.session' --exclude '*.session-journal' --exclude .claude \
	  --exclude .idea --exclude 'data/processed/model_final.pkl' ./ $(HOST):$(DIR)/
	ssh $(HOST) "cd $(DIR) && make up"
