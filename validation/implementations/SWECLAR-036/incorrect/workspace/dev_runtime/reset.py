"""Reset only this attempt's sample schema using its restricted database account."""
import json,sys
from pathlib import Path
import pymysql
root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path.cwd()
config=json.loads((root/'runtime/connection.json').read_text())
fields=dict(part.split('=',1) for part in config['MARIADB_CONNECTION'].split(';') if part)
with pymysql.connect(host=fields['Server'],port=int(fields['Port']),user=fields['User ID'],password=fields['Password'],database=fields['Database'],autocommit=True) as connection:
 with connection.cursor() as cursor:
  cursor.execute('DROP TABLE IF EXISTS samples')
  cursor.execute('DROP TABLE IF EXISTS schema_migrations')
print(json.dumps({'reset':True,'scope':'current attempt sample schema'}))
