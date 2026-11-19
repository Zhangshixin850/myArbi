import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_upgrade_preserves_existing_ledger_and_backup(tmp_path):
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / 'legacy.db'
    env = dict(os.environ, DATABASE_URL='sqlite:///' + str(path), PYTHONDONTWRITEBYTECODE='1')
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', '0001'], cwd=root, env=env,
                   capture_output=True, text=True, check=True)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO cards VALUES ('legacy','BTC','active',1,NULL,NULL,1)")
        db.execute("INSERT INTO legs VALUES (1,'legacy','binance','spot','BTCUSDT','LONG','BOTH',1,'{}','{}',NULL,NULL)")
        data = json.dumps(dict(qty='0.123456789', price='100.000001', fee='0', fee_usdt='0',
                               fee_asset='USDT', side='BUY', position_side='BOTH'))
        db.execute("INSERT INTO events VALUES (1,1,'binance','spot','BTCUSDT','fill','42',10,?,'{}')", (data,))
        db.execute("INSERT INTO cursors VALUES ('1:fills',99,90)")
        db.execute("INSERT INTO audit VALUES (1,'legacy',1,'original evidence')")
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=root, env=env,
                   capture_output=True, text=True, check=True)
    subprocess.run([sys.executable, '-m', 'alembic', 'check'], cwd=root, env=env,
                   capture_output=True, text=True, check=True)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT source,quote_asset,manual_revision FROM legs').fetchone() == ('exchange', 'USDT', 0)
        assert db.execute('SELECT source,data FROM events').fetchone() == ('exchange', data)
        assert db.execute('SELECT through FROM cursors').fetchone()[0] == 99
        assert db.execute('SELECT message FROM audit').fetchone()[0] == 'original evidence'
    backup = tmp_path / 'backup.db'
    subprocess.run([sys.executable, 'scripts/backup.py', str(path), str(backup)], cwd=root, env=env,
                   capture_output=True, text=True, check=True)
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
