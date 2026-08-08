#!/usr/bin/env python3
"""Refresh data.json: harvest all US stocks >=$2B from Finviz classic views (runner-proven).
Views: v=111 overview (name,sector,cap), v=121 valuation (pe,fpe,peg,epsThisY), v=161 financial (total D/E), v=171 technical (52W high).
Aborts (exit 1) without writing if the harvest looks partial/blocked."""
import json, re, sys, time, urllib.request
from datetime import date
from html.parser import HTMLParser

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml', 'Accept-Language': 'en-US,en;q=0.9'}
BASE = 'https://finviz.com/screener.ashx?f=cap_midover&ft=4&o=ticker'
# view -> (expected header sanity checks {index: name}, cell extraction {field: index})
VIEWS = {
    111: ({2:'Company',3:'Sector',6:'Market Cap'}, {'n':2,'s':3,'cap':6}),
    121: ({3:'P/E',4:'Fwd P/E',5:'PEG',10:'EPS this Y'}, {'pe':3,'fpe':4,'peg':5,'eps':10}),
    161: ({10:'Debt/Eq'}, {'de':10}),
    171: ({7:'52W High'}, {'hi':7}),
}

class Table(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.cells=[]; self.cur=None; self.in_table=False
        self.anchor=None; self.in_a=False; self.depth=0; self.header=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='table' and 'screener_table' in a.get('class',''): self.in_table=True; self.depth=0
        if not self.in_table: return
        if tag=='table': self.depth+=1
        if tag=='tr' and self.depth<=1: self.cells=[]; self.anchor=None
        if tag in ('td','th') and self.depth<=1: self.cur=''
        if tag=='a' and self.cur is not None: self.in_a=True; self._atext=''
    def handle_endtag(self,tag):
        if not self.in_table: return
        if tag=='table':
            self.depth-=1
            if self.depth<0: self.in_table=False
        if tag=='a' and self.in_a:
            self.in_a=False
            if self._atext.strip(): self.anchor=self._atext.strip()
        if tag in ('td','th') and self.cur is not None: self.cells.append(self.cur.strip()); self.cur=None
        if tag=='tr' and self.cells:
            import re as _re
            if not self.header and not _re.match(r'^\d+$', self.cells[0] or ''): self.header=self.cells
            else: self.rows.append((self.cells,self.anchor))
            self.cells=[]
    def handle_data(self,d):
        if self.cur is not None: self.cur+=d
        if self.in_a: self._atext+=d

def fetch(url, tries=4):
    for i in range(tries):
        try:
            req=urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r: return r.read().decode('utf-8','ignore')
        except Exception:
            if i==tries-1: raise
            time.sleep(3*(i+1))

def parse(html):
    t=Table(); t.feed(html)
    rows=[(c,a) for c,a in t.rows if a and len(c)>5 and re.match(r'^\d+$', c[0] or '')]
    return t.header, rows

def get_page(view, r, want_rows=True):
    for attempt in (1,2):
        header, rows = parse(fetch(f'{BASE}&v={view}&r={r}'))
        if rows or not want_rows: return header, rows
        time.sleep(5)
    return header, rows

def main():
    first_html=fetch(f'{BASE}&v=111&r=1')
    m=re.search(r'#\d+\s*/\s*(\d+)\s*Total', first_html)
    if not m: sys.exit('ABORT: no Total count - layout changed or blocked')
    total=int(m.group(1)); npages=(total+19)//20
    print(f'universe total={total} pages={npages}')
    out={}
    for view,(sanity,fields) in VIEWS.items():
        header, rows = get_page(view, 1)
        if header:
            bad=[f'{i}:{header[i] if i<len(header) else "?"}!={name}' for i,name in sanity.items()
                 if i>=len(header) or header[i].lower()!=name.lower()]
            if bad: sys.exit(f'ABORT: view {view} header mismatch [{"; ".join(bad)}] headers={header}')
        else:
            print(f'view {view}: no header row (legacy layout) - relying on value checks')
        got=0
        for p in range(1,npages+1):
            if p>1:
                _, rows = get_page(view, 1+(p-1)*20)
            for c,tk in rows:
                o=out.setdefault(tk,{'t':tk})
                for fld,idx in fields.items():
                    if idx<len(c): o[fld]=c[idx]
            got+=len(rows)
            time.sleep(0.4)
        print(f'view {view}: rows seen={got}, tickers={len(out)}')
    def num(s):
        if s in (None,'-',''): return None
        try: return float(str(s).replace('%','').replace(',',''))
        except ValueError: return None
    def capb(s):
        if not s or s=='-': return None
        v=num(re.sub(r'[TBM]','',s))
        if v is None: return None
        return v*1000 if 'T' in s else v/1000 if 'M' in s else v
    rows=[{'t':o['t'],'n':o.get('n',o['t']),'s':o.get('s',''),'cap':capb(o.get('cap')),
           'pe':num(o.get('pe')),'fpe':num(o.get('fpe')),'peg':num(o.get('peg')),
           'de':num(o.get('de')),'eps':num(o.get('eps')),'hi52':num(o.get('hi'))} for o in out.values()]
    full=[r for r in rows if r['pe'] is not None or r['fpe'] is not None]
    if len(rows) < max(1500, total*0.9) or len(full) < len(rows)*0.7:
        sys.exit(f'ABORT: partial harvest rows={len(rows)} full={len(full)} expected~{total}')
    des=[r['de'] for r in rows if r['de'] is not None]
    his=[r['hi52'] for r in rows if r['hi52'] is not None]
    pes=sorted(r['pe'] for r in rows if r['pe'] is not None)
    med=pes[len(pes)//2] if pes else None
    if not des or sum(1 for v in des if 0<=v<=20)<len(des)*0.6: sys.exit(f'ABORT: D/E values implausible n={len(des)}')
    if not his or sum(1 for v in his if v<=0)<len(his)*0.6: sys.exit(f'ABORT: 52W-high values implausible n={len(his)}')
    if med is None or not (3<med<80): sys.exit(f'ABORT: P/E median implausible {med}')
    data={'asOf':date.today().isoformat(),'universe':'US stocks with market cap >= $2B (Finviz)',
          'count':len(rows),'rows':rows}
    with open('data.json','w') as f: json.dump(data,f,separators=(',',':'),ensure_ascii=False)
    print(f'WROTE data.json rows={len(rows)}')

if __name__=='__main__': main()
