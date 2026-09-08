#!/usr/bin/env python3
"""把 graph.json 注入 viewer 模板，产出零依赖单文件 HTML。

用法：python3 scripts/render.py [graph.json] [输出.html]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    graph_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'data', 'graph.json')
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'atlas.html')
    tpl_path = os.path.join(ROOT, 'templates', 'viewer.html')

    with open(graph_path) as f:
        graph = json.load(f)
    with open(tpl_path) as f:
        tpl = f.read()

    meta = graph.get('meta', {})
    payload = json.dumps(graph, ensure_ascii=False, separators=(',', ':'))
    # 防止评论正文里的 </script> 提前闭合脚本标签
    payload = payload.replace('</', '<\\/')

    html = (tpl
            .replace('__TITLE__', meta.get('title', '知识图谱'))
            .replace('__SUBTITLE__', meta.get('subtitle', ''))
            .replace('__GRAPH_JSON__', payload))

    with open(out_path, 'w') as f:
        f.write(html)

    size = os.path.getsize(out_path) / 1024
    print(f"{len(graph.get('nodes', []))} 节点 / {len(graph.get('links', []))} 边 -> {out_path} ({size:.0f} KB)")


if __name__ == '__main__':
    main()
