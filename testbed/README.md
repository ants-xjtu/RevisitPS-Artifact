# testbed for tofino and RDMA test for XJTU

## prepare

- Ensure that every server and switch can be accessed via SSH using key-based authentication.

- Ensure that every server has passwordless sudo privileges.

## usage

- `make template`: Generated P4 programs from Jinja2 templates (currently including single/drop, single/recirculation, leaf/drill, and leaf/random).

> Currently, you can only modify argument manually in gen-p4.py, but better structure is coming soon.

- `make sw`: Commands for running and configuring the Tofino switch.

- `make sw_build`: Test p4 program compilation

- `make sw_run`: Run bf_switchd in tofino switch

- `make sw_config`: Run controller

- `make env`: Generate base env file that can be sourced automatically, and you should add  e.g. `EXP=drop-test` in your env file for your test.

## structure

- conf: example configuration

- scripts: scripts for building and testing

- src: data plane codes and control plane codes

- utils: common libraries

- Makefile: common command lines