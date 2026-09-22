#!/usr/bin/env python3
"""Add physical interface connectors without guessing cable wiring or protocol pinouts."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import zipfile
from collections import Counter
from pathlib import Path
import add_ac_packages as common
from libforge import legacy_lib

ROOT=common.ROOT
COLLECTION=ROOT/'collections/interfaces'
SOURCE=ROOT/'sources/interface-packages'
LICENSE='CC-BY-SA-4.0 WITH KiCad-Libraries-exception'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def family(m):
    src=m.get('source',{})
    if not isinstance(src,dict):return ''
    if not (src.get('library','').startswith(('Connector','SparkFun-Connector','dk_')) and m.get('class','').startswith('connector')):return ''
    text=' '.join([m.get('name',''),m.get('description',''),(m.get('footprint') or {}).get('name','')])
    for pattern,group in [(r'HDMI','hdmi'),(r'DisplayPort','displayport'),(r'\bDVI','dvi'),(r'PCI.?Express|PCIe|mini.?PCI','pcie'),(r'M\.2','m2'),(r'\be?SATA','sata'),(r'FFC|FPC','ffc_fpc'),(r'\bUSB','usb'),(r'\bU[.]FL|\bI-PEX|\bIPEX','rf_coax')]:
        if re.search(pattern,text,re.I):return group
    return ''

def build_templates(repos,out):
    specs=[('Connector_FFC-FPC','*.kicad_mod','ffc_fpc'),
           ('Connector_Video','*HDMI*.kicad_mod','hdmi'),
           ('Connector_SATA_SAS','SATA_*.kicad_mod','sata'),
           ('Connector_PCBEdge','M.2_*.kicad_mod','m2_card_edge'),
           ('Connector_PCBEdge','BUS_PCI_Express_Mini*.kicad_mod','mini_pcie'),
           ('Connector_USB','*.kicad_mod','usb')]
    parts=[];provenance=[];groups={}
    for library,pattern,group in specs:
        for path in sorted((repos/'kicad-footprints'/(library+'.pretty')).glob(pattern)):
            fp=common.parse.parse_footprint_file(path)
            if not fp or not fp.electrical_designators:raise ValueError(f'No contacts: {path}')
            name=f'Contacts__{fp.name}'
            body=f'{fp.descr}. Numbered physical connector contacts; assign protocol signals from the target board pinout. Cable wiring, interface generation and bandwidth are not specified.'
            if group=='m2_card_edge':body+=' Card-side edge contacts, not a motherboard socket footprint.'
            keywords=[group,'connector','numbered','contacts',fp.name]
            if group=='ffc_fpc' and fp.pad_count in {15,22,24,30,40}:keywords+=['camera','display','MIPI','candidate','board-specific-pinout']
            pins=[{'number':n,'name':('SHIELD' if n.lower() in {'sh','shield'} else 'MOUNT' if n.lower()=='mp' else n),'type':'passive','unit':1} for n in sorted(fp.all_designators,key=lambda n:(not n.isdigit(),int(n) if n.isdigit() else n))]
            src_fp=SOURCE/(library+'.pretty')/path.name;src_fp.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,src_fp)
            src_sym=SOURCE/'symbols'/(name+'.kicad_sym');src_sym.parent.mkdir(parents=True,exist_ok=True)
            url_match=re.search(r'https?://[^\s)]+',fp.descr)
            record=common.PartRecord(id=f'wireframe-interface-packages/Interface_Connectors/{name}',name=name,
                source='wireframe-interface-packages',source_rank=100,library='Interface_Connectors',license=LICENSE,
                symbol_path=str(src_sym),footprint_path=str(src_fp),description=body,description_origin='rules',
                keywords=keywords,datasheet=url_match[0] if url_match else '',reference='J',value=name,
                pin_count=fp.pad_count,named_pins=fp.pad_count,pins=pins,footprint_name=fp.name,footprint_library=library,
                declared_footprint=library+':'+fp.name,pad_count=fp.pad_count,mount=fp.mount,pitch_mm=fp.pitch_mm,
                courtyard_mm=fp.courtyard,body_mm=fp.body,footprint_descr=fp.descr,footprint_tags=fp.tags,
                footprint_method='explicit_generic',tier='B',score=70,flags=['physical_contacts_protocol_unspecified'],named_pin_ratio=1.0)
            src_sym.write_text(legacy_lib.to_kicad_sym(record))
            part=common.EnrichedPart(record,'connector',['Connector'],body+' '+' '.join(keywords),[],[])
            parts.append(part);groups[record.id]=group
            provenance.append({'id':record.id,'family':group,'symbol':str(src_sym.relative_to(ROOT)),
                'footprint':str(src_fp.relative_to(ROOT)),'upstream_footprint':f'kicad-footprints/{library}.pretty/{path.name}',
                'footprint_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'symbol_sha256':hashlib.sha256(src_sym.read_bytes()).hexdigest(),
                'contact_count':fp.pad_count,'contact_side_description':fp.descr})
    images,_=common.preview.render(parts,out,workers=4,progress=print)
    if any(not images.get(common.package.part_slug(p),{}).get(k) for p in parts for k in ('sym','fp')):raise ValueError('Missing template previews')
    common.package.write_part_zips(parts,out,include_3d=False,previews=images,progress=print)
    (SOURCE/'PROVENANCE.json').write_text(json.dumps({'schema':1,'license':LICENSE,
        'upstream_commit':subprocess.check_output(['git','-C',str(repos/'kicad-footprints'),'rev-parse','HEAD'],text=True).strip(),
        'policy':'Unmodified KiCad physical footprints with explicitly numbered passive contact symbols. No protocol or cable compatibility inferred.',
        'parts':provenance},indent=2)+'\n')
    return groups

def update_indexes(out,entries,manifest,additions):
    base=manifest['base_url'];all_parts=[]
    for e in entries.values():
        path=out/'parts'/(e['slug']+'.zip')
        with zipfile.ZipFile(path) as z:
            m=json.loads(z.read('part.json')) if 'part.json' in z.namelist() else {}
            if not all(k in m for k in ('symbol','quality')):m=common.legacy_manifest(z,e)
        all_parts.append(common.as_part(m,path,e))
    # Modify only the connector shard. Other groups retain their existing bytes.
    path=out/'shards/connector.json';shard=json.loads(path.read_text());shard['entries']=[e for e in entries.values() if e['class'].split('.')[0]=='connector'];shard['count']=len(shard['entries']);shard['generated_at']=common.package._now()
    path.write_text(json.dumps(shard,indent=2))
    clusters=common.cluster.cluster_parts(all_parts);counts=common.cluster.write_clusters(clusters,out)
    common.package.write_search_index(all_parts,out/'lib_search.sqlite',base,clusters,packaged_models={e['slug'] for e in entries.values() if e.get('has_3d')})
    with sqlite3.connect(out/'lib_search.sqlite') as conn:conn.executemany('UPDATE part SET slug=?,download_url=? WHERE id=?',[(e['slug'],e['download_url'],e['id']) for e in entries.values()])
    visible=[p for p in all_parts if p.record.tier in {'A','B','G'}]
    manifest['generated_at']=common.package._now();manifest['counts']={'total':len(entries),'planner_visible':len(visible),
        'by_tier':dict(Counter(p.record.tier for p in all_parts)),'by_source':dict(Counter(p.record.source for p in all_parts)),
        'with_description':sum(bool(p.record.description) for p in visible),'with_footprint':sum(bool(p.record.footprint_name) for p in visible),
        'with_3d':sum(bool(e.get('has_3d')) for e in entries.values() if e['tier'] in {'A','B','G'}),
        'description_origin':dict(Counter(p.record.description_origin for p in visible))}
    for s in manifest['shards']:
        if s['name']=='connector':s['count']=shard['count']
    manifest['clusters']={'index':'clusters/index.json','count':len(clusters),'by_class':counts}
    if not any(s['name']=='wireframe-interface-packages' for s in manifest['sources']):
        manifest['sources'].append({'name':'wireframe-interface-packages','license':LICENSE,'url':'https://github.com/CaSauCoin/wireframe_lib/tree/main/sources/interface-packages','rank':100,'commit':'','provenance':'sources/interface-packages/PROVENANCE.json'})
        with (out/'LICENSES.md').open('a') as f:f.write('\n## WireFrame interface connector packages\n\nUnmodified KiCad footprints and project-authored numbered contact symbols. CC-BY-SA-4.0 WITH KiCad-Libraries-exception; see sources/interface-packages/PROVENANCE.json. No protocol or cable compatibility is inferred.\n')
    (out/'lib_index.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    cp=out/'compat/lib_index.json';compat=json.loads(cp.read_text());by_slug={e['slug']:e for e in entries.values()};present={e['id'] for e in compat['libraries']}
    for e in additions:
        if e['slug'] not in present:
            compat['libraries'].append({'id':e['slug'],'name':e['name'],'category':e['class'],'download_url':e['download_url'],'hash':e['hash'],'preview_sym':e['preview_sym'],'preview_fp':e['preview_fp'],'components':[{'type':'sym'},{'type':'fp'}]+([{'type':'3d'}] if e['has_3d'] else [])})
    for e in compat['libraries']:
        if e['id'] in by_slug and by_slug[e['id']]['source']=='wireframe-interface-packages':e['hash']=by_slug[e['id']]['hash']
    compat['generated_at']=common.package._now();cp.write_text(json.dumps(compat,indent=2))

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--templates',action='store_true');ap.add_argument('--repos',type=Path,default=Path.home()/'.wireframe/library_cache/repos');args=ap.parse_args()
    out=ROOT/'Dist_Repo/v2';manifest=json.loads((out/'lib_index.json').read_text());entries={e['id']:e for f in sorted((out/'shards').glob('*.json')) for e in json.loads(f.read_text())['entries']}
    before={k:dict(v) for k,v in entries.items()};COLLECTION.mkdir(parents=True,exist_ok=True)
    prior_path=COLLECTION/'catalog.json';prior=json.loads(prior_path.read_text()) if prior_path.exists() else {}
    groups=build_templates(args.repos,out) if args.templates else {}
    prov=SOURCE/'PROVENANCE.json'
    if prov.exists():groups.update({p['id']:p['family'] for p in json.loads(prov.read_text())['parts']})
    added=[];deferred=[];selected=[];existing_issues=[]
    for path in sorted((out/'parts').glob('*.zip')):
        # Only physical connector libraries, never interface ICs or compute modules.
        fields=path.stem.split('__')
        if len(fields)<3 or not fields[1].startswith(('Connector','SparkFun-Connector','dk_USB-DVI','dk_Coaxial','Interface_Connectors')):continue
        with zipfile.ZipFile(path) as z:
            if 'part.json' not in z.namelist():continue
            m=json.loads(z.read('part.json'));group=groups.get(m.get('id'),family(m))
            if not group:continue
            if m['id'] in before:
                reason=common.validate(z,m)
                if reason:existing_issues.append({'id':m['id'],'reason':reason})
                if m['source']['name']=='wireframe-interface-packages':entries[m['id']]['hash']=hashlib.sha256(path.read_bytes()).hexdigest()
                selected.append({'id':m['id'],'family':group,'status':'existing'});continue
            reason=common.validate(z,m)
            if reason:
                deferred.append({'id':m['id'],'family':group,'reason':reason});continue
            part=common.as_part(m,path);slug=common.package.part_slug(part)
            if slug!=path.stem:raise ValueError(f'slug mismatch: {path}')
            images={}
            for kind,field in [('sym','symbol'),('fp','footprint')]:
                name=(m.get('previews') or {}).get(field)
                if name and name in z.namelist():
                    dest=out/'previews'/f'{slug}_{kind}.png'
                    if not dest.exists():dest.write_bytes(z.read(name))
                    images[kind]=str(dest.relative_to(out))
            models={slug} if (m.get('model3d') or {}).get('file') in z.namelist() else set()
            entry=common.package.index_entry(part,manifest['base_url'],slug,hashlib.sha256(path.read_bytes()).hexdigest(),images,manifest['parts_base_url'],models)
            entries[m['id']]=entry;added.append(entry);selected.append({'id':m['id'],'family':group,'status':'added'})
    update_indexes(out,entries,manifest,added)
    all_added={e['id']:e for e in prior.get('additions',[])}
    for e in added:all_added[e['id']]={'id':e['id'],'slug':e['slug'],'family':next(x['family'] for x in selected if x['id']==e['id'])}
    for e in selected:
        if e['id'] in all_added:e['status']='added'
    initial={k:v for k,v in before.items() if k not in all_added}
    report={'schema':1,'scope':'Physical connector packages; no cable assembly or protocol generation certification.',
        'before':prior.get('before',len(before)),'after':len(entries),'added':len(all_added),
        'baseline_entries_sha256':prior.get('baseline_entries_sha256',digest(initial)),
        'by_family':dict(Counter(e['family'] for e in all_added.values())),
        'additions':list(all_added.values()),'selected':selected,'deferred':deferred,'existing_issues':existing_issues}
    prior_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['before','after','added','by_family']},indent=2));print('Deferred',len(deferred),'existing issues',len(existing_issues))

if __name__=='__main__':main()
