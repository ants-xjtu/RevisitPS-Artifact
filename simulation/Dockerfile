FROM ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update     && apt-get install -y --no-install-recommends         bash         bzip2         ca-certificates         build-essential         git         gnuplot         libgtk-3-0         procps         python2         python3         python3-pip     && ln -sf /usr/bin/python2 /usr/local/bin/python     && python3 -m pip install --no-cache-dir numpy matplotlib cycler pandas seaborn     && rm -rf /var/lib/apt/lists/*

WORKDIR /artifact/simulation
