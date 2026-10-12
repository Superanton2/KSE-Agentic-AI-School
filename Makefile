# «Встигну?» — one entry point. `make help` lists the targets.
# Laptop: setup/test/demo need uv. Server: up/model/snapshot need only docker, make, git, curl (python runs in the image).
SHELL := /bin/bash
.DEFAULT_GOAL := help

export AIRALERT_UID ?= $(shell id -u)
export AIRALERT_GID ?= $(shell id -g)
# on the server there is no .git (rsync): `make deploy` leaves the commit in .code_sha
export AIRALERT_CODE_SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null || cat .code_sha 2>/dev/null || echo unknown)
export AIRALERT_PORT ?= 8000

PORT ?= $(AIRALERT_PORT)
OPEN ?= 1
DEMO_AT ?= 2026-10-07T11:30:00Z
DEMO_ALERT_AT ?= 2026-10-07T13:45:00Z
COMPOSE := docker compose --profile serve
TOOLS := docker compose --profile tools run --rm -T tools
FALLBACK := data/work/replay/latest/model_final.pkl
VADIMKIN := data/raw/vadimkin
VADIMKIN_URL := https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset.git
DIR ?= /opt/airalert
SESSION ?= $(HOME)/.config/airalert/airalert.session
DATE := $(shell date +%Y-%m-%d)

.PHONY: help setup test demo demo-alert login up down logs ps health model model-fallback dataset snapshot cron \
	deploy migrate

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

dataset: $(VADIMKIN)/datasets/volunteer_data_en.csv  ## Vadimkin CSV (labels before 2026-08-26) for the nightly refit
$(VADIMKIN)/datasets/volunteer_data_en.csv:
	rm -rf $(VADIMKIN) && git clone -q --depth 1 $(VADIMKIN_URL) $(VADIMKIN)

model-fallback: $(FALLBACK)  ## model from the committed data (the API uses it until the nightly refit made one)
$(FALLBACK):
	mkdir -p data/work/replay
	$(COMPOSE) build -q collector
	$(TOOLS) model-fit --until latest --out /app/data/work/replay/latest

up:  ## collector, sitrep, api, nightly in Docker; waits until the API answers
	@test -f .env || { echo "no .env: cp .env.example .env and fill TG_*"; exit 1; }
	@test -f $(SESSION) || { echo "no Telegram session $(SESSION): make login (or make migrate from the laptop)"; exit 1; }
	mkdir -p data/live data/work/replay data/raw
	$(MAKE) dataset
	@test -f data/processed/model_final.pkl || $(MAKE) model-fallback
	$(COMPOSE) up -d --build collector sitrep api nightly
	@$(MAKE) --no-print-directory health

health:  ## wait for /api/health (≤ 5 min) and print it
	@echo "waiting for the API on 127.0.0.1:$(PORT)…"; for i in $$(seq 1 60); do \
	  curl -sf http://127.0.0.1:$(PORT)/api/health >/dev/null && { curl -s http://127.0.0.1:$(PORT)/api/health; echo; \
	  exit 0; }; sleep 5; done; echo "API not up after 5 min"; $(COMPOSE) ps; exit 1

down:  ## stop everything
	$(COMPOSE) down

logs:  ## follow the logs
	$(COMPOSE) logs -f --tail=100

ps:  ## container status + health
	$(COMPOSE) ps

model:  ## refit now from the live DB: snapshot inside the collector -> grid -> ensemble -> model_card.json
	$(MAKE) dataset
	docker compose exec -T collector airalert db-snapshot --db alerts
	$(TOOLS) model-features
	$(TOOLS) model-fit --no-rebuild

snapshot:  ## consistent copies of all live DBs into data/work/backup/<date>/, keeps 7 days
	mkdir -p data/work/backup/$(DATE)
	for db in alerts drones sitrep; do \
	  docker compose exec -T collector airalert db-snapshot --db $$db --out /app/data/live/snapshots/backup-$$db.sqlite && \
	  mv data/live/snapshots/backup-$$db.sqlite data/work/backup/$(DATE)/$$db.sqlite || exit 1; done
	find data/work/backup -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

cron:  ## install the nightly backup (03:30) into this user's crontab, idempotent
	( crontab -l 2>/dev/null | grep -v 'airalert-backup' ; \
	  echo "30 3 * * * cd $(CURDIR) && make snapshot >> data/work/backup.log 2>&1 # airalert-backup" ) | crontab -
	crontab -l | grep airalert-backup

RSYNC_EXCLUDES := --exclude .git --exclude .venv --exclude 'data/live/' --exclude 'data/work/' --exclude 'data/raw/' \
	--exclude .env --exclude '*.session' --exclude '*.session-journal' --exclude .claude --exclude .idea \
	--exclude node_modules --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache --exclude .hypothesis \
	--exclude .DS_Store
# the nightly refit owns these on the server: copied once, never overwritten
NIGHTLY_FILES := data/processed/model_final.pkl data/processed/model_card.json data/processed/model_grid.parquet

deploy:  ## rsync the code to HOST:DIR (never data/live, data/work, .env, sessions, nightly model) and make up there
	@test -n "$(HOST)" || { echo "usage: make deploy HOST=user@host DIR=/opt/airalert"; exit 1; }
	@git diff --quiet HEAD || echo "warning: uncommitted changes are deployed too"
	git rev-parse --short HEAD > .code_sha
	ssh $(HOST) "mkdir -p $(DIR)"
	rsync -az --delete $(RSYNC_EXCLUDES) $(addprefix --exclude ,$(NIGHTLY_FILES)) ./ $(HOST):$(DIR)/
	rsync -az --ignore-existing --relative $(filter-out data/processed/model_final.pkl,$(NIGHTLY_FILES)) $(HOST):$(DIR)/
	rm -f .code_sha
	ssh $(HOST) "cd $(DIR) && make up"

migrate:  ## move the live collector from this laptop to HOST: stop here, copy data/live + .env + session, deploy
	@test -n "$(HOST)" || { echo "usage: make migrate HOST=user@host DIR=/opt/airalert"; exit 1; }
	@test -f .env && test -f $(SESSION) || { echo "need .env and $(SESSION) here"; exit 1; }
	@echo "One Telegram session must run in ONE place: stopping the local stack."
	$(COMPOSE) stop
	ssh $(HOST) "mkdir -p $(DIR)/data/live && mkdir -p -m 700 ~/.config/airalert"
	rsync -az --exclude 'snapshots/' data/live/ $(HOST):$(DIR)/data/live/
	rsync -az --chmod=F600 .env $(HOST):$(DIR)/.env
	rsync -az --chmod=F600 $(SESSION) $(HOST):.config/airalert/airalert.session
	$(MAKE) deploy HOST=$(HOST) DIR=$(DIR)
	@echo "Moved. Do not start the collector on this laptop again (make down here is safe)."
