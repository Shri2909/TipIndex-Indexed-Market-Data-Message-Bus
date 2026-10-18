"""Audit Git-eligible artifacts before a local implementation snapshot."""
import hashlib,json,re,subprocess
from pathlib import Path
names=[x for x in subprocess.check_output(['scripts/git.sh','ls-files','--cached','--others','--exclude-standard','-z']).decode().split('\0') if x]
seed=Path('data/raw/fuzz_itch_walker/nasdaq-20191230-first65536.bin').read_bytes()
signatures={seed[i:i+24] for i in range(0,len(seed)-23,32) if len(set(seed[i:i+24]))>=10}
pattern=re.compile(b'|'.join(re.escape(s) for s in sorted(signatures)))
matches=[]; forbidden=[]; total=0
for name in names:
 p=Path(name)
 if not p.is_file(): continue
 raw=p.read_bytes();total+=len(raw)
 if pattern.search(raw): matches.append(name)
 if name.startswith(('data/raw/','data/traces/','results/raw/')) or (name.startswith('results/p1/F2') and name.endswith('.log')): forbidden.append(name)
result={'status':'passed' if not matches and not forbidden else 'failed','eligible_files':len(names),'eligible_bytes':total,'real_prefix_sha256':hashlib.sha256(seed).hexdigest(),'high_entropy_24_byte_signatures':len(signatures),'matching_paths':matches,'forbidden_message_paths':forbidden,'selection':'git ls-files --cached --others --exclude-standard -z','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'limitations':'A signature/provenance audit supports exclusion; it cannot prove absence of every short payload fragment. Tracked test/fuzz bytes derive only from synthetic fixtures. Raw input, traces, real seed and F2 raw logs remain ignored.'}
Path('results/p4/git-data-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));raise SystemExit(result['status']!='passed')
