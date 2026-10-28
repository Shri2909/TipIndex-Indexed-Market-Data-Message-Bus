#!/usr/bin/env python3
"""Bounded source/input safety probes. Only private temporary inputs are modified."""
import hashlib,json,os,struct,subprocess,sys,tempfile
from pathlib import Path
binary=Path(sys.argv[1]).resolve()
output=Path(sys.argv[2])
rows=[]
with tempfile.TemporaryDirectory(prefix='tiplog-independent-tools-') as temporary:
 root=Path(temporary)
 mix=root/'mix.csv'; mix.write_text('type,payload_bytes,count\nA,12,1\n')
 case=root/'case.tsv'; case.write_text('CASE\tone\t1\nCOST\t1\t0\t0\nNODE\t-\t1\tr\nEND\n')
 trace=root/'trace.mdt'; data=bytearray(64);data[:8]=b'TPLTRC\0\1';struct.pack_into('<I',data,8,1);data.extend(struct.pack('<IIH',1,1,5)+b'r/a/e');struct.pack_into('<QQQ',data,16,0,64,len(data)-64);trace.write_bytes(data)
 def run(label,name,args,source=None,env=None):
  before=source.read_bytes() if source else None
  argv=[str(binary/name),*map(str,args)]
  p=subprocess.run(argv,text=True,capture_output=True,timeout=30,env=env)
  after=source.read_bytes() if source else None
  rows.append(dict(label=label,argv=argv,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,source_unchanged=before==after,binary_sha256=hashlib.sha256((binary/name).read_bytes()).hexdigest()))
 for name in ['tiplog_layout','tiplog_layout_runtime']:
  source=root/(name+'.tsv');source.write_bytes(case.read_bytes());alias=root/(name+'.hardlink');alias.hardlink_to(source)
  run(name+'_hardlink',name,['--input',source,'--output',alias,'--methods','base'],source)
 source=root/'requests.tsv';source.write_text('one\tT1\t0\tsubtree:synth\tscan\tquad\trepeat-warm\t64\t1\n')
 run('bench_requests_alias','tiplog_bench',['--synthetic','--records','1','--partitions','2','--mix',mix,'--ring-bytes','8192','--requests',source,'--output',source],source)
 run('bench_requests_read_error','tiplog_bench',['--synthetic','--records','1','--partitions','2','--mix',mix,'--ring-bytes','8192','--requests',root,'--output',root/'readerror.jsonl'])
 run('merge_numeric_suffix','merge_bench',['--diagnostic','--profile=uniform64','--outputs=8garbage'])
 run('merge_signed_seed','merge_bench',['--diagnostic','--profile=uniform64','--outputs=8','--seed=-1'])
 for name,args in [('merge_bench',['--diagnostic','--profile=uniform64','--outputs=8','--unknown-option']),('publish_bench',['--verify-only','--mix-file',mix,'--unknown-option']),('index_bench',['--verify-only','--trace',trace,'--unknown-option'])]:
  run(name+'_unknown_verify_argument',name,args)
output.write_text(json.dumps(rows,indent=2)+'\n')
