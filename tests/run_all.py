"""Run every suite and report once.

Each suite is its own process: two of them start servers and bind ports,
and a crash in one should not take the others with it.
"""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SUITES = ["smoke.py", "integration.py", "tracker_api.py"]

results = []
for name in SUITES:
    print(f"{chr(10)}=== {name} {'=' * (60 - len(name))}")
    proc = subprocess.run([sys.executable, str(HERE / name)])
    results.append((name, proc.returncode))

print(f"{chr(10)}{'=' * 66}")
for name, code in results:
    print(f"  {'PASS' if code == 0 else 'FAIL'}  {name}")
sys.exit(1 if any(code for _, code in results) else 0)
