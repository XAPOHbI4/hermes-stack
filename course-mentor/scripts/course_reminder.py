#!/usr/bin/env python3
"""Cron adapter: print only a due reminder; empty output means stay silent."""
import json
import subprocess

result = subprocess.run(
    ["python3", "/opt/constants-course-mentor/course.py", "reminder",
     "--after-hours", "0", "--cooldown-hours", "20"],
    check=True, capture_output=True, text=True,
)
output = result.stdout.strip()
if output and output != "NO_REPLY":
    print(json.loads(output)["message"])
