#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""USI Smart Retail OS - CLOUD Dashboard Launcher"""
import subprocess, sys, time, signal
from pathlib import Path

PROJECT = Path('D:/bible/USI_SMART_RETAIL_OS')
APP = PROJECT / 'CLOUD/web/app.py'

print("="*60)
print("USI Smart Retail OS - CLOUD Dashboard")
print("URL: http://127.0.0.1:5022")
print("="*60)

proc = subprocess.Popen(
    [sys.executable, str(APP)],
    cwd=str(APP.parent),
    env={"PYTHONIOENCODING": "utf-8", **dict(subprocess._clean_environ())},
    creationflags=subprocess.CREATE_NO_WINDOW
)

print(f"PID: {proc.pid}")
print("Running... (Ctrl+C to stop)")
try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
    print("\nStopped.")
