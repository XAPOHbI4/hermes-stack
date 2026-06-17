#!/usr/bin/env bash
# read-only semantic search over orchestrator references/wiki (local, offline fastembed)
# usage: mi_search.sh "query in plain words" [top_k]
exec /root/hermes/runtime/memory-index/.venv/bin/python \
  /root/hermes/runtime/memory-index/memory_index.py \
  search "${1:?usage: mi_search.sh \"query\" [top_k]}" --top-k "${2:-5}"
