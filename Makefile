.PHONY: setup db-up migrate lint test gate check sim-stats eval-regression eval-live eval-final dev chat
PYTHON ?= python
ARGS ?=

setup db-up migrate lint test check sim-stats eval-regression eval-live eval-final dev chat:
	$(PYTHON) scripts/tasks.py $@ $(ARGS)

gate:
	$(PYTHON) scripts/gate.py --phase $(PHASE)
