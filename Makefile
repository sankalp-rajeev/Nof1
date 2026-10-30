.PHONY: setup db-up migrate lint test gate check sim-stats eval-regression eval-live eval-final dev
PYTHON ?= python

setup db-up migrate lint test check sim-stats eval-regression eval-live eval-final dev:
	$(PYTHON) scripts/tasks.py $@

gate:
	$(PYTHON) scripts/gate.py --phase $(PHASE)
