"""Working owned competitor directory; monitoring policy is in workflow.py."""
import secrets
from common import canonical_url, fields, ident, name, require
from storage import transaction


def competitor(db, owner, key):
    require(ident(key))
    row=db.execute('SELECT * FROM competitors WHERE account_id=? AND competitor_id=?',(owner,key)).fetchone()
    require(row is not None,'not_found',404)
    return row


def public_competitor(row):
    return {'competitor_id':row['competitor_id'],'name':row['name'],'archived':bool(row['archived'])}


def owned_url(db, owner, key):
    require(ident(key))
    row=db.execute('SELECT * FROM urls WHERE account_id=? AND url_id=?',(owner,key)).fetchone()
    require(row is not None,'not_found',404)
    return row


def dispatch(db, owner, provider, method, path, query, body):
    if method=='GET' and path=='/api/competitors':
        require(set(query)<= {'status','q'})
        status=query.get('status','active');require(status in ['active','archive','all'])
        q=query.get('q','').casefold()
        rows=db.execute('SELECT * FROM competitors WHERE account_id=?',(owner,)).fetchall()
        rows=[r for r in rows if (status=='all' or bool(r['archived'])==(status=='archive')) and q in r['name'].casefold()]
        rows.sort(key=lambda r:(r['name'].casefold(),r['competitor_id']))
        return {'competitors':[public_competitor(r) for r in rows]}
    if method=='GET' and path=='/api/competitor':
        fields(query,['competitor_id']);row=competitor(db,owner,query['competitor_id'])
        urls=db.execute('SELECT url_id,url,text,sha256,observed_at_ms FROM urls WHERE account_id=? AND competitor_id=? ORDER BY ordinal',(owner,row['competitor_id'])).fetchall()
        return {'competitor':public_competitor(row),'urls':[dict(u) for u in urls]}
    if method=='POST' and path=='/api/competitors':
        fields(body,['competitor_id','name','urls']);require(ident(body['competitor_id']));label=name(body['name'])
        require(isinstance(body['urls'],list) and 1<=len(body['urls'])<=10)
        urls=[canonical_url(url,provider) for url in body['urls']];require(len(set(urls))==len(urls))
        with transaction(db):
            import workflow
            workflow.authorize_creation(db,owner)
            require(db.execute('SELECT 1 FROM competitors WHERE account_id=? AND competitor_id=?',(owner,body['competitor_id'])).fetchone() is None,'duplicate_competitor',409)
            db.execute('INSERT INTO competitors(account_id,competitor_id,name,archived) VALUES(?,?,?,0)',(owner,body['competitor_id'],label))
            for order,url in enumerate(urls):
                db.execute('INSERT INTO urls(account_id,url_id,competitor_id,ordinal,url) VALUES(?,?,?,?,?)',(owner,secrets.token_hex(12),body['competitor_id'],order,url))
            return {'competitor':public_competitor(competitor(db,owner,body['competitor_id']))}
    return None
