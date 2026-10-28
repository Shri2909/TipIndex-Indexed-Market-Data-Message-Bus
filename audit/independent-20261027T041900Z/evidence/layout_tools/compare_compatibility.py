#!/usr/bin/env python3
"""Functional output comparisons, never interpreted as timing measurements."""
import hashlib,json,struct,subprocess,tempfile
from pathlib import Path
root=Path.cwd(); baseline=root/'build/independent-layout-tools-baseline';changed=root/'build/independent-layout-tools-final';e=root/'audit/independent-20261027T041900Z/evidence/layout_tools'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
results=[]
with tempfile.TemporaryDirectory(prefix='tiplog-layout-compatibility-') as d:
 p=Path(d);trace=p/'tiny.mdt';data=bytearray(64);data[:8]=b'TPLTRC\0\1';struct.pack_into('<I',data,8,1)
 for i in range(64):data.extend(struct.pack('<IHHQ',1,16,0,i)+bytes(range(16)))
 off=len(data);data.extend(struct.pack('<IIH',1,1,5)+b'r/a/e');struct.pack_into('<QQQ',data,16,64,off,len(data)-off);trace.write_bytes(data)
 commands=[('merge_bench',['--diagnostic','--profile=uniform64','--outputs=8','--seed=18446744073709551615']),('publish_bench',['--verify-only','--mix-file',str(root/'configs/m2_payload_mix.csv')]),('index_bench',['--verify-only','--trace',str(trace)])]
 for name,args in commands:
  pairs=[]
  for b in (baseline,changed):
   argv=[str(b/name),*args];r=subprocess.run(argv,text=True,capture_output=True,timeout=30)
   pairs.append(dict(argv=argv,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr,binary_sha256=sha(b/name)))
  equal=pairs[0]['stdout']==pairs[1]['stdout'];assert equal and all(row['returncode']==0 for row in pairs)
  results.append(dict(name=name,byte_identical_stdout=equal,runs=pairs))
 # This nonempty original fixture specifically proves the M3 verify-only gap.
 pairs=[]
 for b in (baseline,changed):
  argv=[str(b/'index_bench'),'--verify-only','--trace',str(trace),'--unknown-option'];r=subprocess.run(argv,text=True,capture_output=True,timeout=30)
  pairs.append(dict(argv=argv,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr,binary_sha256=sha(b/'index_bench')))
 assert pairs[0]['returncode']==0 and pairs[1]['returncode']!=0
 results.append(dict(name='index_nonempty_unknown_verification',runs=pairs))
(e/'functional-compatibility.json').write_text(json.dumps(results,indent=2)+'\n')
