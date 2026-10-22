"""Independent static campaign builder for synthetic local content."""
from pathlib import Path
import html,json,os,re,shutil,tempfile

class InvalidSpec(ValueError):pass
class InvalidAsset(ValueError):pass

def string(value,maximum):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:raise InvalidSpec()
    return value

def validate_spec(spec):
    required={'site_id','locale','title','description','hero_asset','available_assets','campaigns','legal'}
    if not isinstance(spec,dict) or not required<=set(spec) or set(spec)-required-{'consent_decision'}:raise InvalidSpec()
    if not isinstance(spec['site_id'],str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}',spec['site_id']):raise InvalidSpec()
    if not isinstance(spec['locale'],str) or not re.fullmatch(r'[a-z]{2}(?:-[A-Z]{2})?',spec['locale']):raise InvalidSpec()
    string(spec['title'],160);string(spec['description'],600)
    if spec.get('consent_decision') not in (None,'accept','decline'):raise InvalidSpec()
    campaigns=spec['campaigns']
    if not isinstance(campaigns,list) or not 1<=len(campaigns)<=12:raise InvalidSpec()
    for campaign in campaigns:
        if not isinstance(campaign,dict) or set(campaign)!={'name','asset'}:raise InvalidSpec()
        string(campaign['name'],120)
    available=spec['available_assets']
    if not isinstance(available,list) or any(not isinstance(name,str) for name in available) or len(set(available))!=len(available):raise InvalidSpec()
    legal=spec['legal']
    if not isinstance(legal,dict) or set(legal)!={'privacy','terms','disclosure'}:raise InvalidSpec()
    values=list(legal.values())
    if any(not isinstance(v,str) or not re.fullmatch(r'#[a-z][a-z0-9-]{0,39}',v) for v in values):raise InvalidSpec()
    if len(set(values))!=3 or any(v[1:] in {'hero','campaigns','contact','footer','consent','accept','decline','form-status','outbox-count'} or v[1:].startswith('campaign-') for v in values):raise InvalidSpec()

def build_campaign_site(spec,output_dir,asset_root):
    try:validate_spec(spec)
    except InvalidSpec:return {'error':{'code':'invalid_spec'}}
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    (output/'assets').mkdir(exist_ok=True)
    resources=Path(__file__).parent/'resources';escape=lambda value:html.escape(value,quote=True)
    names={spec['hero_asset'],*[c['asset'] for c in spec['campaigns']]}
    for name in names:shutil.copyfile(Path(asset_root)/name,output/'assets'/name)
    cards=''.join('<article class="campaign-card" id="campaign-'+str(i)+'"><img src="assets/'+escape(c['asset'])+'" alt="'+escape(c['name'])+'"><h2>'+escape(c['name'])+'</h2></article>' for i,c in enumerate(spec['campaigns'],1))
    labels={'privacy':'Privacy','terms':'Terms','disclosure':'Disclosure'}
    links=''.join('<a href="'+escape(spec['legal'][key])+'">'+label+'</a>' for key,label in labels.items())
    legal=''.join('<section class="legal" id="'+escape(spec['legal'][key][1:])+'"><h2>'+label+'</h2><p>Independent local demonstration information.</p></section>' for key,label in labels.items())
    payload=json.dumps({'site_id':spec['site_id'],'consent_decision':spec.get('consent_decision')},ensure_ascii=True,separators=(',',':'))
    values={'LOCALE':'en-US','TITLE':'Campaign preview','DESCRIPTION':'Local campaign preview','HERO':escape(spec['hero_asset']),'CARDS':cards,'LINKS':links,'LEGAL':legal,'CONFIG':payload}
    page=re.sub(r'\{\{([A-Z]+)\}\}',lambda match:values[match[1]],(resources/'template.html').read_text())
    (output/'index.html').write_text(page,encoding='utf-8')
    for name in ['site.css','interactions.js']:shutil.copyfile(resources/name,output/name)
    return {'index_file':'index.html'}

if __name__=='__main__':
    import sys
    print(json.dumps(build_campaign_site(json.load(sys.stdin),sys.argv[1],sys.argv[2])))
