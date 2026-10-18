#!/usr/bin/env python3
"""Check P1 real-data artifacts after conversion, repetition and C++ reads."""
import argparse,csv,hashlib,json
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--spec-cpp',type=Path,required=True)
    parser.add_argument('--flat-cpp',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    counts=json.loads(Path('results/data/itch_20191230_counts.json').read_text())
    manifest=json.loads(Path('data/manifest.json').read_text())
    checks={}
    traces={}
    cpp=[json.loads(p.read_text()) for p in (args.spec_cpp,args.flat_cpp)]
    for index,(name,hierarchy) in enumerate((('spec','H-spec'),('flat','H-flat'))):
        filename=f'itch_20191230_0930_1000_{name}.mdt'
        primary=Path('data/traces')/filename
        repeat=Path('data/traces/repeat')/filename
        meta=json.loads(Path(str(primary)+'.meta.json').read_text())
        repeated=json.loads(Path(str(repeat)+'.meta.json').read_text())
        primary_sha=digest(primary)
        repeat_sha=digest(repeat)
        traces[hierarchy]={'path':str(primary),'bytes':primary.stat().st_size,
                           'sha256':primary_sha,'repeat_path':str(repeat),'repeat_sha256':repeat_sha,
                           'records':meta['trace']['records'],'topics':meta['trace']['topics'],
                           'cpp_result':cpp[index]}
        checks[f'{hierarchy}:RC2_byte_identity']=primary_sha==repeat_sha==meta['trace']['sha256']==repeated['trace']['sha256']
        checks[f'{hierarchy}:source_identity']=meta['source']['sha256']==repeated['source']['sha256']==manifest['sha256']==counts['source_sha256']
        checks[f'{hierarchy}:complete_scan']=not meta['source']['limited'] and meta['source']['uncompressed_bytes_scanned']==counts['total_uncompressed_bytes'] and meta['source']['messages_scanned']==counts['message_count']
        checks[f'{hierarchy}:source_completeness_reported']=meta['source']['incomplete']==counts['incomplete'] and meta['source']['terminated']==counts['terminated']
        checks[f'{hierarchy}:window']=meta['window']==repeated['window']=={'start_inclusive_ns':34200000000000,'end_exclusive_ns':36000000000000}
        checks[f'{hierarchy}:cpp_counts']=cpp[index]['record_count']==meta['trace']['records']==counts['window']['message_count'] and cpp[index]['payload_bytes']==counts['window']['payload_bytes'] and cpp[index]['topic_count']==meta['trace']['topics']
        checks[f'{hierarchy}:hierarchy_label']=meta['hierarchy']==hierarchy
        checks[f'{hierarchy}:type_counts']=sum(meta['counts_by_type'].values())==counts['window']['message_count']
    checks['hierarchies:payload_identity']=all(cpp[0][key]==cpp[1][key] for key in ('record_count','payload_bytes','payload_fnv1a64'))
    for scope,expected in (('full_day',counts),('window',counts['window'])):
        for table in ('topic_volumes','H-flat_topic_volumes','partition_volumes','family_volumes','per_second'):
            path=Path(f'results/data/itch_20191230_{scope}_{table}.csv')
            with path.open(newline='') as stream:
                rows=list(csv.DictReader(stream))
            checks[f'{scope}:{table}:counts']=sum(int(row['count']) for row in rows)==expected['message_count']
            checks[f'{scope}:{table}:payload_bytes']=sum(int(row['payload_bytes']) for row in rows)==expected['payload_bytes']
        with Path(f'results/data/itch_20191230_{scope}_run_lengths.csv').open(newline='') as stream:
            checks[f'{scope}:run_lengths:counts']=sum(int(row['messages']) for row in csv.DictReader(stream))==expected['message_count']
    names=('F01_itch_type_mix','F02_symbol_volume_skew','F03_family_composition','F04_runs_and_bursts','F05_tree_and_class_sizes')
    figures={str(p):{'bytes':p.stat().st_size,'sha256':digest(p)} for n in names for e in ('png','pdf') if (p:=Path(f'results/figures/{n}.{e}')).is_file()}
    checks['F01_F05:all_10_artifacts']=len(figures)==10 and all(info['bytes']>0 for info in figures.values())
    checks['CC6:passed']=json.loads(Path('results/p1/cc6-reconciliation.json').read_text())['status']=='passed'
    result={'status':'passed' if all(checks.values()) else 'failed','checks':checks,'traces':traces,'figures':figures,
            'scope':'Real-data P1 integrity/RC-2/V05/L1 checks; no engine or performance result'}
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,indent=2,sort_keys=True))
    return int(not all(checks.values()))

if __name__=='__main__':raise SystemExit(main())
