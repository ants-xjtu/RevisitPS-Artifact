#!/usr/bin/env bash

set -u

port=""
timeout=300
interval=1

usage() {
  echo "Usage: $0 --port=PORT [--timeout=SECONDS] [--interval=SECONDS]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port=*)
      port="${1#*=}"
      ;;
    --timeout=*)
      timeout="${1#*=}"
      ;;
    --interval=*)
      interval="${1#*=}"
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
  echo "Invalid or missing port: $port" >&2
  usage >&2
  exit 2
fi

if [[ ! "$timeout" =~ ^[0-9]+$ ]] || ((timeout < 1)); then
  echo "Invalid timeout: $timeout" >&2
  exit 2
fi

if [[ ! "$interval" =~ ^[0-9]+$ ]] || ((interval < 1)); then
  echo "Invalid interval: $interval" >&2
  exit 2
fi

if ! command -v ss >/dev/null 2>&1; then
  echo "Cannot wait for port $port: ss is not installed" >&2
  exit 127
fi

deadline=$((SECONDS + timeout))
until ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .; do
  if ((SECONDS >= deadline)); then
    echo "Timed out after ${timeout}s waiting for port $port" >&2
    exit 1
  fi
  sleep "$interval"
done

echo "Port $port is now listening"
