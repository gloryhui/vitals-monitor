PYTHON ?= python3
PYTHONPATH := backend/src

.PHONY: help test lint format run dev-web build-web deploy

help:
	@echo "make test       run backend tests"
	@echo "make lint       ruff check"
	@echo "make format     ruff format"
	@echo "make run        run the backend from source"
	@echo "make dev-web    vite dev server (proxies /api to :8790)"
	@echo "make build-web  build the frontend into ./index.html and ./assets"
	@echo "make deploy     build the frontend and restart vitals.service"

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s backend/tests -v

lint:
	ruff check backend

format:
	ruff format backend

run:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m vitals

dev-web:
	cd web && npm run dev

build-web:
	cd web && npm install && npm run build

deploy: build-web
	sudo systemctl restart vitals
	@sleep 1
	curl -fsS http://127.0.0.1:8790/api/health && echo
