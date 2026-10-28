"""F14–F18 from actual P7 observations; all byte costs are modeled."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

METHODS = ('base', 'km-min', 'km-max', 'best-exact')
COLORS = dict(zip(METHODS, ('#676767','#e69f00','#56b4e9','#009e73'), strict=True))


def value(item):
    if item is None:
        return None
    return float(item['value']) if isinstance(item, dict) else float(item)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def source_identity():
    path = Path(__file__).resolve()
    return {'path':str(path.relative_to(path.parents[3])), 'sha256':sha(path)}


def select(rows, **conditions):
    return [row for row in rows if all(str(row.get(k)) == str(v) for k,v in conditions.items())]


def finish(figure, output, name, caption):
    figure.text(.01,.012,caption,fontsize=8,va='bottom')
    figure.tight_layout(rect=(0,.06,1,.94))
    for extension in ('png','pdf'):
        figure.savefig(output/f'{name}.{extension}',dpi=150)
    plt.close(figure)


def build(summary_path, global_path, example_path, output, runtime_path=None):
    summary_path, global_path, example_path, output = map(Path,(summary_path,global_path,example_path,output))
    summary=json.loads(summary_path.read_text())
    global_results=json.loads(global_path.read_text())
    example=json.loads(example_path.read_text())
    runtime_path = Path(runtime_path or 'results/derived/layout-runtime.json')
    runtime=json.loads(runtime_path.read_text())
    if summary['failure_counts'] or global_results['status']!='passed' or example['status']!='passed' or runtime['status']!='passed':
        raise ValueError('P7 figure inputs contain unresolved failures')
    output.mkdir(parents=True,exist_ok=True)
    figures=[]

    fig,axes=plt.subplots(4,3,figsize=(17,13),squeeze=False)
    for wi,workload in enumerate(('W0','W1','W2','W3')):
        for bi,beta in enumerate(('0','65536','1048576')):
            ax=axes[wi,bi]
            rows=select(summary['exact_cohort_consumer_quality'],kind='real',hierarchy='H-spec',workload=workload,beta=beta)
            roles=sorted({r['role'] for r in rows})
            width=.18
            for mi,method in enumerate(METHODS):
                lookup={r['role']:r for r in rows if r['method']==method}
                heights=[value(lookup.get(role,{}).get('weighted_read_amplification')) for role in roles]
                ax.bar(np.arange(len(roles))+(mi-1.5)*width,[np.nan if h is None else h for h in heights],width,
                       label=method,color=COLORS[method])
            cohort=select(summary['exact_cohort_quality'],kind='real',hierarchy='H-spec',workload=workload,beta=beta,method='best-exact')
            n=cohort[0]['feasible'] if cohort else 0
            ax.set(xticks=np.arange(len(roles)),xticklabels=roles,ylabel='Weighted read / useful bytes',
                   title=f'{workload}; β/α={int(beta):,} B; common exact cohort n={n:,}')
            ax.tick_params(axis='x',labelrotation=25)
            if wi==0 and bi==0:ax.legend(fontsize=8)
    fig.suptitle('F14 · Per-class read amplification on identical solved partitions',fontsize=15)
    finish(fig,output,'F14_layout_class_amplification','Modeled full-window record bytes. Best-exact uses a solved DP/ENUM result; capped partitions are excluded from every method in each panel.')
    figures.append('F14_layout_class_amplification')

    fig,axes=plt.subplots(2,3,figsize=(16,9));flat=axes.ravel()
    for wi,workload in enumerate(('W0','W1','W2','W3')):
        ax=flat[wi]
        stratum=next(s for s in global_results['strata'] if s['label']==f'real-H-spec-{workload}-beta0')
        points=sorted({(p['stores'],value(p['objective'])) for p in stratum['points']})
        if points:
            ax.plot([p[0] for p in points],[p[1]/1e9 for p in points],marker='o',color=COLORS['best-exact'],
                    linestyle='-' if stratum['global_certified'] else '--',
                    label='Certified supported sweep' if stratum['global_certified'] else 'Feasible sweep; uncertified')
        for method,marker in zip(METHODS[:3],('s','^','v'),strict=True):
            row=select(summary['quality'],kind='real',hierarchy='H-spec',workload=workload,beta='0',method=method)[0]
            ax.scatter(row['stores'],value(row['weighted_read_bytes'])/1e9,marker=marker,color=COLORS[method],label=method,s=50)
        ax.set(title=f'{workload}: complete curves {stratum["complete_partitions"]:,}/8,907',xlabel='Total materialized stores',ylabel='Weighted modeled read GB')
        ax.legend(fontsize=7)
    ax=flat[4]
    curve=[p for p in example['joint_curves'] if p['enum'] is not None]
    ax.plot([p['budget'] for p in curve],[int(p['enum'])/1e9 for p in curve],marker='o')
    ax.set(title='Worked example: joint at-most-budget exact curve',xlabel='Total budget, separate L/R partitions',ylabel='Modeled read GB')
    flat[5].axis('off')
    flat[5].text(0,.95,'Global certificate rules\n\n• Every partition needs a complete exact curve.\n• λ ≥ 0 exposes supported efficient points.\n• Unsupported budgets retain feasible upper bounds\n  and certified lower bounds, when available.\n• Incomplete terms supply no global certificate.\n\nβ = γ = 0 in the four real-data panels.\nAll other β strata are retained in the summary.',va='top',fontsize=11,linespacing=1.6)
    fig.suptitle('F15 · Stores versus modeled read bytes',fontsize=15)
    finish(fig,output,'F15_layout_tradeoff','Full real population. Lines show evaluated nonnegative-multiplier points, not an assertion that every integer budget or the entire hull was solved.')
    figures.append('F15_layout_tradeoff')

    fig,axes=plt.subplots(2,3,figsize=(18,10))
    for bi,beta in enumerate(('0','65536','1048576')):
        ax=axes[0,bi];stats=[];labels=[];colors=[]
        for workload in ('W0','W1','W2','W3'):
            for method in METHODS[:3]:
                row=select(summary['comparisons'],kind='real',hierarchy='H-spec',workload=workload,beta=beta,method=method)[0]
                d=row['relative_gaps']
                if not d['count']:continue
                stats.append({'med':value(d['median']),'q1':value(d['p25']),'q3':value(d['p75']),
                              'whislo':value(d['minimum']),'whishi':value(d['maximum']),'fliers':[]})
                labels.append(f'{workload}\n{method}');colors.append(COLORS[method])
        boxes=ax.bxp(stats,showfliers=False,patch_artist=True)
        for patch,color in zip(boxes['boxes'],colors,strict=True):patch.set_facecolor(color)
        ax.set_xticks(np.arange(1,len(labels)+1),labels,rotation=60,fontsize=7)
        ax.set(title=f'β/α={int(beta):,} B',ylabel='(cost − OPT) / OPT',yscale='symlog')
        ax.axhline(0,color='black',linewidth=.5)
    ax=axes[1,0]
    for shape in ('chain','star','random'):
        rows=[r for r in runtime['cases'] if r['classes']==4 and r['budget']==4 and r['shape']==shape
              and r['all_measured_solved']]
        sizes=sorted({r['nodes'] for r in rows})
        medians=[float(np.median([r['solved_seconds']['median'] for r in rows if r['nodes']==n])) for n in sizes]
        ax.loglog(sizes,medians,marker='o',label=f'{shape} ({len(rows)}/40 inputs)')
    ax.set(title='Controlled DP: b=4, K=4; 10 processes per input',xlabel='Nodes',ylabel='Median across fixed-input medians (s)');ax.legend(fontsize=8)
    ax=axes[1,1]
    positions=np.arange(4);width=.36
    for mi,method in enumerate(('enum','dp')):
        rows=[select(summary['exact_coverage'],kind='real',hierarchy='H-spec',workload=w,beta='0',method=method)[0] for w in ('W0','W1','W2','W3')]
        ax.bar(positions+(mi-.5)*width,[100*value(r['case_fraction']) for r in rows],width,label=method)
    ax.set(xticks=positions,xticklabels=['W0','W1','W2','W3'],ylim=(0,105),ylabel='Solved partitions (%)',title='H-spec exact coverage, β=0');ax.legend(fontsize=8)
    axes[1,2].axis('off');axes[1,2].text(0,.95,'Gap scope\n\nBoxes: 25th/50th/75th percentiles.\nWhiskers: full observed min/max.\nOnly solved identical-budget cases enter gaps.\nZero OPT has no relative gap.\n\nRuntime: saved warm-up +10 measured processes.\nPoints combine up to5 different tree inputs.\nOnly all10-solved inputs enter runtime points.\nAll cap outcomes and frequency flags are retained.\n\nPer-input CIs and exact coverage by partitions,\nbytes and active class weight are saved.',va='top',fontsize=11,linespacing=1.6)
    fig.suptitle('F16 · Exact optimality gaps, scaling and coverage',fontsize=15)
    finish(fig,output,'F16_layout_gaps_scaling','Modeled objective gaps; controlled solver timings remain conditional on this nonexclusive laptop. A cap result is never treated as an optimum or a solved runtime.')
    figures.append('F16_layout_gaps_scaling')

    fig,axes=plt.subplots(1,3,figsize=(17,6))
    locationsL={0:(.1,.9),1:(.1,.6),2:(0,.3),3:(.22,.3),4:(.35,.6)}
    locationsR={0:(.72,.9),1:(.55,.6),2:(.47,.3),3:(.63,.3),4:(.88,.6),5:(.8,.3),6:(.97,.3)}
    for ax,method in zip(axes,('base','km-max','dp'),strict=True):
        row=next(r for r in example['rows'] if r['method']==method)
        for partition_index,(nodes,positions,cuts) in enumerate(((example['left_nodes'],locationsL,row['cutsL']),(example['right_nodes'],locationsR,row['cutsR']))):
            owners={}
            for node in nodes:
                v=node['id'];parent=node['parent'];x,y=positions[v]
                owners[v]=v if parent is None or v in cuts else owners[parent]
                if parent is not None:
                    px,py=positions[parent];ax.plot([px,x],[py,y],color='gray',linestyle='--' if v in cuts else '-',linewidth=.9 if v in cuts else 2)
                ax.scatter(x,y,s=650,c=[plt.cm.tab20((owners[v]+10*partition_index)%20)],edgecolors='black',zorder=3)
                amount=f'{node["bytes"]:,}'
                ax.text(x,y,node['path'].split('/')[-1],ha='center',va='center',fontsize=9,zorder=4)
                ax.text(x,y-.09,amount,ha='center',fontsize=7)
        ax.set(title=f'{method}: {row["stores"]} stores\nWaste {row["waste"]:,} B',xlim=(-.1,1.1),ylim=(.03,1.05));ax.axis('off')
    fig.suptitle('F17 · Computed article-example layouts under the declared model',fontsize=15)
    finish(fig,output,'F17_layout_worked_example','Dashed edges are cuts; colors distinguish component ownership within each partition. Zero-node attachments may differ under objective ties. L/R never share a store.')
    figures.append('F17_layout_worked_example')

    fig,axes=plt.subplots(2,2,figsize=(13,10))
    for ax,workload in zip(axes.ravel(),('W0','W1','W2','W3'),strict=True):
        for hierarchy,color in (('H-spec','#0072b2'),('H-flat','#d55e00')):
            for method,marker in zip(METHODS[:3],('s','^','v'),strict=True):
                row=select(summary['quality'],kind='real',hierarchy=hierarchy,workload=workload,beta='0',method=method)[0]
                ax.scatter(row['stores'],value(row['weighted_waste_bytes'])/1e9,color=color,marker=marker,s=65,label=f'{hierarchy} {method}')
        ax.set(title=workload,xlabel='Total materialized stores',ylabel='Weighted modeled waste GB')
        ax.legend(fontsize=8)
    fig.suptitle('F18 · Hierarchy sensitivity, full population, β = γ = 0',fontsize=15)
    finish(fig,output,'F18_layout_hierarchy','H-flat baseline exact-read waste is zero by construction and checked for all partitions. Hierarchies have different feasible sets; cross-hierarchy differences are not optimality gaps.')
    figures.append('F18_layout_hierarchy')
    manifest={'schema':'tiplog-p7-figures-v1','figures':figures,'scope':'L2/L3/L4/L5; modeled bytes only',
              'inputs':{str(p):sha(p) for p in (summary_path,global_path,example_path,runtime_path)},
              'outputs':{str(output/f'{name}.{ext}'):sha(output/f'{name}.{ext}') for name in figures for ext in ('png','pdf')},
              'exact_cohort':'All compared methods restricted to the same solved partitions in F14 and gap panels; full-population heuristics in F15/F18.',
              'source':source_identity()}
    (output/'p7-figures.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    return manifest
