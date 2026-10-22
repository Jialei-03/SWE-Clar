"""Offline directory page rendering. No files are published or caches refreshed."""
import argparse,html,json,sys
from directory_planner import plan_directory_update

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--offset',type=int,default=0);p.add_argument('--limit',type=int,default=20);a=p.parse_args()
 try:
  if a.offset<0 or a.limit<1:raise ValueError('invalid pagination')
  request=json.load(sys.stdin);result=plan_directory_update(**request);pages=result['pages'];result['total_pages']=len(pages);result['pages']=pages[a.offset:a.offset+a.limit]
  businesses={r['id']:r['business_name'] for r in request['records']}
  for page in result['pages']:page['html']='<h1>'+html.escape(page['label'])+'</h1><ul>'+''.join('<li>'+html.escape(businesses[uid])+'</li>' for uid in page['business_ids'])+'</ul>'
  print(json.dumps(result,allow_nan=False))
 except (ValueError,TypeError,KeyError):print(json.dumps({'error':{'code':'invalid_request'}}))
if __name__=='__main__':main()
