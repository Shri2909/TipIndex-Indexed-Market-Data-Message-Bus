"""Validate the controlled-runtime input/dependency contracts without timing."""
from argparse import Namespace
import runpy

namespace=runpy.run_path('scripts/run_p7_runtime.py')
runner=namespace['Runner'](Namespace(output_dir='results/raw/P7/runtime',summary='results/p7/runtime-campaign.json',
                                   protocol='results/p7/runtime-supplement.json',manifest='results/p7/input-manifest.json',
                                   campaign='results/raw/P7/studies/campaign.json'))
runner.select_observer()
runner.prepare()
assert len(runner.cases)==len(runner.metadata)==len(runner.reference)==900
assert len(runner.orders)==11 and all(len(set(order))==900 for order in runner.orders)
print('Preflight passed: 900 unchanged cases/references, 11 seeded permutations, exact limits and current dependency identities.')
