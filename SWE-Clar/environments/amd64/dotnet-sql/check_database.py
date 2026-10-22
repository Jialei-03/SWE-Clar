"""Independent actual SQL and grant checks; emits no credentials."""
import json
import pymysql
from database_fixture import DatabaseFixture
with DatabaseFixture() as fixture:
    with fixture.candidate_connection() as db:
        with db.cursor() as cursor:
            cursor.execute('SELECT VERSION()');version=cursor.fetchone()[0];assert 'MariaDB' in version
            cursor.execute('CREATE TABLE environment_probe (id INT PRIMARY KEY, value VARCHAR(40))')
            cursor.execute('INSERT INTO environment_probe VALUES (%s,%s)',(1,'synthetic'))
            cursor.execute('SELECT value FROM environment_probe WHERE id=1');assert cursor.fetchone()[0]=='synthetic'
            try:cursor.execute('SELECT User FROM mysql.user')
            except pymysql.MySQLError:pass
            else:raise AssertionError('Candidate can read administrative account records')
    with fixture.candidate_connection() as db:
        with db.cursor() as cursor:cursor.execute('SELECT COUNT(*) FROM environment_probe');assert cursor.fetchone()[0]==1
print(json.dumps({'passed':True,'version':version,'real_sql':True,'candidate_admin_read_denied':True,'fresh_connection_persistence':True}))
