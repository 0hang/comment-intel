#!/usr/bin/env python3
"""把 graph.json 导出成三种分发形态。

- docs/index.html   GitHub Pages 在线交互版（点链接就能看）
- data/digest.md    agent 可读的纯文本摘要（也是人在 GitHub 上能直接读的）
- README 里的 mermaid 片段（GitHub 首页原生渲染，不用点任何链接）
- llms.txt          agent 入口清单

用法：python3 scripts/export.py [--repo owner/name]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
DOCS = os.path.join(ROOT, 'docs')

MERMAID_BEGIN = '<!-- ATLAS:MERMAID:BEGIN -->'
MERMAID_END = '<!-- ATLAS:MERMAID:END -->'


def detect_repo():
    """从 git remote 推断 owner/name，失败返回占位符。"""
    try:
        url = subprocess.check_output(
            ['git', 'remote', 'get-url', 'origin'],
            cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None
    m = re.search(r'[:/]([^/:]+)/([^/]+?)(?:\.git)?$', url)
    return f'{m.group(1)}/{m.group(2)}' if m else None


def load_graph():
    with open(os.path.join(DATA, 'graph.json')) as f:
        return json.load(f)


def load_rows():
    """复用 build_graph 的加载逻辑，否则别名归一化不一致，
    README 和 digest 会对同一个关注点报出不同的数字。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'build_graph', os.path.join(ROOT, 'scripts', 'build_graph.py'))
    bg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bg)
    return bg.load_extracted()


def mermaid_block(graph, top_n=8):
    """GitHub README 原生渲染的精简图：人群 → 关注点 → 应对。

    只画有连线的关注点。孤立节点会在 README 里堆成一长列空方块，
    把图撑得很高又不传达关系——完整榜单在 digest.md 和交互版里。
    """
    rank = {n['id']: i for i, n in enumerate(graph['nodes'])}
    concern_ids = {n['id'] for n in graph['nodes'] if n['type'] == 'concern'}

    # 先收边，据此决定画哪些节点
    cand = []
    for l in graph['links']:
        if l['rel'] in ('担心', '缓解') and l['t'] in concern_ids and l['w'] >= 2:
            cand.append((l['s'], l['t'], l['rel']))

    linked = sorted({t for _, t, _ in cand}, key=lambda x: rank.get(x, 999))[:top_n]
    keep = set(linked)
    concerns = [n for n in graph['nodes'] if n['id'] in keep]

    ids, counter = {}, [0]

    def nid(name):
        if name not in ids:
            counter[0] += 1
            ids[name] = f'n{counter[0]}'
        return ids[name]

    edges, sides, seen = [], {}, set()
    for src, dst, rel in cand:
        if dst not in keep or (src, dst, rel) in seen:
            continue
        seen.add((src, dst, rel))
        edges.append((src, dst, rel))
        sides[src] = graph_node_type(graph, src)

    lines = ['```mermaid', 'graph LR']
    # 节点定义集中在前，每个只定义一次
    for c in concerns:
        lines.append(f'  {nid(c["id"])}("{esc_mm(c["id"])}<br/>{c["mentions"]}次")')
    for name in sides:
        lines.append(f'  {nid(name)}["{esc_mm(name)}"]')
    for src, dst, rel in edges:
        lines.append(f'  {nid(src)} -->|{esc_mm(rel)}| {nid(dst)}')

    lines.append('  classDef concern fill:#ffdedb,stroke:#d1534a,color:#5c1a15')
    lines.append('  classDef persona fill:#dbeafe,stroke:#3b7dd8,color:#12325e')
    lines.append('  classDef coping fill:#dcfce7,stroke:#3f9e5a,color:#14401f')
    if concerns:
        lines.append('  class ' + ','.join(nid(c['id']) for c in concerns) + ' concern')
    for t, cls in (('persona', 'persona'), ('coping', 'coping')):
        group = [nid(n) for n, nt in sides.items() if nt == t]
        if group:
            lines.append('  class ' + ','.join(group) + f' {cls}')
    lines.append('```')
    return '\n'.join(lines)


def check_mermaid(block):
    """静态自检。README 首页渲染失败会显示一大块红色报错，比没有图更糟。"""
    body = [l for l in block.split('\n') if l not in ('```mermaid', '```')]
    errs = []
    if not body or body[0].strip() != 'graph LR':
        errs.append('缺少 graph LR 声明')

    defined, used = set(), set()
    node_re = re.compile(r'^\s*(n\d+)[\("\[]')
    edge_re = re.compile(r'^\s*(n\d+)\s*-->\s*(?:\|[^|]*\|)?\s*(n\d+)\s*$')
    class_re = re.compile(r'^\s*class\s+([\w,]+)\s+\w+\s*$')

    for line in body[1:]:
        s = line.strip()
        if not s or s.startswith('classDef'):
            continue
        if (m := edge_re.match(line)):
            used.update(m.groups())
        elif (m := class_re.match(line)):
            used.update(m.group(1).split(','))
        elif (m := node_re.match(line)):
            defined.add(m.group(1))
        else:
            errs.append(f'无法解析: {s[:48]}')

    if (missing := used - defined):
        errs.append(f'引用了未定义的节点: {sorted(missing)}')
    # 标签里的裸引号/方括号会截断解析
    for line in body:
        label = re.search(r'[\("\[](.*?)[\)"\]]', line)
        if label and re.search(r'["\[\]]', label.group(1)):
            errs.append(f'标签含未转义字符: {line.strip()[:48]}')
    return errs


def graph_node_type(graph, node_id):
    for n in graph['nodes']:
        if n['id'] == node_id:
            return n['type']
    return 'unknown'


def esc_mm(s):
    """mermaid 标签里的引号和方括号会破坏语法。"""
    return str(s).replace('"', "'").replace('[', '(').replace(']', ')')


def build_digest(graph, rows, repo):
    """agent 读的摘要。结论在前，证据在后，纯 markdown。"""
    meta = graph['meta']
    stats = meta['stats']
    out = []
    w = out.append

    w(f"# {meta['title']} — 数据摘要")
    w('')
    w(f"> {meta['subtitle']}。本文件由 `scripts/export.py` 自动生成，供 agent 直接读取。")
    w('')
    w('## 概览')
    w('')
    w('| 指标 | 值 |')
    w('| --- | --- |')
    w(f"| 评论总数 | {stats['comments']} |")
    w(f"| 视频数 | {stats['videos']} |")
    w(f"| 含关注点的评论 | {stats['with_concern']} |")
    w(f"| 提问（内容缺口信号） | {stats['ask']} |")
    w(f"| 成果汇报 | {stats['win']} |")
    w(f"| 阴阳怪气 | {stats['sarcasm']} |")
    w('')
    w('立场分布：' + '、'.join(f'{k} {v}' for k, v in meta['stance'].items()))
    w('')

    # 关注点榜 + 提问密度
    ask, tot = Counter(), Counter()
    for r in rows:
        for c in (r.get('concerns') or []):
            tot[c] += 1
            if r.get('is_ask'):
                ask[c] += 1

    w('## 关注点排行')
    w('')
    w('`提问率` 高的是内容缺口——观众在问但还没被正面回答。')
    w('')
    w('| 关注点 | 提及 | 提问 | 提问率 |')
    w('| --- | ---: | ---: | ---: |')
    for c, n in tot.most_common(15):
        rate = ask[c] / n * 100 if n else 0
        w(f'| {c} | {n} | {ask[c]} | {rate:.0f}% |')
    w('')

    # 每个关注点的代表证据
    ev_by_concern = defaultdict(list)
    for r in rows:
        for c in (r.get('concerns') or []):
            ev_by_concern[c].append(r)

    w('## 关注点证据')
    w('')
    for c, n in tot.most_common(10):
        top = sorted(ev_by_concern[c], key=lambda x: -x.get('like', 0))[:3]
        w(f'### {c}（{n} 次提及，{ask[c]} 条提问）')
        w('')
        for r in top:
            flags = []
            if r.get('is_ask'):
                flags.append('提问')
            if r.get('is_win'):
                flags.append('成果')
            if r.get('is_sarcasm'):
                flags.append('阴阳怪气')
            tag = f" `{'/'.join(flags)}`" if flags else ''
            w(f"- 「{r['text']}」 — {r.get('like', 0)} 赞{tag}")
        w('')

    # 金句
    ms = [(r.get('like', 0), r['metaphor']) for r in rows if r.get('metaphor')]
    if ms:
        w('## 高赞金句')
        w('')
        for lk, m in sorted(ms, reverse=True)[:12]:
            w(f'- 「{m}」 — {lk} 赞')
        w('')

    # 共现
    co = Counter()
    for r in rows:
        cs = sorted(set(r.get('concerns') or []))
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                co[(cs[i], cs[j])] += 1
    if co:
        w('## 关注点共现')
        w('')
        w('总是一起出现的关注点，说明在观众心里它们是同一件事。')
        w('')
        for (a, b), n in co.most_common(8):
            w(f'- {a} × {b} — {n} 次')
        w('')

    w('## 机器可读')
    w('')
    if repo:
        raw = f'https://raw.githubusercontent.com/{repo}/main/data/graph.json'
        w(f'完整图谱（节点、边、逐条证据）：<{raw}>')
    else:
        w('完整图谱（节点、边、逐条证据）：`data/graph.json`')
    w('')
    w('```')
    w('graph.json 结构：')
    w('  meta   { title, subtitle, stats, stance }')
    w('  types  { concern|persona|video|metaphor|coping: {label, color} }')
    w('  nodes  [ {id, type, mentions} ]')
    w('  links  [ {s, t, rel, w, ev: [{text, like, video, stance, sarcasm, ask, win}]} ]')
    w('```')
    w('')
    w('每条边的 `ev` 是原始评论证据，任何结论都能回溯到具体哪句话。')
    return '\n'.join(out)


def build_llms_txt(graph, repo):
    meta = graph['meta']
    base = f'https://raw.githubusercontent.com/{repo}/main' if repo else '.'
    if repo:
        owner, name = repo.split('/')
        pages_line = f'- [在线交互版](https://{owner}.github.io/{name}/): 悬浮看摘要，点击看证据'
    else:
        pages_line = '- 在线交互版：推送到 GitHub 并开启 Pages 后，重跑 export.py 补全地址'
    return f"""# comment-intel

> 把短视频评论区变成可交互、可追溯的知识图谱。本仓库同时是一个 Agent Skill 和一份公开数据集。

## 数据集：{meta['title']}

{meta['subtitle']}。每条边都挂评论原文作为证据。

- [完整图谱 JSON]({base}/data/graph.json): 节点、边、逐条评论证据。agent 直接 fetch 这个
- [数据摘要]({base}/data/digest.md): 关注点排行、内容缺口、金句、共现簇
{pages_line}

## 用作 Skill

- [SKILL.md]({base}/SKILL.md): 六阶段流程，处理你自己的评论数据
- [抽取规范]({base}/references/schema.md): 字段定义和词表

## 说明

评论数据来自创作者本人后台，不含用户昵称和个人标识。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', help='owner/name，省略则从 git remote 推断')
    args = ap.parse_args()
    repo = args.repo or detect_repo()

    graph = load_graph()
    rows = load_rows()

    # 1. GitHub Pages
    os.makedirs(DOCS, exist_ok=True)
    src = os.path.join(ROOT, 'atlas.html')
    if os.path.exists(src):
        shutil.copy(src, os.path.join(DOCS, 'index.html'))
        print(f'docs/index.html  <- atlas.html')
    with open(os.path.join(DOCS, '.nojekyll'), 'w') as f:
        f.write('')

    # 2. digest
    digest = build_digest(graph, rows, repo)
    with open(os.path.join(DATA, 'digest.md'), 'w') as f:
        f.write(digest + '\n')
    print(f'data/digest.md   ({len(digest) // 1024 + 1} KB)')

    # 3. llms.txt
    llms = build_llms_txt(graph, repo)
    with open(os.path.join(ROOT, 'llms.txt'), 'w') as f:
        f.write(llms)
    print('llms.txt')

    # 4. README 里的 mermaid 片段
    block = mermaid_block(graph)
    if (errs := check_mermaid(block)):
        print('\nmermaid 自检未通过，README 未修改：')
        for e in errs:
            print(f'  - {e}')
        raise SystemExit(1)
    readme_path = os.path.join(ROOT, 'README.md')
    with open(readme_path) as f:
        readme = f.read()
    if MERMAID_BEGIN in readme and MERMAID_END in readme:
        readme = re.sub(
            re.escape(MERMAID_BEGIN) + r'.*?' + re.escape(MERMAID_END),
            MERMAID_BEGIN + '\n' + block + '\n' + MERMAID_END,
            readme, flags=re.S)
        note = f'mermaid 已更新（{block.count(chr(10))} 行）'
        # 推送后把 README 里的占位链接换成真地址
        if repo:
            owner, name = repo.split('/')
            before = readme
            readme = readme.replace(
                'https://example.github.io/comment-intel/',
                f'https://{owner}.github.io/{name}/')
            readme = re.sub(r'github\.com/<owner>/comment-intel',
                            f'github.com/{repo}', readme)
            readme = re.sub(r'githubusercontent\.com/<owner>/comment-intel',
                            f'githubusercontent.com/{repo}', readme)
            if readme != before:
                note += '，链接已补全'
        with open(readme_path, 'w') as f:
            f.write(readme)
        print(f'README.md        {note}')
    else:
        print('README.md        跳过——没找到 ATLAS:MERMAID 标记')

    if not repo:
        print('\n提示：未检测到 git remote，链接用了相对路径。')
        print('     推送后重跑 python3 scripts/export.py 会自动补全 URL。')


if __name__ == '__main__':
    main()
