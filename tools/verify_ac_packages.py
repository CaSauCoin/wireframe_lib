import json,sys,sqlite3,subprocess,hashlib,os
from pathlib import Path
os.chdir(Path(__file__).resolve().parents[2])
sys.path.insert(0,'WireFrame/Tools')
from libcheck.tree import BuiltTree
from libcheck.checks import structural,visual
from dataclasses import asdict
def main():
    p=Path('wireframe_lib/Dist_Repo/v2'); catalog=json.loads(Path('wireframe_lib/collections/ac/catalog.json').read_text()); additions={e['id'] for e in catalog['additions']}
    tree=BuiltTree(p); new_rows=[r for r in tree.shard_rows if r.data['id'] in additions]
    tree.part_zip_names={r.slug+'.zip' for r in new_rows}
    tree.preview_names={Path(r.url_path(k,tree.base_url)).name for r in new_rows for k in ['preview_sym','preview_fp'] if r.data.get(k)}
    results=[]
    for check in [structural,visual]:
     result=check.run(tree,sample=0,**({'workers':4} if check is visual else {}));results.append(asdict(result));print(check.__name__,result.errors,'errors',result.warnings,'warnings',flush=True)
     for f in result.findings:
      if f.severity!='info':print(f.message,f.sample,flush=True)
    entries={r.data['id']:r.data for r in tree.shard_rows}
    old_count=0
    for f in (p/'shards').glob('*.json'):
     data=subprocess.check_output(['git','-C','wireframe_lib','show',catalog['baseline_commit']+':Dist_Repo/v2/shards/'+f.name],text=True)
     for entry in json.loads(data)['entries']:
      assert entries[entry['id']]==entry,entry['id']
      old_count+=1
    assert old_count==catalog['before']
    conn=sqlite3.connect(p/'lib_search.sqlite'); assert conn.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert conn.execute('select count(*) from part').fetchone()[0]==len(entries)==tree.manifest['counts']['total']
    assert conn.execute('select count(*) from part_fts').fetchone()[0]==len(entries)
    assert not conn.execute('select id from part group by id having count(*)>1').fetchall()
    searches={}
    for name in ['MOC3021M','MOC3063M','HLK-PM01','IRM-05-5','GBU8K','BTA16-600B','G5LE-1','ACS712xLCTR-05B']:
     rows=conn.execute('SELECT p.id FROM part_fts JOIN part p ON p.id=part_fts.part_id WHERE part_fts MATCH ? AND p.name=?', ('"'+name+'"',name)).fetchall()
     searches[name]=len(rows); assert rows,name
    for row in new_rows:
     archive=p/'parts'/(row.slug+'.zip');assert hashlib.sha256(archive.read_bytes()).hexdigest()==row.data['hash']
    assert {r.data['id'] for r in new_rows}==additions
    report={'new_parts':len(new_rows),'existing_entries_preserved':old_count,'total':len(entries),'fts_queries':searches,'results':results}
    Path('wireframe_lib/collections/ac/validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
    assert not any(r['findings'] and any(f['severity']=='error' for f in r['findings']) for r in results)

if __name__=='__main__':
    main()
