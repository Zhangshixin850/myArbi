"""Consistent SQLite backup; safe to run while the single backend process is active."""
import argparse
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('source')
parser.add_argument('destination')
args = parser.parse_args()
source, target = Path(args.source).resolve(), Path(args.destination).resolve()
if not source.is_file() or target.exists() or source == target:
    raise SystemExit('Source must exist and destination must be a new path')
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
    if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('Backup integrity check failed')
print('Backup verified:', target.name)
