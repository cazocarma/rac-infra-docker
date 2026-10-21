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
ifneq ($(ENV),dev)
COMPOSE_FILES += -f compose.release.yaml
endif
COMPOSE_FILES += -f docker-compose.$(ENV).yaml
COMPOSE_FILES += -f compose.observability.yaml -f compose.tests.yaml
ifeq ($(ENV),dev)
ifneq ($(wildcard envs/.env.photos-s3),)
COMPOSE_FILES += -f compose.photos-s3.yaml
endif
endif
COMPOSE_ENV := --env-file $(ENV_FILE)
ifeq ($(ENV),dev)
ifneq ($(wildcard envs/.env.backups),)
COMPOSE_ENV += --env-file envs/.env.backups
COMPOSE_FILES += -f compose.backups.yaml
endif
endif
COMPOSE := docker compose $(COMPOSE_ENV) -p rac-$(ENV) $(COMPOSE_FILES)
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
	@echo make storage-up / storage-activate / storage-test / storage-test-persistence / storage-stop
	@echo make backup-enable / backup-now / backup-status / backup-restore-test
config:
	$(COMPOSE) config --quiet
up: config
ifeq ($(ENV),dev)
	$(PYTHON) scripts/build_dev.py $(COMPOSE)
endif
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
	$(PYTHON) scripts/build_dev.py $(COMPOSE)
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
	$(CURL) $(CHECK_URL)/api/chat/health
	$(CURL) $(CHECK_URL)/api/alert/health
	$(CURL) $(CHECK_URL)/api/user/skills
	$(COMPOSE) exec -T booking-events-relay wget -q -T 5 -O /dev/null http://localhost:8080/ready
	$(COMPOSE) exec -T alert-events-consumer wget -q -T 5 -O /dev/null http://localhost:8080/ready

# Laboratorio independiente: nunca usa secretos ni volúmenes de QA/PRD.
STORAGE_COMPOSE := docker compose --env-file envs/.env.storage -p rac-dev-storage -f compose.storage.yaml
.PHONY: storage-up storage-test storage-stop storage-logs storage-test-persistence
storage-up:
ifeq ($(wildcard envs/.env.storage),)
	$(PYTHON) scripts/init_storage.py
endif
	$(STORAGE_COMPOSE) up -d --wait --wait-timeout 180 rustfs
storage-test: storage-up
	$(STORAGE_COMPOSE) run --rm --build storage-test
storage-stop:
	$(STORAGE_COMPOSE) stop
storage-logs:
	$(STORAGE_COMPOSE) logs --tail 100 rustfs
storage-test-persistence: storage-test
	$(STORAGE_COMPOSE) run --rm -e STORAGE_TEST_PHASE=seed storage-test
	$(STORAGE_COMPOSE) up -d --force-recreate --wait --wait-timeout 180 rustfs
	$(STORAGE_COMPOSE) run --rm -e STORAGE_TEST_PHASE=verify storage-test

.PHONY: storage-activate
storage-activate:
ifeq ($(ENV),dev)
	$(PYTHON) scripts/init_storage.py
	$(PYTHON) scripts/activate_storage.py
else
	$(error storage-activate solo disponible para DEV)
endif
PYTHON ?= python
ifeq ($(ENV),dev)
ifneq ($(wildcard envs/.env.photos-s3),)
up: storage-up
endif
endif

.PHONY: backup-enable backup-now backup-status backup-restore-test
backup-enable:
ifeq ($(ENV),dev)
	$(PYTHON) scripts/init_storage.py
	$(STORAGE_COMPOSE) run --rm --build storage-config
	$(PYTHON) scripts/init_backups.py
	$(MAKE) backup-now
	$(COMPOSE) --env-file envs/.env.backups -f compose.backups.yaml up -d --build --no-deps --wait --wait-timeout 240 backups
else
	$(error Backups automaticos solo configurados en DEV)
endif
backup-now:
ifeq ($(ENV),dev)
	$(COMPOSE) run --rm --build --no-deps backups once
else
	$(error Backups automaticos solo configurados en DEV)
endif
backup-status:
ifeq ($(ENV),dev)
	$(COMPOSE) exec -T backups cat /backups/status.json
else
	$(error Backups automaticos solo configurados en DEV)
endif
backup-restore-test:
ifeq ($(ENV),dev)
	$(PYTHON) scripts/test_backup_restore.py
else
	$(error Prueba de restauracion solo disponible para DEV)
endif
