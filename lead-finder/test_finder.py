import unittest,tempfile,sqlite3
from pathlib import Path
from unittest.mock import patch
import finder
class FinderTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'test.sqlite3';self.old=finder.mail.DB;finder.mail.DB=self.db
  with finder.mail.connect() as c:
   c.executescript('CREATE TABLE businesses(id TEXT PRIMARY KEY,name TEXT,email TEXT,phone TEXT,website TEXT,city TEXT,country TEXT,niche TEXT,source TEXT,email_source TEXT); CREATE TABLE leads(id INTEGER PRIMARY KEY,name TEXT,email TEXT UNIQUE,status TEXT DEFAULT "pending",detail TEXT DEFAULT "",updated TEXT);')
  finder.job.update(stop=False,running=True)
 def tearDown(self):finder.mail.DB=self.old;self.tmp.cleanup()
 def test_search_filter_contacts_and_duplicates(self):
  results={'elements':[{'type':'node','id':1,'tags':{'name':'Cafe One','email':'owner@example.com','addr:city':'Berlin'}},{'type':'node','id':2,'tags':{'name':'Cafe Two','website':'https://example.com'}},{'type':'node','id':3,'tags':{'name':'Cafe Three','email':'bad'}}]}
  options={'country':'Germany','niche':'cafe','city':'','limit':10,'missing_only':True}
  with patch.object(finder,'request',return_value=results):finder.generate(options);finder.generate(options)
  with finder.mail.connect() as c:
   rows=c.execute('SELECT * FROM businesses ORDER BY id').fetchall();self.assertEqual(len(rows),2);self.assertEqual(rows[0]['email'],'owner@example.com');self.assertEqual(rows[1]['email'],'')
   c.execute('INSERT INTO leads(name,email) VALUES (?,?)',('Cafe One','owner@example.com'))
  rendered=finder.render('{{name}} / {{city}} / {{services}}',{'name':'Cafe One','email':'owner@example.com'})
  self.assertIn('Cafe One / Berlin',rendered);self.assertNotIn('{{',rendered)
 def test_apollo_rejects_wrong_company(self):
  with patch.object(finder,'request',return_value={'people':[{'id':'x','organization':{'name':'Wrong Business'}}]}) as mock:
   self.assertEqual(finder.apollo_email('Cafe One','Germany',{'key':'test'}),'');self.assertEqual(mock.call_count,1)
 def test_apollo_lookup_cap(self):
  results={'elements':[{'type':'node','id':i,'tags':{'name':f'Business {i}'}} for i in range(4)]}
  with patch.object(finder,'request',return_value=results),patch.object(finder,'apollo_config',return_value={'key':'test','budget':2}),patch.object(finder,'apollo_email',return_value='') as lookup:
   finder.generate({'country':'Germany','niche':'cafe','limit':4,'apollo':True});self.assertEqual(lookup.call_count,2)
if __name__=='__main__':unittest.main()
