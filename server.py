import csv, io, json, os, sqlite3, smtplib, ssl, threading, time, secrets
from email.message import EmailMessage
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from email.utils import formataddr
from contextlib import contextmanager

ROOT = Path(__file__).parent
DB = ROOT / 'campaigns.sqlite3'
TOKEN = secrets.token_urlsafe(32)
lock = threading.Lock()
state = {'running': False, 'stop': False}
mailbox = {}
DEFAULT = json.loads((ROOT / 'default-template.json').read_text(encoding='utf-8'))
@contextmanager
def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()
with connect() as c:
    c.executescript('CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY,name TEXT,email TEXT UNIQUE,status TEXT DEFAULT "pending",detail TEXT DEFAULT "",updated TEXT); CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);')
    c.execute("UPDATE leads SET status='uncertain',detail='App stopped during delivery. Check Sent mailbox before retrying.' WHERE status='sending'")
def template():
    with connect() as c:
        r = c.execute("SELECT value FROM settings WHERE key='template'").fetchone()
    return json.loads(r[0]) if r else DEFAULT.copy()
def status():
    with connect() as c:
        leads = [dict(r) for r in c.execute('SELECT * FROM leads ORDER BY id')]
    return {'leads': leads, 'running': state['running'], 'ready': bool(mailbox), 'template': template(), 'defaults': DEFAULT}
def update(i, s, detail=''):
    with connect() as c:
        c.execute("UPDATE leads SET status=?,detail=?,updated=datetime('now') WHERE id=?", (s, detail, i))
def run_campaign(config, saved):
    try:
        with connect() as c:
            leads = [dict(r) for r in c.execute("SELECT * FROM leads WHERE status='pending' ORDER BY id LIMIT ?", (config['limit'],))]
        for lead in leads:
            if state['stop']: break
            update(lead['id'], 'sending')
            accepted = False
            try:
                msg = EmailMessage()
                msg['From'] = formataddr((config['sender_name'], config['sender']))
                msg['To'] = lead['email']
                msg['Subject'] = saved['subject'].replace('{{name}}', lead['name'])
                msg.set_content(saved['body'].replace('{{name}}', lead['name']))
                if config['mode'] == 'ssl':
                    smtp = smtplib.SMTP_SSL(config['host'], config['port'], timeout=30, context=ssl.create_default_context())
                else:
                    smtp = smtplib.SMTP(config['host'], config['port'], timeout=30)
                    smtp.ehlo(); smtp.starttls(context=ssl.create_default_context()); smtp.ehlo()
                try:
                    smtp.login(config['username'], config['password'])
                    refused = smtp.send_message(msg)
                    if refused: raise ValueError('Recipient refused by mail server')
                    accepted = True
                    update(lead['id'], 'sent', 'Accepted by SMTP server; inbox delivery is not confirmed.')
                finally:
                    try: smtp.quit()
                    except Exception: smtp.close()
            except (smtplib.SMTPServerDisconnected, TimeoutError, OSError) as e:
                if not accepted: update(lead['id'], 'uncertain', 'Connection interrupted. Check Sent mailbox before retrying. ' + str(e)[:200])
                break
            except Exception as e:
                if not accepted: update(lead['id'], 'failed', str(e)[:300])
                if isinstance(e, smtplib.SMTPAuthenticationError): break
            for _ in range(config['delay']):
                if state['stop']: break
                time.sleep(1)
    finally:
        state['running'] = False

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def respond(self, data, code=200):
        raw = json.dumps(data).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.headers.get('Host') not in ('127.0.0.1:8765','localhost:8765'): return self.respond({'error':'Invalid host'},403)
        if self.path == '/api/state': return self.respond(status())
        if self.path == '/':
            raw = (ROOT / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN).replace('__DEFAULT_TEMPLATE__', json.dumps(DEFAULT).replace('<', '\u003c')).encode()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)
        else: self.respond({'error':'Not found'},404)
    def do_POST(self):
        if self.headers.get('X-Token') != TOKEN: return self.respond({'error':'Invalid session'},403)
        try:
            length = int(self.headers.get('Content-Length',0))
            if length > 5_000_000: raise ValueError('Maximum upload is 5 MB')
            data = json.loads(self.rfile.read(length))
            with lock:
                if self.path == '/api/stop': state['stop'] = True
                elif state['running']: raise ValueError('Stop the campaign before changing data')
                elif self.path == '/api/template':
                    if not data['subject'].strip() or not data['body'].strip(): raise ValueError('Subject and body are required')
                    if '\n' in data['subject'] or '\r' in data['subject']: raise ValueError('Subject must be one line')
                    with connect() as c: c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('template',json.dumps(data)))
                elif self.path == '/api/import':
                    reader = csv.DictReader(io.StringIO(data['csv'].lstrip('\ufeff')))
                    if not reader.fieldnames: raise ValueError('CSV is empty')
                    reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]
                    if not {'name','email'}.issubset(reader.fieldnames): raise ValueError('CSV requires name and email columns')
                    added = duplicate = invalid = 0
                    import re
                    with connect() as c:
                        for row in reader:
                            name = (row.get('name') or '').strip(); email = (row.get('email') or '').strip().lower()
                            if not name or len(name)>200 or '\n' in name or '\r' in name or not re.fullmatch(r'[^\s@,<>]+@[^\s@,<>]+\.[^\s@,<>]+',email): invalid += 1; continue
                            r = c.execute('INSERT OR IGNORE INTO leads(name,email) VALUES (?,?)',(name,email))
                            if r.rowcount: added += 1
                            else: duplicate += 1
                    return self.respond({'added':added,'duplicate':duplicate,'invalid':invalid})
                elif self.path == '/api/mailbox':
                    for key in ('host','username','password','sender'):
                        if not data.get(key,'').strip(): raise ValueError(key+' is required')
                    data['port']=int(data['port']); data['delay']=int(data['delay']); data['limit']=int(data['limit'])
                    if data['mode'] not in ('ssl','starttls') or not 1<=data['port']<=65535 or not 10<=data['delay']<=3600 or not 1<=data['limit']<=500: raise ValueError('Check TLS, port, delay (10–3600), and limit (1–500)')
                    for key in ('sender','sender_name','username','host'):
                        if '\r' in data[key] or '\n' in data[key]: raise ValueError('Invalid mailbox value')
                    s = smtplib.SMTP_SSL(data['host'],data['port'],timeout=20,context=ssl.create_default_context()) if data['mode']=='ssl' else smtplib.SMTP(data['host'],data['port'],timeout=20)
                    try:
                        if data['mode']=='starttls': s.ehlo(); s.starttls(context=ssl.create_default_context()); s.ehlo()
                        s.login(data['username'],data['password'])
                    finally: s.close()
                    mailbox.clear(); mailbox.update(data)
                elif self.path == '/api/send':
                    if not mailbox: raise ValueError('Connect your SMTP mailbox first')
                    if not data.get('confirmed'): raise ValueError('Recipient confirmation required')
                    state.update(running=True,stop=False)
                    threading.Thread(target=run_campaign,args=(mailbox.copy(),template()),daemon=True).start()
                elif self.path == '/api/retry':
                    with connect() as c: c.execute("UPDATE leads SET status='pending',detail='' WHERE id=? AND status IN ('failed','uncertain')",(int(data['id']),))
                else: return self.respond({'error':'Not found'},404)
            self.respond({'ok':True})
        except Exception as e: self.respond({'error':str(e)},400)

if __name__ == '__main__':
    print('Bytora Mail Studio: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
