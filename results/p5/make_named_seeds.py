"""Explicit synthetic integrated-operation seeds; no input dataset bytes."""
from pathlib import Path
import hashlib,json
root=Path('tests/fuzz/corpus/ops_integrated');root.mkdir(exist_ok=True)
def pub(path,length=8,value=42):return [0,0,path,length,value]
def snap(sub,mode,kernel,selection=0):return [1,0,sub,selection,mode,kernel]
def batch(n):return [2,0,n]
def tail(sub,mode=1,kernel=0,selection=0,floor=None):return [8,0,sub,selection]+([] if floor is None else [floor])+[mode,kernel]
def poll(n):return [9,0,n]
seeds={}; meanings={}
for mode,name in [(0,'scan'),(1,'indexed'),(2,'auto')]:
 for kernel,kname in [(0,'stdpq'),(1,'binheap'),(2,'quad'),(3,'loser')]:
  if mode==0 and kernel:continue
  filename=f'{name}_{kname}_multicursor.ops'
  seeds[filename]=[66]+pub(0)+pub(4,8,43)+pub(1)+pub(0)+snap(3,mode,kernel)+batch(2)+pub(0)+batch(3)+snap(3,mode,kernel,1)+batch(8)+tail(3,mode,kernel,3)+pub(4)+poll(1)+poll(1)
  meanings[filename]='Two selected nonempty partitions, overlapping terms, distinct equal events, full-budget More, captured upper then checkpoint resume; fresh Tail rearm. Auto rho1 permits Indexed.'
seeds['auto_forced_scan.ops']=[98]+pub(0)+pub(4)+snap(3,2,3)+batch(8)
meanings['auto_forced_scan.ops']='Kmax0 forces Scan for Auto/Loser without changing expected output.'
seeds['auto_density_scan.ops']=[2]+pub(0)+pub(4)+snap(3,2,2)+batch(8)
meanings['auto_density_scan.ops']='Rho0.25 forces Scan for dense Auto/Quad snapshot.'
seeds['true_pressure_all_kernels.ops']=[128]
meanings['true_pressure_all_kernels.ops']='N1/B1/C64 independent golden ForceEvict/Reject fixture executes with all four kernels.'
seeds['tail_future_topic_zero_output.ops']=[66]+tail(5,1,3)+pub(0,0)+[7,0]+poll(8)+[4,0,0,2,8,19]+poll(1)+[7,0]+poll(1)
meanings['tail_future_topic_zero_output.ops']='Empty Tail captures nothing at max0; zero-output A range completes, future topic2 appears and is delivered by rearmed Loser Tail.'
seeds['tail_global_zero_output_expiry.ops']=[0]+tail(1)+pub(4,16)+poll(8)+pub(4,16)*3+poll(1)+[7,0]+tail(1,1,0,5)+[11,0]
meanings['tail_global_zero_output_expiry.ops']='After zero-output seq1 checkpoint, oldest3 yields FellBehind(request0,last0,oldest3); future UINT64_MAX Tail rejects and preserves old reader.'
seeds['tail_completed_pad_expired.ops']=[0]+pub(0,10)+pub(0,4)+tail(0,1,2,6,1)+poll(1)+pub(0,8)+pub(0,0)+pub(0,8)+poll(4)
meanings['tail_completed_pad_expired.ops']='Tail after1 consumes seq2 at exact budget/cp56; PAD56 expires while seq3 remains, then rearm delivers3/4/5 without false expiry.'
seeds['tail_last_matching_expiry.ops']=[0]+pub(0,16)+tail(1)+poll(1)+pub(4,16)*3+poll(1)
meanings['tail_last_matching_expiry.ops']='Later rearm expiry preserves global matching seq1, not irrelevant resumed floor.'
seeds['rejection_unchanged.ops']=[2]+pub(0)+[6,0,0]+snap(0,1,1)+batch(8)
meanings['rejection_unchanged.ops']='Oversized publication rejects before mutation; prior A event still reads through BinHeap.'
files={}
for name,data in seeds.items():
 raw=bytes(data);p=root/name;p.write_bytes(raw);files[str(p)]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'scenario':meanings[name],'decoded_bytes':data}
Path('results/p5/named-corpus.json').write_text(json.dumps({'scope':'Fresh P5 grammar seeds; old P3/P4 corpora preserved separately and not relabeled as these scenarios','files':files},indent=2)+'\n')
print('Fresh integrated synthetic seeds:',len(files))
