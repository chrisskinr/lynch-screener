#!/usr/bin/env python3
"""Refresh data.json: harvest all US stocks >=$2B from Finviz (3 views), write data.json.
Aborts (exit 1) without writing if the harvest looks partial/blocked."""
import json, re, sys, time, urllib.request
from datetime import date
from html.parser import HTMLParser

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml', 'Accept-Language': 'en-US,en;q=0.9'}
BASE = 'https://finviz.com/screener.ashx?f=cap_midover&ft=4&o=ticker'

class Table(HTMLParser):
    """Collect rows of the screener table: list of (cells:list[str], last_anchor_text:str)."""
    def __init__(self):
        super().__init__(); self.rows=[]; self.cells=[]; self.cur=None; self.in_table=False
        self.anchor=None; self.in_a=False; self.depth=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='table' and 'screener_table' in a.get('class',''): self.in_table=True; self.depth=0
        if not self.in_table: return
        if tag=='table': self.depth+=1
        if tag=='tr' and self.depth<=1: self.cells=[]; self.anchor=None
        if tag=='td' and self.depth<=1: self.cur=''
        if tag=='a' and self.cur is not None: self.in_a=True; self._atext=''
    def handle_endtag(self,tag):
        if not self.in_table: return
        if tag=='table':
            self.depth-=1
            if self.depth<0: self.in_table=False
        if tag=='a' and self.in_a:
            self.in_a=False
            if self._atext.strip(): self.anchor=self._atext.strip()
        if tag=='td' and self.cur is not None: self.cells.append(self.cur.strip()); self.cur=None
        if tag=='tr' and self.cells: self.rows.append((self.cells,self.anchor)); self.cells=[]
    def handle_data(self,d):
        if self.cur is not None: self.cur+=d
        if self.in_a: self._atext+=d

def fetch(url, tries=3):
    for i in range(tries):
        try:
            req=urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r: return r.read().decode('utf-8','ignore')
        except Exception as e:
            if i==tries-1: raise
            time.sleep(2*(i+1))

def pages(view):
    html=fetch(f'{BASE}&v={view}&r=1')
    m=re.search(r'#\d+\s*/\s*(\d+)\s*Total', html)
    if not m: sys.exit('ABORT: no Total count — page layout changed or blocked')
    total=int(m.group(1))
    return total, (total+19)//20, html

def rows_of(html):
    t=Table(); t.feed(html)
    return [(c,a) for c,a in t.rows if a and len(c)>5 and re.match(r'^\d+$', c[0] or '')]

def main():
    out={}
    total, npages, first = pages(111)
    print(f'universe total={total} pages={npages}')
    for view in (111,121,161):
        for p in range(1,npages+1):
            html = first if (view==111 and p==1) else fetch(f'{BASE}&v={view}&r={1+(p-1)*20}')
            for cells,tk in rows_of(html):
                o=out.setdefault(tk,{'t':tk})
                if view==111: o['n']=cells[2]; o['s']=cells[3]; o['cap']=cells[6]
                elif view==121: o['pe']=cells[3]; o['fpe']=cells[4]; o['peg']=cells[5]; o['eps']=cells[10]
                elif view==161: o['de']=cells[10]
            time.sleep(0.35)
        print(f'view {view} done, rows={len(out)}')
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
           'de':num(o.get('de')),'eps':num(o.get('eps'))} for o in out.values()]
    full=[r for r in rows if r['pe'] is not None or r['fpe'] is not None]
    if len(rows) < max(1500, total*0.9) or len(full) < len(rows)*0.7:
        sys.exit(f'ABORT: partial harvest rows={len(rows)} full={len(full)} expected~{total}')
    data={'asOf':date.today().isoformat(),'universe':'US stocks with market cap ≥ $2B (Finviz)',
          'count':len(rows),'rows':rows}
    with open('data.json','w') as f: json.dump(data,f,separators=(',',':'),ensure_ascii=False)
    print(f'WROTE data.json rows={len(rows)}')

if __name__=='__main__': main()
