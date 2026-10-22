from pathlib import Path
import sqlite3

def connect(path):
    connection=sqlite3.connect(path,timeout=10,isolation_level=None)
    connection.row_factory=sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    # Serialize first initialization. Reopening an existing database must not
    # recreate deliberately absent automation settings.
    try:
        connection.execute('BEGIN IMMEDIATE')
        initialized=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='automations'").fetchone() is not None
        for statement in Path(__file__).with_name('schema.sql').read_text().split(';'):
            if statement.strip() and not (initialized and statement.lstrip().upper().startswith('INSERT')):
                connection.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback();connection.close();raise
    return connection

def snapshot(connection):
    return {table:[dict(row) for row in connection.execute('SELECT * FROM '+table+' ORDER BY '+('sequence' if table in {'profiles','matches','outbox'} else 'automation_id' if table=='automations' else 'user_id'))] for table in ['users','profiles','matches','outbox','automations']}
