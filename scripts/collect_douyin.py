#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖音评论采集 —— douyin MCP 直连（2026-09-09 实测）。

> 不要用 mcporter call douyin.*（必现 -32000 Connection closed 死路）。
> 改用 douyin-mcp 自带 .venv 的 Python 直接走 mcp.client.stdio 连 MCP。

流程: check_login_status（未登录直接跳过）→ 每关键词 search_videos
      （sort_type=1 按点赞）取前 N 个视频 → get_video_comments 读评论。
带请求超时，单请求失败跳过不中断。

用法:
    python collect_douyin.py <out_dir> [--mcp-dir <douyin-mcp路径>] [--kws "关键词1,关键词2"] [--top N] [--per N]

输出: <out_dir>/douyin_combined.json（rows: aweme_id/text/like/title/play，可直接喂 format_comments.py）
依赖: douyin-mcp 项目（.venv/Scripts/python.exe + main.py + cookies.txt），本项目从项目根读 cookie。
"""
import argparse
import asyncio
import json
import os
import sys

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("需要 mcp 库：pip install mcp（或使用 douyin-mcp/.venv 的 python 运行本脚本）")
    sys.exit(2)

DEFAULT_MCP_DIR = r"D:\data\Doubao\douyin-mcp"
DEFAULT_KEYWORDS = ["怎么做自媒体", "AI副业"]
DEFAULT_TOP = 2
DEFAULT_PER = 20
REQ_TIMEOUT = 25


async def call(session, name, args):
    return await asyncio.wait_for(session.call_tool(name, args), timeout=REQ_TIMEOUT)


def to_text(resp):
    return "".join(c.text or "" for c in resp.content)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", nargs="?", default=os.getcwd())
    ap.add_argument("--mcp-dir", default=DEFAULT_MCP_DIR)
    ap.add_argument("--kws", default=",".join(DEFAULT_KEYWORDS))
    ap.add_argument("--top", type=int, default=DEFAULT_TOP)
    ap.add_argument("--per", type=int, default=DEFAULT_PER)
    args = ap.parse_args()

    mcp_dir = args.mcp_dir
    keywords = [k.strip() for k in args.kws.split(",") if k.strip()]
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    venv_py = os.path.join(mcp_dir, ".venv", "Scripts", "python.exe")
    main_py = os.path.join(mcp_dir, "main.py")
    if not os.path.exists(venv_py) or not os.path.exists(main_py):
        print(f"douyin-mcp 未找到: {mcp_dir}（缺 .venv/Scripts/python.exe 或 main.py）")
        return 1

    sp = StdioServerParameters(command=venv_py, args=[main_py], cwd=mcp_dir)
    async with stdio_client(sp) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                st = await call(session, "check_login_status", {})
                print("login:", to_text(st).strip()[:100])
                if "false" in to_text(st).lower().split("logged_in")[-1][:20]:
                    print("SKIP douyin: not logged in")
                    return 0
            except Exception as e:
                print("login check fail:", e)
                return 0

            rows, seen = [], set()
            for kw in keywords:
                vids = []
                try:
                    r = await call(session, "search_videos", {"keyword": kw, "count": 10, "sort_type": 1})
                    data = json.loads(to_text(r))
                    items = data.get("data") or data.get("items") or data.get("videos") or [] if isinstance(data, dict) else []
                    for it in items:
                        info = it.get("aweme_info") or it
                        aid = str(info.get("aweme_id") or "")
                        if not aid or aid in seen:
                            continue
                        stat = info.get("statistics") or {}
                        vids.append({"aweme_id": aid, "desc": info.get("desc", ""),
                                     "play": stat.get("play_count", 0)})
                    vids = vids[:args.top]
                    print(f"[{kw}] {len(vids)} videos")
                except Exception as e:
                    print(f"[{kw}] search fail: {e}")

                for v in vids:
                    seen.add(v["aweme_id"])
                    try:
                        cr = await call(session, "get_video_comments", {"aweme_id": v["aweme_id"], "count": args.per})
                        cdata = json.loads(to_text(cr))
                        comments = cdata.get("comments") or cdata.get("data") or [] if isinstance(cdata, dict) else []
                        for cm in comments:
                            rows.append({
                                "aweme_id": v["aweme_id"],
                                "text": str(cm.get("content", cm.get("text", ""))),
                                "like": int(cm.get("like_count", cm.get("like", 0)) or 0),
                                "title": v["desc"][:60],
                                "play": v["play"],
                            })
                        print(f"  {v['aweme_id']}: {len(comments)} comments")
                    except Exception as e:
                        print(f"  {v['aweme_id']} comments fail: {e}")
                await asyncio.sleep(1)

            out = os.path.join(out_dir, "douyin_combined.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"rows": rows, "source": "douyin-mcp", "n": len(rows)}, f, ensure_ascii=False, indent=1)
            print(f"TOTAL {len(rows)} -> {out}")
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
