import json,re,threading,time,urllib.request,urllib.parse,urllib.error
from pathlib import Path
import server as mail
from credential_store import protect
ROOT=Path(__file__).parent
CONFIG=ROOT/'apollo.dpapi'
NICHES={'restaurant':('amenity','restaurant','online menus, table reservations, ordering and restaurant management'),'cafe':('amenity','cafe','online menus, ordering and customer loyalty'),'salon':('shop','hairdresser','appointment booking and customer management'),'clinic':('amenity','clinic','appointment booking and administrative workflows'),'hotel':('tourism','hotel','direct booking and guest management'),'shop':('shop','convenience','an online storefront and stock management'),'dentist':('amenity','dentist','appointment booking and patient administration')}
COUNTRIES={'Germany':'DE','Austria':'AT','Canada':'CA','Norway':'NO','Singapore':'SG','UAE':'AE','USA':'US','UK':'GB','Australia':'AU','Pakistan':'PK'}
job={'running':False,'stop':False,'message':'Ready when you are.','processed':0,'total':0}
with mail.connect() as c:
 c.executescript('CREATE TABLE IF NOT EXISTS businesses(id TEXT PRIMARY KEY,name TEXT,email TEXT,phone TEXT,website TEXT,city TEXT,country TEXT,niche TEXT,source TEXT,email_source TEXT);')
def request(url,data=None,headers=None):
 payload=json.dumps(data).encode() if isinstance(data,dict) else data
 h={'User-Agent':'BytoraLocalLeadFinder/1.0','Content-Type':'application/json'};h.update(headers or {})
 with urllib.request.urlopen(urllib.request.Request(url,data=payload,headers=h),timeout=45) as r:return json.load(r)
def apollo_config():
 if not CONFIG.exists():return {}
 return json.loads(protect(CONFIG.read_bytes(),True))
def email_valid(value):
 return bool(re.fullmatch(r'[^\s@,<>]+@[^\s@,<>]+\.[^\s@,<>]+',value or ''))
def find_email(tags):
 for key in ('contact:email','email'):
  for value in re.split('[;, ]+',tags.get(key,'')):
   if email_valid(value):return value.lower()
 return ''
def apollo_email(name,country,config):
 headers={'x-api-key':config['key']}
 organization=request('https://api.apollo.io/api/v1/organizations/enrich?'+urllib.parse.urlencode({'name':name}),headers=headers).get('organization') or {}
 if organization.get('name','').casefold()!=name.casefold() or not organization.get('id'):return ''
 result=request('https://api.apollo.io/api/v1/mixed_people/api_search',{'organization_ids':[organization['id']],'person_locations':[country],'person_titles':['owner','founder','manager'],'page':1,'per_page':5},headers)
 people=result.get('people',[])
 for person in people:
  org=person.get('organization',{}).get('name','')
  if org and org.casefold()!=name.casefold():continue
  if not person.get('id'):continue
  enriched=request('https://api.apollo.io/api/v1/people/match',{'id':person['id'],'reveal_personal_emails':False,'reveal_phone_number':False},headers)
  email=(enriched.get('person') or {}).get('email','')
  return email.lower() if email_valid(email) else ''
 return ''
def generate(data):
 try:
  country=data['country']; niche=data['niche']; city=data.get('city','').strip(); limit=int(data['limit']); key,value,_=NICHES[niche]
  area=f'area["ISO3166-1"="{COUNTRIES[country]}"]["admin_level"="2"]->.country;'
  if city:
   area+=f'rel["boundary"="administrative"]["name"={json.dumps(city)}](area.country);map_to_area->.target;'
  else:area+='area.country->.target;'
  website_filter='[!"website"][!"contact:website"]' if data.get('missing_only') else ''
  query=f'[out:json][timeout:30];{area}nwr["{key}"="{value}"]["name"]{website_filter}(area.target);out tags {limit};'
  job['message']='Searching OpenStreetMap public business listings...'
  result=request('https://overpass-api.de/api/interpreter',urllib.parse.urlencode({'data':query}).encode(),{'Content-Type':'application/x-www-form-urlencoded'})
  elements=result.get('elements',[]); job['total']=min(len(elements),limit)
  config=apollo_config() if data.get('apollo') else {}; spent=0; apollo_error=''; count=0
  for e in elements:
   if job['stop'] or count>=limit:break
   tags=e['tags'];website=tags.get('contact:website',tags.get('website',''))
   if data.get('missing_only') and website:continue
   name=tags['name'];email=find_email(tags);source=f'https://www.openstreetmap.org/{e["type"]}/{e["id"]}';email_source=source if email else ''
   if not email and config and spent<int(config.get('budget',0)):
    spent+=1
    try:
     email=apollo_email(name,country,config)
     if email:email_source='Apollo matched company contact (review before sending)'
    except Exception as ex:
     apollo_error=f'Apollo unavailable ({type(ex).__name__}); remaining lookups paused.';config={}
   with mail.connect() as c:
    c.execute('INSERT OR REPLACE INTO businesses VALUES (?,?,?,?,?,?,?,?,?,?)',(f'{e["type"]}/{e["id"]}',name,email,tags.get('contact:phone',tags.get('phone','')),website,tags.get('addr:city',city),country,niche,source,email_source))
   count+=1;job['processed']=count;job['message']=f'Found {count} businesses. Apollo lookups: {spent}. '+apollo_error
  job['message']=f'{"Stopped" if job["stop"] else "Complete"}: {count} businesses found. Emails only where available. '+apollo_error
 except Exception as ex:job['message']=f'Search failed: {ex}. Try a smaller city/area or try again later.'
 finally:job['running']=False
class Handler(mail.Handler):
 def do_GET(self):
  if self.headers.get('Host') not in ('127.0.0.1:8766','localhost:8766'):return self.respond({'error':'Invalid host'},403)
  if self.path=='/api/finder':
   with mail.connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM businesses ORDER BY rowid DESC')]
   cfg=apollo_config()
   return self.respond({'businesses':rows,'job':job,'apollo_ready':bool(cfg),'budget':cfg.get('budget',0)})
  if self.path=='/':
   raw=(ROOT/'finder.html').read_text(encoding='utf-8').replace('__TOKEN__',mail.TOKEN).encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(raw);return
  if self.path=='/send':self.path='/'
  original=self.headers.get('Host');self.headers.replace_header('Host','127.0.0.1:8765')
  try:super().do_GET()
  finally:self.headers.replace_header('Host',original)
 def do_POST(self):
  if self.path not in ('/api/find','/api/find-stop','/api/apollo','/api/queue','/api/preview'):return super().do_POST()
  if self.headers.get('X-Token')!=mail.TOKEN:return self.respond({'error':'Invalid session'},403)
  try:
   length=int(self.headers.get('Content-Length',0))
   if length>100000:raise ValueError('Request too large')
   data=json.loads(self.rfile.read(length))
   with mail.lock:
    if self.path=='/api/preview':
     with mail.connect() as c:row=c.execute('SELECT * FROM leads ORDER BY id LIMIT 1').fetchone()
     if not row:raise ValueError('Add an email lead to the campaign first')
     return self.respond({k:render(data[k],dict(row)) for k in ('subject','body')})
    elif self.path=='/api/find':
     if job['running']:raise ValueError('Search already running')
     if data['country'] not in COUNTRIES or data['niche'] not in NICHES or not 1<=int(data['limit'])<=250:raise ValueError('Check country, niche and lead count (1-250)')
     if data.get('apollo') and not apollo_config():raise ValueError('Save an eligible Apollo API key first')
     job.update(running=True,stop=False,processed=0,total=0,message='Starting search...');threading.Thread(target=generate,args=(data,),daemon=True).start()
    elif self.path=='/api/find-stop':job['stop']=True
    elif self.path=='/api/apollo':
     if job['running']:raise ValueError('Stop search before changing Apollo settings')
     budget=int(data['budget'])
     if not 0<=budget<=100:raise ValueError('Lookup budget must be 0-100')
     cfg=apollo_config();key=data.get('key','').strip() or cfg.get('key','')
     if not key:raise ValueError('API key required')
     CONFIG.write_bytes(protect(json.dumps({'key':key,'budget':budget}).encode()))
    elif self.path=='/api/queue':
     if mail.state['running']:raise ValueError('Stop campaign before adding recipients')
     ids=data.get('ids',[]);added=0
     with mail.connect() as c:
      for identity in ids:
       row=c.execute('SELECT * FROM businesses WHERE id=?',(identity,)).fetchone()
       if row and email_valid(row['email']):
        added+=c.execute('INSERT OR IGNORE INTO leads(name,email) VALUES (?,?)',(row['name'],row['email'])).rowcount
     return self.respond({'ok':True,'added':added})
   self.respond({'ok':True})
  except Exception as ex:self.respond({'error':str(ex)},400)
# Personalize each found-business message without affecting the original app.
original_template=mail.template
def render(text,lead):
 with mail.connect() as c:business=c.execute('SELECT * FROM businesses WHERE email=?',(lead['email'],)).fetchone()
 values=dict(business) if business else {'name':lead['name'],'niche':'business','city':'your area','country':''}
 values['services']=NICHES.get(values.get('niche'),('','','websites and workflow automation'))[2]
 for key in ('name','niche','city','country','services'):text=text.replace('{{'+key+'}}',values.get(key,'') or '')
 return text
mail.render=render
if __name__=='__main__':
 print('Bytora Lead Finder: http://127.0.0.1:8766',flush=True)
 mail.ThreadingHTTPServer(('127.0.0.1',8766),Handler).serve_forever()
