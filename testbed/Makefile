.PHONY: env sw sw_build sw_run sw_config check_one_link check_all_links sequential_start concurrent_start plot_throughput gen_trace_from_host gen_trace_from_connection sync_trace analysis_fct
SHELL := /bin/bash

ARTIFACT_ROOT := $(shell git rev-parse --show-toplevel)
TESTBED_ROOT := $(CURDIR)
PYTHONPATH := $(TESTBED_ROOT)/utils
ENV_GEN_FILE := .env

ENV_CMD = set -a && source $(ENV_GEN_FILE) && set +a &&

env:
	echo "ARTIFACT_ROOT=$(ARTIFACT_ROOT)" > $(ENV_GEN_FILE)
	echo "TESTBED_ROOT=$(TESTBED_ROOT)" >> $(ENV_GEN_FILE)
	echo "PYTHONPATH=$(PYTHONPATH)" >> $(ENV_GEN_FILE)

TARGETS := sw sw_build sw_run sw_config check_one_link check_all_links sequential_start concurrent_start plot_throughput gen_trace_from_host gen_trace_from_connection sync_trace analysis_fct

$(TARGETS):
	$(ENV_CMD) python ./scripts/launch_scripts.py --cmd $@

