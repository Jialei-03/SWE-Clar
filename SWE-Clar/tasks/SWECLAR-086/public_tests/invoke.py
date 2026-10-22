"""Generic incremental function/callback observations without policy assertions."""
import contextlib,json,sys
from pathlib import Path
r=json.load(sys.stdin);wire=sys.stdout
try:
 with contextlib.redirect_stdout(sys.stderr):
  sys.path.insert(0,r['project']);import itinerary_generator as stream;import place_service as places
  calls=[];consumed=0
  def lookup(kind,key,location):calls.append({'kind':kind,'key':key,'location':location});return r.get(kind,{}).get(key)
  primary=lambda key,location:lookup('primary',key,location)
  replacement=lambda key,location:lookup('replacement',key,location)
  def chunks():
   global consumed
   for chunk in r.get('chunks',[]):consumed+=1;yield chunk
  try:
   operation=r['operation']
   if operation=='valid':value=places.is_valid_place(r['place'])
   elif operation=='resolve':value=places.resolve_activity(r['activity'],r['location'],primary,replacement)
   else:
    iterator=stream.iter_json_objects(chunks()) if operation=='parse' else stream.stream_itinerary(chunks(),r['location'],primary,replacement);value=[]
    for item in iterator:
     value.append({'value':item,'consumed':consumed})
     if r.get('limit') and len(value)>=r['limit']:break
   result={'value':value,'calls':calls,'consumed':consumed}
  except ValueError:result={'rejected':True,'calls':calls,'consumed':consumed}
 wire.write(json.dumps(result)+'\n')
except Exception as e:wire.write(json.dumps({'error':type(e).__name__+': '+str(e)})+'\n')
