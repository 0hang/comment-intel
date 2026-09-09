#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书评论批量采集（OpenCLI + 浏览器登录态）。

风控应对（2026-09-09 实测）：
- 搜索页通常可通，笔记详情页/评论会动态风控（Navigation rejected）
- 每次 opencli 调用间隔 8 秒；被拒后重试 1 次；仍失败降级为搜索元数据
  （标题+点赞记入 xhs_degraded.txt 供简报使用），不中断整体
- opencli 用 node 直调 main.js，绕开 .cmd 把 URL 里 &xsec_source= 截断的问题

用法:
    python collect_xhs.py [--base <任务目录>] [--search-files a.yaml,b.yaml ...]
                          [--top N] [--interval 8] [--retry 1]
    --search-files 缺省时自动取 <base>/xhs_search_*.yaml

输入: <base>/xhs_search_*.yaml（opencli xiaohongshu search -f yaml 输出，UTF-16LE/UTF-8-BOM/UTF-8/GBK 自动探测）
输出: <base>/xhs_comments_<n>.yaml；被拒笔记记入 <base>/xhs_degraded.txt
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time

RATE_LIMIT_SEC = 8
COMMENTS_RETRY = 1
DEGRADE_ON_REJECT = True

OPENCLI = r"C:\Users\12480\AppData\Roaming\npm\opencli.cmd"
if not os.path.exists(OPENCLI):
    cand = shutil.which("opencli")
    OPENCLI = cand or "opencli"


def read_text(path):
    """自动探测编码：PowerShell `>` 重定向产物常为 UTF-16LE 或 UTF-8-BOM。"""
    with open(path, "rb") as f:
        b = f.read()
    if b.startswith(b"\xff\xfe"):
        return b.decode("utf-16-le", errors="replace")
    if b.startswith(b"\xef\xbb\xbf"):
        return b.decode("utf-8-sig", errors="replace")
    try:
        return b.decode("utf-8", errors="replace")
    except Exception:
        return b.decode("gbk", errors="replace")


def parse_urls(path):
    """解析 opencli 搜索 yaml。处理 `key: >-` 折叠值（值在后续缩进行）。"""
    items = []
    cur = None
    pending = None
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        m = re.match(r"\s*- rank:\s*(\d+)", line)
        if m:
            if cur and cur.get("url"):
                items.append(cur)
            cur = {"rank": int(m.group(1))}
            pending = None
            continue
        if cur is None:
            continue
        m = re.match(r"^(\s*)([^\s:]+):(?=\s|$)(.*)$", line)
        if m:
            indent, key, val = m.group(1), m.group(2), m.group(3).strip().strip("'\"")
            pending = None
            if val in (">-", "|-", ">"):
                pending = (key, indent)
            elif key in ("title", "url", "likes") and key not in cur:
                cur[key] = val
            continue
        if pending:
            key, indent = pending
            indent_len = len(indent)
            m = re.match(r"^(\s{%d,%d})(\S.*)$" % (indent_len + 2, indent_len + 8), line)
            if m and key not in cur:
                cur[key] = m.group(2).strip().strip("'\"")
    if cur and cur.get("url"):
        items.append(cur)
    return items


def run_opencli(args, timeout=180):
    """node 直调 main.js：绕开 .cmd 批处理把 URL 里 `&xsec_source=` 当命令分隔符截断的问题。"""
    node_main = os.path.join(
        os.path.dirname(OPENCLI),
        "node_modules", "@jackwener", "opencli", "dist", "src", "main.js",
    )
    if os.path.exists(node_main):
        base = ["node", node_main]
    else:
        base = [OPENCLI]
    p = subprocess.run(
        base + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    return p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getcwd())
    ap.add_argument("--search-files", default="", help="逗号分隔，缺省自动取 xhs_search_*.yaml")
    ap.add_argument("--top", type=int, default=2)
    ap.add_argument("--interval", type=int, default=RATE_LIMIT_SEC)
    ap.add_argument("--retry", type=int, default=COMMENTS_RETRY)
    args = ap.parse_args()

    base = args.base
    if args.search_files:
        search_files = [s.strip() for s in args.search_files.split(",") if s.strip()]
    else:
        search_files = sorted(glob.glob(os.path.join(base, "xhs_search_*.yaml")))
    if not search_files:
        print("未找到 xhs_search_*.yaml，退出")
        return 1

    targets = []
    for sf in search_files:
        if not os.path.exists(sf):
            continue
        kw = os.path.basename(sf).replace("xhs_search_", "").replace(".yaml", "")
        items = parse_urls(sf)
        print(f"[{kw}] 解析到 {len(items)} 条结果")
        for it in items[:args.top]:
            targets.append((kw, it.get("title", ""), it.get("url", ""), it.get("likes", 0)))

    print(f"共 {len(targets)} 篇笔记待读评论（间隔 {args.interval}s，被拒自动降级）")
    degraded_log = os.path.join(base, "xhs_degraded.txt")
    for i, (kw, title, url, likes) in enumerate(targets, 1):
        out = os.path.join(base, f"xhs_comments_{i:02d}.yaml")
        if not url:
            print(f"[{i}] 无 URL，跳过: {title}")
            continue
        print(f"[{i}/{len(targets)}] {kw} | {title[:30]} | {likes}赞")
        text = run_opencli(["xiaohongshu", "comments", url, "-f", "yaml"])
        ok = "ok: false" not in text[:300] and "Navigation rejected" not in text[:500]
        if not ok and args.retry > 0:
            print(f"    -> 首次 FAIL ({len(text)} bytes)，等 {args.interval}s 重试…")
            time.sleep(args.interval)
            text = run_opencli(["xiaohongshu", "comments", url, "-f", "yaml"])
            ok = "ok: false" not in text[:300] and "Navigation rejected" not in text[:500]
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# kw={kw}\n# title={title}\n# url={url}\n# likes={likes}\n" + text)
        if ok:
            print(f"    -> OK ({len(text)} bytes)")
        else:
            print(f"    -> FAIL ({len(text)} bytes)")
            if DEGRADE_ON_REJECT:
                with open(degraded_log, "a", encoding="utf-8") as f:
                    f.write(f"{kw}\t{title}\t{likes}\t{url}\n")
                print("    -> 已降级：标题/点赞记入 xhs_degraded.txt")
        time.sleep(args.interval)

    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
