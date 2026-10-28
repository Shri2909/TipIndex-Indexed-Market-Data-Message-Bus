#!/usr/bin/env python3
"""Validate exact pinned-source patching, no-op reconfiguration, and rejection."""
import hashlib,json,subprocess,tempfile
from pathlib import Path
root=Path.cwd(); original=root/'build/independent-layout-tools-baseline/_deps/benchmark-src/src/benchmark.cc'
patch=root/'cmake/benchmark_output_patch.cmake'; archive=root/'build/downloads/benchmark-1.9.5.tar.gz'
sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
rows=[];archive_before=sha(archive)
with tempfile.TemporaryDirectory(prefix='tiplog-benchmark-patch-') as d:
 base=Path(d); source=base/'src/benchmark.cc';source.parent.mkdir();source.write_bytes(original.read_bytes())
 for label in ('original','idempotence','unexpected'):
  if label=='unexpected':source.write_bytes(source.read_bytes()+b'\n// changed\n')
  before=sha(source); mtime=source.stat().st_mtime_ns
  argv=['cmake','-Dbenchmark_SOURCE_DIR='+str(base),'-DBENCHMARK_ENABLE_EXCEPTIONS=ON','-P',str(patch)]
  r=subprocess.run(argv,text=True,capture_output=True,timeout=30)
  rows.append(dict(label=label,argv=argv,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr,before=before,after=sha(source),mtime_unchanged=mtime==source.stat().st_mtime_ns))
 assert rows[0]['returncode']==0 and rows[0]['before']=='93dd058ff126b0e50f53f8d5d31d6fa5132b345b3132781c692b7d8538c72da3'
 assert rows[0]['after']=='4fc57e51c4bf1aa76e8c61bc4538f4a00fce0f03dd96e8f8ba577870da16fce8'
 assert rows[1]['returncode']==0 and rows[1]['mtime_unchanged']
 assert rows[2]['returncode']!=0 and rows[2]['before']==rows[2]['after']
assert sha(archive)==archive_before=='f82705a2726d8f6cdcda274b841f6314dbfc6f731cdda06c946f310ec1cc3ad9'
(root/'audit/independent-20261027T041900Z/evidence/layout_tools/dependency-patch-check.json').write_text(json.dumps(dict(cases=rows,archive_before=archive_before,archive_after=sha(archive)),indent=2)+'\n')
