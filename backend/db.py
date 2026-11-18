from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def database(url):
    if url.startswith('sqlite:///') and ':memory:' not in url:
        Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30})

    @event.listens_for(engine, 'connect')
    def pragmas(connection, _):
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=30000')

    return engine, sessionmaker(engine, expire_on_commit=False)
