from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
p=ROOT/'collector.py'
text=p.read_text(encoding='utf-8')

repls=[
("        self._capture_ref = False\n        self._ref_tag = None\n        self._ref_parts = []\n",
 "        self._capture_ref = False\n        self._ref_tag = None\n        self._ref_parts = []\n        self._capture_subtitle = False\n        self._subtitle_tag = None\n        self._subtitle_parts = []\n"),
("            self._card = {\"text\": [], \"anchors\": [], \"location\": None, \"posted\": None, \"ref\": None}\n",
 "            self._card = {\"text\": [], \"anchors\": [], \"location\": None, \"posted\": None, \"ref\": None, \"subtitle\": None}\n"),
("            if \"list-item-ref\" in classes:\n                self._capture_ref = True\n                self._ref_tag = tag\n                self._ref_parts = []\n",
 "            if \"list-item-ref\" in classes:\n                self._capture_ref = True\n                self._ref_tag = tag\n                self._ref_parts = []\n            if \"article__header__text__subtitle\" in classes:\n                self._capture_subtitle = True\n                self._subtitle_tag = tag\n                self._subtitle_parts = []\n"),
("        if self._capture_ref:\n            self._ref_parts.append(data)\n",
 "        if self._capture_ref:\n            self._ref_parts.append(data)\n        if self._capture_subtitle:\n            self._subtitle_parts.append(data)\n"),
("        if self._capture_ref and tag == self._ref_tag:\n            self._card[\"ref\"] = \" \".join(\" \".join(self._ref_parts).split()) or None\n            self._capture_ref = False\n            self._ref_tag = None\n            self._ref_parts = []\n",
 "        if self._capture_ref and tag == self._ref_tag:\n            self._card[\"ref\"] = \" \".join(\" \".join(self._ref_parts).split()) or None\n            self._capture_ref = False\n            self._ref_tag = None\n            self._ref_parts = []\n        if self._capture_subtitle and tag == self._subtitle_tag:\n            self._card[\"subtitle\"] = \" \".join(\" \".join(self._subtitle_parts).split()) or None\n            self._capture_subtitle = False\n            self._subtitle_tag = None\n            self._subtitle_parts = []\n"),
("    location = clean_text(card.get(\"location\"))\n    posted = clean_text(card.get(\"posted\"))\n",
 "    location = clean_text(card.get(\"location\")) or clean_text(card.get(\"subtitle\"))\n    posted = clean_text(card.get(\"posted\"))\n"),
]
for old,new in repls:
    if old not in text:
        raise SystemExit('expected collector patch fragment missing: '+old[:80])
    text=text.replace(old,new,1)
p.write_text(text,encoding='utf-8')

mp=ROOT/'ats_mapping_jw2.json'
data=json.loads(mp.read_text(encoding='utf-8'))
rows=[x for x in data.get('companies',[]) if x.get('company')=='Bain & Company']
if len(rows)!=1: raise SystemExit(f'Bain mapping count={len(rows)}')
r=rows[0]; ats=r.setdefault('ats',{}); ats['inventory_url']='https://careers.bain.com/jobs/SearchJobs'
v=r.setdefault('verification',{})
v.update({
 'level':'FULL',
 'method':'official_avature_searchjobs_exact_reconciliation',
 'location_filter_supported':True,
 'total_count_available':True,
 'full_inventory_possible':True,
 'pagination':'Server-rendered SearchJobs inventory; tenant-fixed page size 10; zero-based folderOffset; numeric stable FolderDetail ID.'
})
r['job_watch_method']={
 'primary':'Enumerate Bain official Avature SearchJobs through every folderOffset page; require exact range/total reconciliation, unique stable IDs, stable reread, and structured article subtitle location.',
 'fallback':'If the public inventory is capped, unstable, blocked, or loses structured location metadata, return NOT_CHECKED.'
}
r['limitations']=[
 'Validated from GitHub Actions on 2026-09-15: 281 declared results, 281 result cards, 281 unique stable FolderDetail IDs across 29 pages, with no overlap/gap and stable total/first page on reread.',
 'The official enumerable inventory is https://careers.bain.com/jobs/SearchJobs; the marketing Find a Role page is not used for completeness proof.',
 'Location is structurally exposed by the Bain Avature theme in article__header__text__subtitle.',
 'folderRecordsPerPage is tenant-fixed at 10; exhaustive pagination uses folderOffset.'
]
r['last_mapped']='2026-09-15'
levels={'FULL':0,'STRONG':0,'PARTIAL':0,'OPAQUE':0}
for x in data.get('companies',[]):
    lvl=((x.get('verification') or {}).get('level'))
    if lvl in levels: levels[lvl]+=1
s=data.setdefault('summary',{});s['companies_analyzed']=len(data.get('companies',[]));s.update(levels)
mp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Bain Avature theme/mapping augmentation applied')
