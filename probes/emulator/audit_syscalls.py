"""Inventory FX syscall coverage, including undocumented slots; no web in CI.

--import-index PATH refreshes the factual catalog from Simon Lothar's legacy
HTML index. This catalog is NOT a complete or verified GIII 03.70 OS ABI.
Run prepare_sources.py first; --check verifies the checked-in report.
"""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re

BASE=Path(__file__).resolve().parent
URL='https://media.taricorp.net/prizm/simon_chm/fx_legacy_syscalls.htm'
PARTIAL={0x003,0x01c,0x01d,0x01e,0x139,0x13a,0x13b,0x1e7,0x80e,0x80f,0x811,0x812}


def import_index(path):
    raw=path.read_bytes();text=raw.decode('utf8',errors='replace');items={}
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',text,re.I|re.S):
        cells=re.findall(r'<td\b[^>]*>(.*?)</td>',row,re.I|re.S)
        clean=lambda s:' '.join(html.unescape(re.sub(r'<[^>]+>','',s)).split())
        if len(cells)<2:continue
        number=clean(cells[0]);m=re.fullmatch(r'0x([\da-fA-F]+)(?:\.\.0x([\da-fA-F]+))?',number)
        if not m:continue
        lo=int(m[1],16);hi=int(m[2],16) if m[2] else lo
        if clean(cells[1])=='Name':continue  # placeholder, not documented ABI
        links=re.findall(r'href=["\']([^"\']+)',row,re.I)
        for n in range(lo,hi+1):
            items[str(n)]={'name':clean(cells[1]),'dataEntry':'no syscall' in clean(row).lower(),
                           'reference':URL.rsplit('/',1)[0]+'/'+links[0] if links and not links[0].startswith('#') else URL}
    data={'source':URL,'sha256':hashlib.sha256(raw).hexdigest(),
          'scope':'Historical FX 1.x/2.00 index; not verified exhaustive for GIII 03.70',
          'entries':items}
    (BASE/'syscall-catalog.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def report():
    catalog=json.loads((BASE/'syscall-catalog.json').read_text('utf8'))
    source=(BASE/'build/patched/os/syscalls.c').read_text()
    table=source.split('static const Syscall SYSCALLS_FX[] = {',1)[1].split('};',1)[0]
    entries={}
    for num,name,fn in re.findall(r'\{0x([\dA-Fa-f]+),\s*"([^"]+)",\s*(\w+)\}',table):
        n=int(num,16)
        if n in entries:raise ValueError(f'duplicate FX syscall {n:04x}')
        entries[n]=(name,fn)
    out=[]
    # Historical table end, not a claim that the GIII has no later slots.
    for n in range(0x1033):
        doc=catalog['entries'].get(str(n))
        row={'number':f'0x{n:04X}','status':'documented-unimplemented' if doc else 'undocumented'}
        if doc:
            row.update(name=doc['name'],reference=doc['reference'])
            if doc['dataEntry']:row['status']='data-entry-unimplemented'
        if n in entries:
            name,fn=entries[n];row.update(name=name,handler=fn)
            row['status']='stub' if fn=='sc_nothing' else 'partial' if n in PARTIAL else 'hle-handler'
        out.append(row)
    return {'scope':catalog['scope'],'slotsAudited':len(out),'documentedEntries':len(catalog['entries']),
            'dispatchEntries':len(entries),'counts':dict(sorted(Counter(x['status'] for x in out).items())),
            'meaning':'hle-handler means executable code, NOT full OS equivalence or device validation',
            'entries':out}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--import-index',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    if a.import_index:import_index(a.import_index)
    r=report();text=json.dumps(r,ensure_ascii=False,indent=2)+'\n';dest=BASE/'syscall-coverage.json'
    if a.check:
        if dest.read_text('utf8')!=text:raise SystemExit('syscall coverage is stale; regenerate it')
    else:dest.write_text(text,encoding='utf8')
    print(json.dumps({k:v for k,v in r.items() if k!='entries'},ensure_ascii=False))


if __name__=='__main__':main()
