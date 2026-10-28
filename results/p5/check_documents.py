"""Check prose Markdown targets/fences without treating code as links."""
import datetime
import json
from pathlib import Path
import re

files = [Path('README.md'), *Path('docs/plan').glob('*.md'),
         *Path('results/p5').glob('*.md')]
errors, count = [], 0
for path in files:
    prose, fence = [], None
    for line in path.read_text().splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            kind = marker[1][0]
            if fence is None:
                fence = kind
            elif fence == kind:
                fence = None
        elif fence is None:
            prose.append(line)
    if fence is not None:
        errors.append(f'{path}: unbalanced Markdown fence')
    text = re.sub(r'`[^`\n]*`', '', '\n'.join(prose))
    for target in re.findall(r'\]\(([^)]+)\)', text):
        target = target.strip('<>')
        if target.startswith(('http:', 'https:', 'mailto:', '#')):
            continue
        target = target.split('#')[0]
        if target:
            count += 1
            if not (path.parent / target).exists():
                errors.append(f'{path}: missing {target}')
result = {
    'status': 'failed' if errors else 'passed',
    'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'files': [str(path) for path in files],
    'local_links_checked': count, 'errors': errors,
    'scope': 'Prose Markdown fences and local target existence only; no external URL or semantic assertion validation',
}
Path('results/p5/document-checks.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
raise SystemExit(bool(errors))
