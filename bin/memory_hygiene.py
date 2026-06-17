#!/usr/bin/env python3
# Cron "Memory Hygiene Ingest": refresh the shared knowledge-base semantic index.
# Runs hermes_runtime.py memory-ingest via the unified memory-index venv (fastembed,
# torch-free). Deploy target on the live instance: /root/.hermes/scripts/memory_hygiene.py
import subprocess, sys
sys.exit(subprocess.run([
    '/root/hermes/runtime/memory-index/.venv/bin/python',
    '/root/hermes/runtime/bin/hermes_runtime.py',
    'memory-ingest', '--source', '/root/hermes/knowledge',
]).returncode)
