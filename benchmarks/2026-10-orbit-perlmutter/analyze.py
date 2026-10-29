#!/usr/bin/env python3
"""Turn bench.py results (+ radical.prof profiles for F1) into summaries and
slide figures.

Usage: analyze.py <runs/perf dir> <output dir>

Writes into <output dir>:
  data/f2_throughput.csv   all F2 / F5 points (every repetition)
  data/f2_summary.csv      median / min / max tasks/s per config and batch size
  data/f1_tasks.csv        per-task segment durations (seconds)
  data/f1_summary.csv      p50 / p95 per config, task kind and segment (ms)
  f1_latency.{png,svg}, f2_throughput.{png,svg}, f5_two_endpoints.{png,svg}

F1 segments only ever subtract timestamps taken on the same host: the client
and the embedded broker share the login node; endpoint_recv / rh_submit /
rh_submit_done all come from the endpoint node.
"""

import csv
import glob
import json
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                     # noqa: E402
import numpy as np                                                  # noqa: E402

# categorical slots of the reference palette, fixed order
C = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300',
     '#6250d6', '#e34948']
INK, INK2, GRID = '#0b0b0b', '#52514e', '#e4e3df'

plt.rcParams.update({
    'font.size': 18, 'axes.titlesize': 20, 'axes.labelsize': 19,
    'legend.fontsize': 15, 'xtick.labelsize': 16, 'ytick.labelsize': 16,
    'axes.edgecolor': INK2, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': INK2, 'ytick.color': INK2, 'axes.spines.top': False,
    'axes.spines.right': False, 'axes.grid': True, 'grid.color': GRID,
    'grid.linewidth': 1, 'figure.facecolor': 'white', 'savefig.dpi': 200,
    'svg.fonttype': 'none'})


def load_results(root):
    recs = []
    for path in sorted(glob.glob(os.path.join(root, '*', 'results.jsonl'))):
        with open(path) as fin:
            recs += [json.loads(line) for line in fin if line.strip()]
    return recs


def read_prof(path):
    evs = []
    if not os.path.exists(path):
        return evs
    with open(path) as fin:
        for line in fin:
            if line.startswith('#'):
                continue
            p = line.rstrip('\n').split(',', 6)
            if len(p) < 7:
                continue
            evs.append({'t': float(p[0]), 'event': p[1], 'uid': p[4],
                        'state': p[5], 'msg': p[6]})
    return evs


def save(fig, out, stem):
    fig.savefig(os.path.join(out, stem + '.png'), bbox_inches='tight')
    fig.savefig(os.path.join(out, stem + '.svg'), bbox_inches='tight')
    plt.close(fig)


def pct(vals, q):
    vals = [v for v in vals if v == v]
    return float(np.percentile(vals, q)) if vals else float('nan')


# ---------------------------------------------------------------------------
# F2 / F5

F2_LINES = [            # cfg, label, color, style
    ('direct',       'RHAPSODY direct (no ORBIT)',         C[0], '-'),
    ('orbit-default', 'via ORBIT',                         C[1], '-'),
    ('orbit-nw0',    'via ORBIT, endpoint notify window 0', C[2], '-'),
    ('orbit-nw0-bw0', 'via ORBIT, both windows 0',         C[3], '-'),
]


def f2(recs, out):
    rows = [r for r in recs if r.get('fig') == 'F2']
    with open(os.path.join(out, 'data', 'f2_throughput.csv'), 'w') as fout:
        w = csv.writer(fout)
        w.writerow(['cfg', 'kind', 'rep', 'batch_size', 'submit_s', 'wait_s',
                    'total_s', 'tasks_per_s', 'failed'])
        for r in rows:
            w.writerow([r['cfg'], r['kind'], r['rep'], r['batch_size'],
                        '%.6f' % r['submit_time'], '%.6f' % r['wait_time'],
                        '%.6f' % r['total_time'], '%.2f' % r['tasks_per_sec'],
                        r['failed']])

    agg = defaultdict(list)
    for r in rows:
        agg[(r['cfg'], r['kind'], r['batch_size'])].append(r['tasks_per_sec'])
    summ = {}
    with open(os.path.join(out, 'data', 'f2_summary.csv'), 'w') as fout:
        w = csv.writer(fout)
        w.writerow(['cfg', 'kind', 'batch_size', 'n_reps', 'median_tps',
                    'min_tps', 'max_tps'])
        for key in sorted(agg):
            v = agg[key]
            summ[key] = (np.median(v), min(v), max(v))
            w.writerow(list(key) + [len(v), '%.1f' % np.median(v),
                                    '%.1f' % min(v), '%.1f' % max(v)])

    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5), sharey=True)
    for ax, kind, title in zip(axes, ('homo', 'hetero'),
                               ('identical tasks', 'per-task arguments')):
        for cfg, label, color, ls in F2_LINES:
            pts = sorted((b, s) for (c, k, b), s in summ.items()
                         if c == cfg and k == kind)
            if not pts:
                continue
            x = [p[0] for p in pts]
            med = [p[1][0] for p in pts]
            ax.fill_between(x, [p[1][1] for p in pts],
                            [p[1][2] for p in pts], color=color, alpha=0.15,
                            linewidth=0)
            ax.plot(x, med, ls, color=color, lw=2.5, marker='o', ms=8,
                    label=label)
            stalls = sorted(r['batch_size'] for r in recs
                            if r.get('fig') == 'F2-stall'
                            and r['cfg'] == cfg and r['kind'] == kind)
            if stalls and x:
                xs = min(stalls)
                ax.plot([xs], [med[-1]], 'X', color=color, ms=16,
                        markeredgecolor='white', markeredgewidth=1.5)
                if cfg == 'orbit-nw0':
                    ax.annotate('stalls from %d\n(client callback\nqueue '
                                'overflow)' % xs, (xs, med[-1]),
                                xytext=(12, -6), textcoords='offset points',
                                fontsize=13, color=INK2, va='top')
        ax.set_xscale('log', base=2)
        ax.set_yscale('log')
        ax.set_title(title)
        ax.set_xlabel('tasks per batch')
        ax.set_xticks([1, 16, 256, 4096, 16384])
        ax.set_xticklabels(['1', '16', '256', '4k', '16k'])
    axes[0].set_ylabel('throughput [tasks/s]')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower center',
               ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.13))
    fig.suptitle('Task throughput vs. batch size (noop backend, '
                 'Perlmutter, median of 3; band = min..max)', fontsize=18,
                 color=INK2)
    save(fig, out, 'f2_throughput')

    # F5: one vs two endpoints
    f5 = [('f5-one', 'one endpoint', C[1]), ('f5-two', 'two endpoints', C[6])]
    if any(c == 'f5-two' for (c, _, _) in summ):
        fig, ax = plt.subplots(figsize=(10, 6.5))
        for cfg, label, color in f5:
            pts = sorted((b, s) for (c, k, b), s in summ.items()
                         if c == cfg and k == 'homo')
            x = [p[0] for p in pts]
            ax.fill_between(x, [p[1][1] for p in pts],
                            [p[1][2] for p in pts], color=color, alpha=0.15,
                            linewidth=0)
            ax.plot(x, [p[1][0] for p in pts], '-', color=color, lw=2.5,
                    marker='o', ms=8, label=label)
        ax.set_xscale('log', base=2)
        ax.set_xlabel('tasks per batch (split evenly over endpoints)')
        ax.set_ylabel('aggregate throughput [tasks/s]')
        ax.set_title('One client, one vs. two ORBIT endpoints (noop)')
        ax.legend(frameon=False, loc='upper left')
        save(fig, out, 'f5_two_endpoints')


# ---------------------------------------------------------------------------
# F1

SEG_LOCAL = [('local', 'RHAPSODY (local session)', C[0])]
SEG_ORBIT = [
    ('api',     'RHAPSODY client API',                    C[0]),
    ('batch',   'client batch window',                    C[3]),
    ('c2b',     'client -> broker',                       C[4]),
    ('ep',      'endpoint: recv -> submitted',            C[2]),
    ('net',     'broker <-> endpoint network + notify',   C[1]),
    ('b2c',     'broker -> client',                       C[6]),
]


def f1_orbit_task(r, cprof, bprof, eprof):
    uid = r['uid']
    sub = cprof.get(('task_submit', uid))
    fl = cprof.get(('task_batch_flush', uid))
    done = cprof.get(('task_complete', uid))
    rs = eprof['rh_submit'].get(uid)
    rsd = eprof['rh_submit_done'].get(uid)
    if None in (sub, done, rs, rsd):
        return None
    # the submit request that carried this task: last submit POST before
    # rh_submit on the endpoint host
    recv = [e for e in eprof['recv'] if e['t'] <= rs]
    if not recv:
        return None
    recv = recv[-1]
    rreq = bprof['req'].get(recv['uid'])
    rresp = bprof['resp'].get(recv['uid'])
    evin = [t for t in bprof['evin'] if rreq is not None and rreq <= t <= done]
    if rreq is None or not evin:
        return None
    evin = evin[-1]
    start = fl if fl is not None else sub
    seg = {
        'api':   (sub - r['t0']) + (r['t2'] - done),
        'batch': (fl - sub) if fl is not None else 0.0,
        'c2b':   rreq - start,
        'ep':    rsd - recv['t'],
        'b2c':   done - evin,
    }
    seg['net'] = (evin - rreq) - seg['ep']
    seg['total'] = r['t2'] - r['t0']
    # submit request round trip minus endpoint time: pure transport estimate
    seg['ws_rtt'] = ((rresp - rreq) - seg['ep']) if rresp else float('nan')
    return seg


def f1(recs, root, out):
    rows = [r for r in recs if r.get('fig') == 'F1']
    by_phase = defaultdict(list)
    for r in rows:
        by_phase[r['phase']].append(r)

    per_task = []                    # (cfg, kind, seg dict)
    for phase, rs in by_phase.items():
        cfg, kind = rs[0]['cfg'], rs[0]['kind']
        if cfg == 'local':
            for r in rs:
                per_task.append((cfg, kind, {'local': r['t2'] - r['t0'],
                                             'total': r['t2'] - r['t0']}))
            continue
        base = os.path.dirname(phase)
        # a client profiler writes to the cwd at backend construction, which
        # may be another phase dir: merge them all (uids are per process)
        cprof = {}
        for p in glob.glob(os.path.join(base, '*', 'client.task.prof')):
            for e in read_prof(p):
                if e['event'] == 'task_complete' and e['state'] != 'DONE':
                    continue
                cprof[(e['event'], e['uid'])] = e['t']
        b = read_prof(os.path.join(base, 'broker.prof'))
        bprof = {'req':  {e['uid']: e['t'] for e in b
                          if e['event'] == 'broker_route_request'},
                 'resp': {e['uid']: e['t'] for e in b
                          if e['event'] == 'broker_route_response'},
                 'evin': sorted(e['t'] for e in b
                                if e['event'] == 'broker_event_in'
                                and 'task_status' in e['msg'])}
        e = []
        for p in glob.glob(os.path.join(base, 'endpoint-*', 'endpoint.prof')):
            e += read_prof(p)
        e.sort(key=lambda x: x['t'])
        eprof = {'rh_submit': {x['uid']: x['t'] for x in e
                               if x['event'] == 'rh_submit'},
                 'rh_submit_done': {x['uid']: x['t'] for x in e
                                    if x['event'] == 'rh_submit_done'},
                 'recv': [x for x in e if x['event'] == 'endpoint_recv'
                          and x['msg'].startswith('POST /rhapsody/submit')]}
        miss = 0
        for r in rs:
            seg = f1_orbit_task(r, cprof, bprof, eprof)
            if seg is None:
                miss += 1
                seg = {'total': r['t2'] - r['t0']}
            per_task.append((cfg, kind, seg))
        print('F1 %-12s %-4s %d tasks, %d without full profile' % (
            cfg, kind, len(rs), miss))

    segs = ['local'] + [s[0] for s in SEG_ORBIT] + ['ws_rtt', 'total']
    with open(os.path.join(out, 'data', 'f1_tasks.csv'), 'w') as fout:
        w = csv.writer(fout)
        w.writerow(['cfg', 'kind'] + segs)
        for cfg, kind, seg in per_task:
            w.writerow([cfg, kind] + ['%.6f' % seg[s] if s in seg else ''
                                      for s in segs])

    groups = defaultdict(list)
    for cfg, kind, seg in per_task:
        groups[(cfg, kind)].append(seg)
    summ = {}
    with open(os.path.join(out, 'data', 'f1_summary.csv'), 'w') as fout:
        w = csv.writer(fout)
        w.writerow(['cfg', 'kind', 'segment', 'n', 'p50_ms', 'p95_ms'])
        for key in sorted(groups):
            for s in segs:
                v = [g[s] for g in groups[key] if s in g]
                if not v:
                    continue
                summ[key + (s,)] = (pct(v, 50) * 1e3, pct(v, 95) * 1e3)
                w.writerow(list(key) + [s, len(v), '%.3f' % summ[key + (s,)][0],
                                        '%.3f' % summ[key + (s,)][1]])

    # (a) end-to-end, stacked; small hops merged so the windows stay legible
    stack = [
        ('local',   'local RHAPSODY session',              C[0]),
        ('small',   'client API + client->broker + endpoint (each ~1 ms)',
                                                          '#8f8e89'),
        ('batch',   'client batch window (0.25 s)',        C[3]),
        ('net',     'endpoint notify window + network',    C[1]),
        ('b2c',     'broker -> client delivery',           C[6]),
    ]

    def seg_p50(cfg, kind, s):
        if s == 'small':
            return sum(summ.get((cfg, kind, x), (0, 0))[0]
                       for x in ('api', 'c2b', 'ep'))
        return summ.get((cfg, kind, s), (0, 0))[0]

    bars = [('local', 'local'), ('default', 'ORBIT\ndefault'),
            ('default-bw0', 'ORBIT\nclient\nwindow 0'),
            ('nw0-bw0', 'ORBIT\nboth\nwindows 0')]
    bars = [b for b in bars if (b[0], 'fn', 'total') in summ]
    if not bars:
        return
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(19, 8),
                                 gridspec_kw={'width_ratios': [1.35, 1]})
    seen, xt, xl = set(), [], []
    for g, (cfg, label) in enumerate(bars):
        for j, kind in enumerate(('fn', 'exe')):
            x = g * 2.6 + j * 1.0
            xt.append(x)
            xl.append('fn' if kind == 'fn' else 'exe')
            bottom = 0.0
            for s, slabel, color in stack:
                v = max(seg_p50(cfg, kind, s), 0.0)
                if (cfg == 'local') != (s == 'local'):
                    continue
                ax.bar(x, v, bottom=bottom, width=0.85, color=color,
                       edgecolor='white', linewidth=2,
                       label=slabel if slabel not in seen else None)
                seen.add(slabel)
                bottom += v
            p50, p95 = summ[(cfg, kind, 'total')]
            ax.text(x, max(p95, bottom) + 8, '%.0f' % p50 if p50 >= 10
                    else '%.1f' % p50, ha='center', va='bottom',
                    fontsize=15, color=INK)
        ax.text(g * 2.6 + 0.5, -0.09, label, transform=ax.get_xaxis_transform(),
                ha='center', va='top', fontsize=16, color=INK)
    ax.set_xticks(xt)
    ax.set_xticklabels(xl, fontsize=14)
    ax.grid(axis='x', visible=False)
    ax.set_ylabel('submit -> DONE latency [ms]')
    ax.set_title('(a) one task end to end (p50, label = p50 ms)')
    fig.legend(*ax.get_legend_handles_labels(), loc='lower left', ncol=2,
               frameon=False, fontsize=14, bbox_to_anchor=(0.02, -0.16))
    ax.set_ylim(0, 580)

    # (b) per-hop cost in the default deployment, p50 bar + p95 whisker
    hops = [('api',    'RHAPSODY client API'),
            ('c2b',    'client -> broker (login node)'),
            ('ws_rtt', 'broker <-> endpoint WS round trip'),
            ('ep',     'endpoint: recv -> task submitted'),
            ('b2c',    'broker -> client delivery')]
    cfg = 'default'
    y = np.arange(len(hops))
    for j, (kind, color, lbl) in enumerate((('fn', C[0], 'noop function'),
                                            ('exe', C[2], '/bin/true'))):
        p50 = [summ.get((cfg, kind, h), (np.nan, np.nan))[0] for h, _ in hops]
        p95 = [summ.get((cfg, kind, h), (np.nan, np.nan))[1] for h, _ in hops]
        yy = y + (j - 0.5) * 0.38
        bx.barh(yy, p50, height=0.36, color=color, label=lbl,
                edgecolor='white', linewidth=2)
        bx.errorbar(p95, yy, fmt='|', color=INK, ms=14, mew=2.5)
        bx.hlines(yy, p50, p95, color=INK, lw=1.2)
    bx.set_yticks(y)
    bx.set_yticklabels([h[1] for h in hops], fontsize=15)
    bx.invert_yaxis()
    bx.set_xlabel('ms (bar = p50, tick = p95)')
    bx.set_title('(b) per-hop cost, default config')
    bx.grid(axis='y', visible=False)
    bx.legend(loc='lower right', frameon=False)
    fig.suptitle('Single remote task vs. local (200 sequential tasks per bar; '
                 'login-node client + broker, compute-node endpoint)',
                 fontsize=17, color=INK2)
    fig.tight_layout()
    save(fig, out, 'f1_latency')


def main():
    root, out = sys.argv[1], sys.argv[2]
    os.makedirs(os.path.join(out, 'data'), exist_ok=True)
    recs = load_results(root)
    f2(recs, out)
    f1(recs, root, out)


if __name__ == '__main__':
    main()
