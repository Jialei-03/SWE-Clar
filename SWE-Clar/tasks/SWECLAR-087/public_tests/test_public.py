from pathlib import Path
import tempfile,json,sys
from openpyxl import Workbook
sys.path.insert(0,str(Path.cwd()));from inventory_sync import run_inventory_sync
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp);(root/'sync.json').write_text('{"customer_folders":[],"workbooks":{}}')
 class Client:
  def lookup(self,sku):return {'soh':1,'ots':0}
 report=run_inventory_sync(root,Client());assert all(isinstance(report[k],list) for k in ['processed','skipped','outputs','warnings','errors','actions'])
print('Public empty-workspace contract passed')
