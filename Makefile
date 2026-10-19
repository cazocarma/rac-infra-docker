.DEFAULT_GOAL := help
ENV ?= dev
ifneq ($(words $(ENV)),1)
$(error ENV debe ser dev, qa o prd)
endif
ifeq ($(filter $(ENV),dev qa prd),)
$(error ENV debe ser dev, qa o prd)
endif
ENV_FILE ?= envs/.env.$(ENV)
COMPOSE_FILES := -f compose.yaml
UP_FLAGS := --no-build
ifeq ($(ENV),dev)
UP_FLAGS := --build
else
COMPOSE_FILES += -f compose.release.yaml
endif
COMPOSE_FILES += -f docker-compose.$(ENV).yaml
COMPOSE_FILES += -f compose.observability.yaml -f compose.tests.yaml
COMPOSE := docker compose --env-file $(ENV_FILE) -p rac-$(ENV) $(COMPOSE_FILES)
CHECK_URL ?= http://localhost$(if $(filter qa,$(ENV)),:8080,$(if $(filter prd,$(ENV)),:8088,))
CURL := curl --fail --silent --show-error --max-time 15 --retry 5 --retry-all-errors --retry-delay 2

.PHONY: help up stop down build pull restart ps logs config check migrate migration-info migration-validate identity-config observe test test-go test-flutter test-integration
help:
	@echo RAC: ENV=dev por defecto. Entornos permitidos: dev, qa, prd.
	@echo make up / stop / down / ps / logs / config / check
	@echo make logs SERVICE=backend-match
	@echo make ENV=qa config
	@echo make ENV=prd ENV_FILE=envs/.env.prd config
	@echo QA y PRD requieren secretos e imagenes publicadas; no se construyen localmente.
	@echo make migrate / migration-info / migration-validate / identity-config / observe
	@echo make test / test-go / test-flutter / test-integration
config:
	$(COMPOSE) config --quiet
up: config
	$(COMPOSE) up -d $(UP_FLAGS)
ifeq ($(ENV),dev)
	$(COMPOSE) run --rm --build identity-config
endif
migrate: config
	$(COMPOSE) run --rm migrate
migration-info:
	$(COMPOSE) run --rm migrate info
migration-validate:
	$(COMPOSE) run --rm migrate validate
identity-config:
	$(COMPOSE) run --rm --build identity-config
observe: config
	$(COMPOSE) --profile observability up -d prometheus loki grafana docker-socket-proxy alloy
test: test-go test-flutter test-integration
test-go:
	$(COMPOSE) run --rm --build test-go
test-flutter:
	$(COMPOSE) run --rm test-flutter
test-integration:
ifeq ($(ENV),dev)
	$(COMPOSE) run --rm --build test-integration
else
	$(error Las pruebas con datos demo solo se permiten en DEV)
endif
stop:
	$(COMPOSE) --profile observability stop
down:
	$(COMPOSE) --profile observability down
build:
ifeq ($(ENV),dev)
	$(COMPOSE) build
else
	$(error build solo esta disponible para dev; promover imagenes a QA y PRD)
endif
pull: config
	$(COMPOSE) pull
restart:
	$(COMPOSE) restart
ps:
	$(COMPOSE) ps
logs:
	$(COMPOSE) logs --tail 100 -f $(SERVICE)
check:
	$(CURL) --head $(CHECK_URL)/
	$(CURL) $(CHECK_URL)/api/auth/health
	$(CURL) $(CHECK_URL)/api/user/health
	$(CURL) $(CHECK_URL)/api/match/health
	$(CURL) $(CHECK_URL)/api/user/skills
