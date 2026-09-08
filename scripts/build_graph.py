#!/usr/bin/env python3
"""把抽取结果合并成 graph.json。

输入：data/extracted_*.json（LLM 抽取产物）+ data/comments_raw.json（视频元数据）
输出：data/graph.json（渲染器直接消费）

节点类型：concern 关注点 / persona 人群 / video 视频 / metaphor 隐喻 / coping 应对
边：担心、被提出、被说成、缓解、共现
每条边都挂证据（评论原文 + 点赞 + 来源视频），可回溯。
"""
import json
import glob
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

TYPE_LABEL = {
    'concern': '关注点',
    'persona': '人群',
    'video': '视频',
    'metaphor': '隐喻',
    'coping': '应对策略',
}
TYPE_COLOR = {
    'concern': '#ff7b72',
    'persona': '#58a6ff',
    'video': '#e3b341',
    'metaphor': '#bc8cff',
    'coping': '#3fb950',
}


# 并行抽取时各 agent 会自建词表外术语，这里归一化。
# 只合并语义确实重合的，不同概念即使低频也保留。
CONCERN_ALIAS = {
    '找工作难': '职业选择',
    '开源被盗用': '开源刷星',
}


def load_extracted():
    rows = []
    for path in sorted(glob.glob(os.path.join(DATA, 'extracted_*.json'))):
        with open(path, encoding='utf-8-sig') as f:
            rows.extend(json.load(f))
    for r in rows:
        if r.get('concerns'):
            seen, merged = set(), []
            for c in r['concerns']:
                c = CONCERN_ALIAS.get(c, c)
                if c not in seen:
                    seen.add(c)
                    merged.append(c)
            r['concerns'] = merged
    return rows


def load_video_meta():
    with open(os.path.join(DATA, 'comments_raw.json'), encoding='utf-8-sig') as f:
        vids = json.load(f)
    return {v['aweme_id']: v for v in vids}


def clean_title(title):
    """去掉话题标签，保留正文。"""
    body = title.split('#')[0].strip()
    return (body or title)[:24]


def main():
    rows = load_extracted()
    meta = load_video_meta()
    print(f'读入 {len(rows)} 条抽取结果')

    nodes = {}
    edges = defaultdict(lambda: {'ev': [], 'w': 0})

    def node(nid, ntype, extra=None):
        if nid not in nodes:
            nodes[nid] = {'id': nid, 'type': ntype, 'mentions': 0}
            if extra:
                nodes[nid].update(extra)
        return nodes[nid]

    def edge(src, dst, rel, ev):
        key = (src, dst, rel)
        e = edges[key]
        e['w'] += 1
        if len(e['ev']) < 12:
            e['ev'].append(ev)

    for r in rows:
        aid = r.get('aweme_id')
        vmeta = meta.get(aid, {})
        vtitle = clean_title(vmeta.get('title', '') or aid)
        vnode = node(vtitle, 'video', {
            'aweme_id': aid,
            'full_title': vmeta.get('title', ''),
            'create_time': vmeta.get('create_time'),
            'play': vmeta.get('play'),
        })

        ev = {
            'text': r.get('text', ''),
            'like': r.get('like', 0),
            'video': vtitle,
            'stance': r.get('stance'),
            'sarcasm': bool(r.get('is_sarcasm')),
            'ask': bool(r.get('is_ask')),
            'win': bool(r.get('is_win')),
        }

        concerns = [c for c in (r.get('concerns') or []) if c]
        persona = r.get('persona')
        metaphor = r.get('metaphor')
        copings = [c for c in (r.get('coping') or []) if c]

        for c in concerns:
            node(c, 'concern')['mentions'] += 1
            vnode['mentions'] += 1
            edge(vtitle, c, '引出', ev)
            if persona:
                node(persona, 'persona')['mentions'] += 1
                edge(persona, c, '担心', ev)
            if metaphor:
                node(metaphor[:22], 'metaphor')['mentions'] += 1
                edge(c, metaphor[:22], '被说成', ev)
            for cp in copings:
                node(cp, 'coping')['mentions'] += 1
                edge(cp, c, '缓解', ev)

        # 无 concern 但有人群/应对时，仍挂到视频上，避免丢信号
        if not concerns:
            if persona:
                node(persona, 'persona')['mentions'] += 1
                edge(persona, vtitle, '出现在', ev)
            if metaphor:
                node(metaphor[:22], 'metaphor')['mentions'] += 1
                edge(vtitle, metaphor[:22], '产出金句', ev)

    # 关注点共现
    co = defaultdict(int)
    co_ev = defaultdict(list)
    for r in rows:
        cs = sorted({c for c in (r.get('concerns') or []) if c})
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                co[(cs[i], cs[j])] += 1
                if len(co_ev[(cs[i], cs[j])]) < 6:
                    co_ev[(cs[i], cs[j])].append({
                        'text': r.get('text', ''), 'like': r.get('like', 0),
                        'video': clean_title(meta.get(r.get('aweme_id'), {}).get('title', '')),
                        'stance': r.get('stance'), 'sarcasm': bool(r.get('is_sarcasm')),
                        'ask': bool(r.get('is_ask')), 'win': bool(r.get('is_win')),
                    })
    for (a, b), w in co.items():
        if w >= 2:
            edges[(a, b, '共现')] = {'w': w, 'ev': co_ev[(a, b)]}

    # 隐喻是长尾金句，全留会淹没核心结构。按最高赞排序只保留 TOP N。
    METAPHOR_KEEP = 24
    m_score = {}
    for (s, d, rel), e in edges.items():
        for nid in (s, d):
            if nodes.get(nid, {}).get('type') == 'metaphor':
                best = max((x.get('like', 0) for x in e['ev']), default=0)
                m_score[nid] = max(m_score.get(nid, 0), best)
    keep_m = {nid for nid, _ in sorted(m_score.items(), key=lambda x: -x[1])[:METAPHOR_KEEP]}
    dropped_m = len(m_score) - len(keep_m)

    keep = set()
    for (s, d, rel), e in edges.items():
        keep.add(s)
        keep.add(d)
    drop = {nid for nid, n in nodes.items()
            if n['type'] == 'metaphor' and nid not in keep_m}
    nodes = {k: v for k, v in nodes.items() if k in keep and k not in drop}
    edge_list = [
        {'s': s, 't': d, 'rel': rel, 'w': e['w'],
         'ev': sorted(e['ev'], key=lambda x: -x.get('like', 0))}
        for (s, d, rel), e in edges.items()
        if s in nodes and d in nodes
    ]

    stats = {
        'comments': len(rows),
        'videos': len({r.get('aweme_id') for r in rows}),
        'with_concern': sum(1 for r in rows if r.get('concerns')),
        'ask': sum(1 for r in rows if r.get('is_ask')),
        'win': sum(1 for r in rows if r.get('is_win')),
        'sarcasm': sum(1 for r in rows if r.get('is_sarcasm')),
    }
    stance = defaultdict(int)
    for r in rows:
        if r.get('stance'):
            stance[r['stance']] += 1

    graph = {
        'meta': {
            'title': 'AI 时代关注点图谱',
            'subtitle': f"{stats['comments']} 条真实评论 · {stats['videos']} 个视频",
            'stats': stats,
            'stance': dict(sorted(stance.items(), key=lambda x: -x[1])),
            'default_off': ['metaphor'],
        },
        'types': {k: {'label': TYPE_LABEL[k], 'color': TYPE_COLOR[k]} for k in TYPE_LABEL},
        'nodes': sorted(nodes.values(), key=lambda n: -n['mentions']),
        'links': sorted(edge_list, key=lambda e: -e['w']),
    }

    out = os.path.join(DATA, 'graph.json')
    with open(out, 'w') as f:
        json.dump(graph, f, ensure_ascii=False, indent=1)

    print(f"节点 {len(graph['nodes'])} 个，边 {len(graph['links'])} 条 -> {out}")
    print(f"  隐喻保留 TOP{METAPHOR_KEEP}，长尾丢弃 {dropped_m} 个")
    print(f"  有关注点的评论 {stats['with_concern']} / {stats['comments']}")
    print(f"  提问 {stats['ask']} 条 · 成果汇报 {stats['win']} 条 · 阴阳怪气 {stats['sarcasm']} 条")
    top = [n for n in graph['nodes'] if n['type'] == 'concern'][:10]
    print('\n关注点 TOP10:')
    for n in top:
        print(f"  {n['mentions']:>3}  {n['id']}")


if __name__ == '__main__':
    main()
