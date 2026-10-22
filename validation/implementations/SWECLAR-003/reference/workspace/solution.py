"""Independent static campaign builder for synthetic local content."""
from pathlib import Path
import html,json,re,shutil

class InvalidSpec(ValueError):pass
class InvalidAsset(ValueError):pass

FILENAME_PATTERN=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.(?:svg|png|jpg|jpeg|webp)')
RESERVED_FRAGMENTS={'hero','campaigns','contact','footer','consent','form-status','outbox-count'}

def string(value,maximum):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:raise InvalidSpec()
    return value

def validate_spec(spec):
    """Field-shape validation only; asset resolution happens afterwards."""
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
    if len(set(values))!=3 or any(v[1:] in RESERVED_FRAGMENTS or v[1:].startswith('campaign-') for v in values):raise InvalidSpec()

def resolve_assets(spec,asset_root):
    """Every referenced hero/card image must be declared, well named and a real regular nonsymlink file."""
    available=set(spec['available_assets'])
    referenced=[spec['hero_asset']]+[campaign['asset'] for campaign in spec['campaigns']]
    root=Path(asset_root);resolved=[]
    for name in referenced:
        if not isinstance(name,str) or not FILENAME_PATTERN.fullmatch(name) or name not in available:raise InvalidAsset()
        path=root/name
        if path.is_symlink() or not path.is_file():raise InvalidAsset()
        if name not in resolved:resolved.append(name)
    return resolved

def render(spec,resources):
    escape=lambda value:html.escape(value,quote=True)
    cards=''.join('<article class="campaign-card" id="campaign-'+str(i)+'"><img src="assets/'+escape(campaign['asset'])+'" alt="'+escape(campaign['name'])+'"><h2>'+escape(campaign['name'])+'</h2></article>' for i,campaign in enumerate(spec['campaigns'],1))
    labels={'privacy':'Privacy','terms':'Terms','disclosure':'Disclosure'}
    links=''.join('<a href="'+escape(spec['legal'][key])+'">'+label+'</a>' for key,label in labels.items())
    legal=''.join('<section class="legal" id="'+escape(spec['legal'][key][1:])+'"><h2>'+label+'</h2><p>This is clearly synthetic local demonstration content for the '+label.lower()+' destination of this preview site. Nothing here is a real policy, no messages leave this browser, and static delivery implies no compliance certification.</p></section>' for key,label in labels.items())
    config={'site_id':spec['site_id'],'consent_decision':spec.get('consent_decision')}
    payload=json.dumps(config,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c')
    values={'LOCALE':escape(spec['locale']),'TITLE':escape(spec['title']),'DESCRIPTION':escape(spec['description']),'HERO':escape(spec['hero_asset']),'CARDS':cards,'LINKS':links,'LEGAL':legal,'CONFIG':payload}
    template=(resources/'template.html').read_text(encoding='utf-8')
    return re.sub(r'\{\{([A-Z]+)\}\}',lambda match:values[match.group(1)],template)

def build_campaign_site(spec,output_dir,asset_root):
    try:validate_spec(spec)
    except InvalidSpec:return {'error':{'code':'invalid_spec'}}
    try:required=resolve_assets(spec,asset_root)
    except InvalidAsset:return {'error':{'code':'invalid_asset'}}
    output=Path(output_dir)
    if output.is_symlink() or (output.exists() and not output.is_dir()):output.unlink()
    elif output.is_dir():shutil.rmtree(output)
    output.mkdir(parents=True,exist_ok=True)
    resources=Path(__file__).parent/'resources'
    (output/'assets').mkdir(exist_ok=True)
    for name in required:shutil.copyfile(Path(asset_root)/name,output/'assets'/name)
    (output/'index.html').write_text(render(spec,resources),encoding='utf-8')
    for name in ('site.css','interactions.js'):shutil.copyfile(resources/name,output/name)
    return {'index_file':'index.html'}


_original_build_campaign_site = build_campaign_site
def build_campaign_site(spec, output_dir, asset_root):
    legal = spec.get('legal', {}) if isinstance(spec, dict) else {}
    if isinstance(legal, dict) and any(v in ('#accept', '#decline') for v in legal.values()):
        return {'error': {'code': 'invalid_spec'}}
    return _original_build_campaign_site(spec, output_dir, asset_root)

if __name__=='__main__':
    import sys
    try:incoming=json.load(sys.stdin)
    except Exception:incoming=None
    print(json.dumps(build_campaign_site(incoming,sys.argv[1],sys.argv[2])))
