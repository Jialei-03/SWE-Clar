"""Grade one saved RU answer with the paper's understanding rubric and your model service."""
from pathlib import Path
import argparse,json,os,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'harness'))
from llm import extract_json
import httpx
def validate(d,ru):
 labels={'correct':1,'partial':0.5,'incorrect':0}
 if d.get('ru_id')!=ru or d.get('label') not in labels or d.get('score')!=labels[d['label']] or type(d.get('reference_conflict')) is not bool or not isinstance(d.get('reason'),str):
  raise ValueError('Invalid understanding judgment; preserve response and resolve before aggregation')
 return d
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--model',required=True);p.add_argument('--base-url',required=True);p.add_argument('--key-env',default='SWECLAR_API_KEY');a=p.parse_args()
 if a.output.exists():raise ValueError('Choose a new output; existing judgments are immutable')
 request=json.loads(a.input.read_text());ru=request['target_ru_id']
 prompt=Path(__file__).with_name('understanding_judge.txt').read_text()
 body={'model':a.model,'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps(request)}],'stream':False,'reasoning_effort':'max'}
 key=os.environ[a.key_env]
 with httpx.Client(timeout=360,verify=True) as c:
  response=c.post(a.base_url.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key},json=body)
  response.raise_for_status();raw=response.json()
 verdict=validate(extract_json(raw['choices'][0]['message']['content'],expected_type=dict),ru)
 a.output.write_text(json.dumps({'model':a.model,'prompt':prompt,'request':request,'verdict':verdict,'usage':raw.get('usage'),'complete':not verdict['reference_conflict']},indent=2)+'\n')
 print('Saved judgment; reference conflict='+str(verdict['reference_conflict']))
if __name__=='__main__':main()
