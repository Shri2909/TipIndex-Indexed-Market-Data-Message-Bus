#!/usr/bin/env python3
"""Execute instrumented P6 CC2 regression coverage and compare outcome-aware mode digests."""
import concurrent.futures,datetime,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
MODES=[('scan','stdpq')]+[(mode,kernel) for mode in ('indexed','auto') for kernel in ('stdpq','binheap','quad','loser')]
EXCLUDE={'mode','kernel','elapsed_monotonic_seconds','effective_indexed_opens','effective_scan_opens','multicursor_opens','indexed_execution_batches','scan_execution_batches'}
def run(task):
 preset,seeds,mode,kernel,cpu=task
 label=f'CC2-{preset}-{mode}-{kernel}'
 cmd=[sys.executable,'scripts/run_check.py','p6',label,'--','taskset','-c',str(cpu),f'build/{preset}/tiplog_differential','--seeds',str(seeds),'--operations','10000','--seed-base','20191230','--mode',mode,'--kernel',kernel]
 result=subprocess.run(cmd,cwd=ROOT)
 records=sorted((ROOT/'results/p6').glob(label+'-*.json')); record=records[-1]
 saved=json.loads(record.read_text()); payload=None
 if result.returncode==0:
  lines=(ROOT/saved['log']).read_text().splitlines();payload=json.loads(next(line for line in reversed(lines) if line.startswith('{')))
  assert payload['seeds']==seeds and payload['operations_per_seed']==10000
  assert payload['operations']==seeds*10000 and payload['status']=='passed'
 return {'preset':preset,'mode':mode,'kernel':kernel,'record':str(record.relative_to(ROOT)),'exit_code':result.returncode,'result':payload}
def main():
 tasks=[(preset,seeds,mode,kernel,8+i%3) for preset,seeds in [('release',1000),('asan-ubsan',200)] for i,(mode,kernel) in enumerate(MODES)]
 # Separate worker queues keep CPU8/9/10 exclusive per concurrent child.
 queues=[[t for t in tasks if t[-1]==cpu] for cpu in (8,9,10)]
 def queue(tasks): return [run(task) for task in tasks]
 rows=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  for future in concurrent.futures.as_completed([pool.submit(queue,q) for q in queues]):rows.extend(future.result())
 checks={}
 for preset in ('release','asan-ubsan'):
  selected=[r for r in rows if r['preset']==preset]
  checks[preset+':nine_successes']=len(selected)==9 and all(r['exit_code']==0 for r in selected)
  if checks[preset+':nine_successes']:
   canonical=[{k:v for k,v in r['result'].items() if k not in EXCLUDE} for r in selected]
   checks[preset+':identical_output_and_outcome']=all(p==canonical[0] for p in canonical[1:])
  else:checks[preset+':identical_output_and_outcome']=False
 result={'status':'passed' if all(checks.values()) else 'failed','finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'operations':{'release':90000000,'sanitizer':18000000},'configurations_per_preset':9,'excluded_mode_specific_fields':sorted(EXCLUDE),'rows':sorted(rows,key=lambda r:(r['preset'],r['mode'],r['kernel']))}
 (ROOT/'results/p6/CC2-all-configurations.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'status':result['status'],'checks':checks}),flush=True)
 return 0 if result['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
