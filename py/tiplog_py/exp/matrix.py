"""Declarative Tier B experiment matrices; all choices are retained as artifacts."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import tomllib

CACHE = ('repeat-warm', 'scratch-thrashed')
KERNELS = ('stdpq', 'binheap', 'quad', 'loser')
ARMS = [('scan', 'stdpq')] + [('indexed', k) for k in KERNELS] + [('auto', k) for k in KERNELS]
TSV_HEADER = 'id\texperiment\tafter_seq\tterms\tmode\tkernel\tcache\tbatch\treaders'


def stable_id(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:20]


def load(path: str | Path) -> dict:
    with open(path, 'rb') as stream: return tomllib.load(stream)


def symbols(path: str | Path) -> list[str]:
    rows = list(csv.DictReader(open(path)))
    return [row['partition'].split('/')[1] for row in
            sorted(rows, key=lambda row: (-int(row['count']), row['partition']))
            if not row['partition'].split('/')[1].startswith('_')]


def consumer(kind: str, names: list[str]) -> str:
    terms = []
    for symbol in names:
        base = 'itch/' + symbol
        if kind == 'BOOK':
            terms += [f'subtree:{base}/{family}' for family in ('add', 'modify', 'stock')]
        elif kind == 'TAPE':
            terms += [f'exact:{base}/modify/executed', f'exact:{base}/modify/executed_px',
                      f'subtree:{base}/trade']
        elif kind == 'AUCT': terms += [f'exact:{base}/noii', f'exact:{base}/trade/cross']
        elif kind == 'STAT': terms += [f'subtree:{base}/stock']
        elif kind == 'REPLAY': terms += [f'subtree:{base}']
        else: raise ValueError('unknown consumer')
    if kind == 'BOOK': terms.append('subtree:itch/_market')
    return ';'.join(sorted(set(terms)))


def t1_subscriptions(config: dict, ranked: list[str]) -> list[dict]:
    rng = random.Random(config['seed'])
    result = [dict(name='BOOK-top1', terms=consumer('BOOK', ranked[:1]), breadth=1),
              dict(name='BOOK-median', terms=consumer('BOOK', [ranked[len(ranked)//2]]), breadth=1)]
    for count in config['t1']['basket_sizes']:
        for strategy, names in [('top', ranked[:count]), ('random', rng.sample(ranked, count))]:
            result.append(dict(name=f'BOOK-{strategy}{count}', terms=consumer('BOOK', names), breadth=count))
    for count in config['t1']['tape_sizes']:
        result.append(dict(name=f'TAPE-top{count}', terms=consumer('TAPE', ranked[:count]), breadth=count))
    result += [dict(name='all-trades', terms=';'.join(f'subtree:itch/{name}/trade' for name in ranked),
                    breadth=len(ranked)), dict(name='full-stream', terms='subtree:itch', breadth=len(ranked))]
    return result


def w2_readers(ranked: list[str], count: int, seed: int) -> list[dict]:
    choices, weights = [], []
    for rank, name in enumerate(ranked, 1):
        for kind in ('BOOK', 'TAPE', 'AUCT', 'STAT'):
            weight = ((10 if rank <= 100 else 1 if rank <= 1000 else 0)
                      if kind in ('BOOK', 'TAPE') else int(rank <= 1000) if kind == 'AUCT' else 1)
            if weight:
                choices.append((kind, name)); weights.append(weight)
    chosen = random.Random(seed).choices(choices, weights=weights, k=count)
    return [dict(name=f'W2-reader{index}-{kind}-{symbol}', terms=consumer(kind, [symbol]),
                 breadth=1, consumer=kind, symbol=symbol)
            for index, (kind, symbol) in enumerate(chosen)]


def arms_for(base: dict, *, include_auto=True, cache_treatments=CACHE) -> list[dict]:
    result = []
    for cache in cache_treatments:
        comparison = dict(base, cache_treatment=cache)
        comparison_id = stable_id(comparison)
        for mode, kernel in (ARMS if include_auto else ARMS[:5]):
            item = dict(comparison, mode=mode, kernel=kernel, comparison_id=comparison_id)
            item['id'] = stable_id(item)
            result.append(item)
    return result


def make_plan(config: dict, *, training=False, pilot=False) -> list[dict]:
    ranked = symbols(config['partition_volumes'])
    workloads = []
    if not training:
        for capacity in (config['t1']['ring_bytes'], config['t1']['long_backlog_ring_bytes']):
            requests = []
            backlogs = config['t1']['backlogs_seconds'] if capacity == config['t1']['ring_bytes'] else [max(config['t1']['backlogs_seconds'])]
            for backlog in backlogs:
                for sub in t1_subscriptions(config, ranked):
                    base = dict(exp='T1', **sub, backlog_seconds=backlog, ring_bytes=capacity,
                                block_entries=config['t1']['block_entries'], anchor_ts=config['anchor_ts'],
                                batch=1024, readers=1)
                    requests += arms_for(base)
            if capacity == config['t1']['ring_bytes']:
                for count in config['t2']['readers']:
                    reader_specs = w2_readers(ranked, count, config['seed'])
                    for index, sub in enumerate(reader_specs):
                        base = dict(exp='T2', **sub, reader_index=index, reader_count=count,
                                    group_name=f'T2-R{count}', market_seconds=config['t2']['backlog_seconds'],
                                    backlog_seconds=config['t2']['backlog_seconds'], ring_bytes=capacity,
                                    block_entries=config['t1']['block_entries'], anchor_ts=config['anchor_ts'],
                                    batch=1024, readers=1)
                        requests += arms_for(base)
            if pilot:
                requests = [row for row in requests if row['exp'] == 'T1' and row['name'] == 'BOOK-top1'
                            and row['backlog_seconds'] == 10 and row['mode'] == 'indexed'
                            and row['kernel'] == 'binheap' and row['cache_treatment'] == 'repeat-warm']
                if capacity != config['t1']['ring_bytes']: continue
            workloads.append(dict(id=f'real-C{capacity}-B1024', kind='trace', trace=config['trace'],
                                  ring_bytes=capacity, block_entries=config['t1']['block_entries'],
                                  anchor_ts=config['anchor_ts'], seed=config['seed'], requests=requests))
        if pilot: return workloads
    t3 = config['t3']
    for partitions in t3['training_partitions'] if training else t3['partitions']:
        for zipf in t3['training_zipf'] if training else t3['zipf']:
            for run_length in t3['training_run_lengths'] if training else t3['run_lengths']:
                seed = t3['training_seed'] if training else t3['evaluation_seed']
                requests = []
                breadths = sorted({1, int(math.sqrt(partitions)), partitions})
                for breadth in breadths:
                    for selectivity in t3['selectivity']:
                        terms = []
                        for owner in range(breadth):
                            if selectivity == 1: terms.append(f'subtree:synth/p{owner}')
                            else:
                                terms.append(f'exact:synth/p{owner}/e0')
                                if selectivity == .1: terms.append(f'exact:synth/p{owner}/e1')
                        base = dict(exp='T3', name=f'k{breadth}-selectivity{selectivity}', terms=';'.join(terms),
                                    k=breadth, selectivity=selectivity, partitions=partitions,
                                    zipf=zipf, run_length=run_length, seed=seed,
                                    ring_bytes=t3['ring_bytes'], block_entries=t3['block_entries'],
                                    records=t3['records'], after_seq=0, batch=1024, readers=1,
                                    split='training' if training else 'held-out')
                        requests += arms_for(base, include_auto=not training)
                workloads.append(dict(id=f'synth-P{partitions}-Z{zipf}-L{run_length}-S{seed}', kind='synthetic',
                                      ring_bytes=t3['ring_bytes'], block_entries=t3['block_entries'],
                                      records=t3['records'], partitions=partitions, zipf=zipf,
                                      run_length=run_length, seed=seed, payload_mix=config['payload_mix'],
                                      requests=requests))
    if not training:
        for block_entries in config['t5']['block_entries']:
            for anchor in config['t5']['anchor_ts']:
                base = dict(exp='T5', name=f'snapshot-{anchor}-B{block_entries}', terms='subtree:itch',
                            breadth=len(ranked), ring_bytes=config['t5']['ring_bytes'],
                            block_entries=block_entries, anchor_ts=anchor, checkpoint_at_snapshot_head=True,
                            batch=1024, readers=1, snapshot_ts=anchor)
                requests = [item for item in arms_for(base) if item['mode'] == 'scan']
                workloads.append(dict(id=f'memory-B{block_entries}-A{anchor}', kind='trace',
                                      trace=config['trace'], ring_bytes=base['ring_bytes'],
                                      block_entries=block_entries, anchor_ts=anchor, seed=config['seed'],
                                      memory=True, allocator_replay=True, requests=requests))
    return workloads


def write_term_dictionary(path: Path, rows: list[dict]) -> dict[str,str]:
    """Store each exact subscription string once; request aliases reduce disk use.

    This changes only the request transport. The independent oracle and config
    identities continue to use the full original subscription terms.
    """
    aliases = {row['terms']:hashlib.sha256(row['terms'].encode()).hexdigest() for row in rows}
    reverse = {identity:terms for terms,identity in aliases.items()}
    if len(reverse) != len(aliases): raise ValueError('subscription alias hash collision')
    text = ''.join(identity+'\t'+terms+'\n' for identity,terms in sorted(reverse.items()))
    if any('\t' in terms or '\n' in terms or '\r' in terms for terms in aliases):
        raise ValueError('subscription dictionary contains separator')
    if path.exists():
        if path.read_text() != text: raise ValueError('existing subscription dictionary differs')
    else:
        path.write_text(text)
    return aliases


def write_requests(path: Path, rows: list[dict], *, term_aliases: dict[str,str] | None = None) -> None:
    with path.open('w') as stream:
        stream.write(TSV_HEADER+'\n')
        for row in rows:
            terms = '@'+term_aliases[row['terms']] if term_aliases is not None else row['terms']
            values = [row['id'], row['exp'], row['after_seq'], terms, row['mode'],
                      row['kernel'], row['cache_treatment'], row.get('batch', 1024), row.get('readers', 1)]
            if any('\t' in str(value) or '\n' in str(value) for value in values):
                raise ValueError('TSV field contains separator')
            stream.write('\t'.join(map(str, values))+'\n')
