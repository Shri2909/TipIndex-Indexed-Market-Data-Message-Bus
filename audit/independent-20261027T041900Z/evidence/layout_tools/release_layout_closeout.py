#!/usr/bin/env python3
"""Current Release CC5/example verification without rewriting historical evidence."""
import hashlib,json,subprocess,time
from pathlib import Path
root=Path.cwd();e=root/'audit/independent-20261027T041900Z/evidence/layout_tools';b=root/'build/independent-layout-tools-final'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
commands=[('cc5',[str(b/'tiplog_layout_cc5'),'--instances','10000','--seed','20191230','--output',str(e/'cc5-release.json')],root/'results/p7/cc5-release.json'),
          ('example',[str(b/'tiplog_layout_example'),'--output',str(e/'worked-example.json')],root/'results/p7/worked-example.json')]
rows=[]
for label,argv,historical in commands:
 start=time.monotonic();r=subprocess.run(argv,text=True,capture_output=True,timeout=180)
 output=Path(argv[-1]); before=json.loads(historical.read_text()); after=json.loads(output.read_text()) if output.exists() else None
 row=dict(label=label,argv=argv,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr,wall_seconds=time.monotonic()-start,binary_sha256=sha(Path(argv[0])),output_sha256=sha(output) if output.exists() else None,historical_path=str(historical),historical_sha256=sha(historical),json_equal_to_historical=before==after,bytes_equal_to_historical=output.read_bytes()==historical.read_bytes() if output.exists() else False)
 rows.append(row)
 assert r.returncode==0 and not r.stderr and before==after,row
sources=list((root/'src/tiplog/layout').glob('*'))+[root/'tools/tiplog_layout/worked_example.cpp',root/'tests/layout/layout_cc5.cpp']
(e/'release-layout-closeout.json').write_text(json.dumps(dict(commands=rows,source_identities=[dict(path=str(p.relative_to(root)),sha256=sha(p)) for p in sources if p.is_file()]),indent=2)+'\n')
