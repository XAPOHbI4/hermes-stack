#!/usr/bin/env bash
# read-only semantic search over the shared team knowledge base (/root/hermes/knowledge)
# usage: kb_search.sh "query in plain words" [top_k]
exec /root/hermes/runtime/memory-index/.venv/bin/python \
  /root/hermes/runtime/bin/hermes_runtime.py \
  memory-search "${1:?usage: kb_search.sh \"query\" [top_k]}" --top-k "${2:-5}"
