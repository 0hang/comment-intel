#!/usr/bin/env python3
"""把平台采集的评论整理成 cheat-on-audience 的输入格式。

用法:
  python format_comments.py <input> [--out-dir <dir>]
                            [--video-id <id>] [--video-title <title>]
                            [--video-url <url>] [--play <n>] [--create-time <ts>]

输入自动识别三种格式:
  - JSON 数组: 字段名智能匹配(text/content/comment, like/digg_count,
    aweme_id/video_id/bvid, title, create_time, play)
  - CSV: 第一行表头, 同样智能匹配
  - 纯文本: 每行一条评论; 若行内含 Tab 则视为 "视频ID\t点赞\t正文"

输出到 <out-dir>:
  comments_raw.json   视频元数据数组(build_graph.py 必需)
  comments.txt        每行 "视频ID\t点赞\t正文"(LLM 抽取阶段读取)

只做确定性整理, 不改写评论原文。
"""
import argparse
import csv
import json
import os
import re
import sys

TEXT_KEYS = ('text', 'content', 'comment', 'body', 'comment_text', 'msg', '正文', '评论', '评论内容')
LIKE_KEYS = ('like', 'likes', 'like_count', 'likes_count', 'digg_count', 'agree', '点赞', '点赞数', 'likecnt')
VIDEO_KEYS = ('aweme_id', 'awemeid', 'video_id', 'videoId', 'vid', 'bvid', 'aid', 'item_id', '视频id', '视频ID')
TITLE_KEYS = ('title', 'video_title', 'desc', 'name', '标题')
TIME_KEYS = ('create_time', 'createtime', 'timestamp', 'publish_time', 'published_at', '发布时间')
PLAY_KEYS = ('play', 'play_count', 'view_count', 'views', '播放', '播放量')

VIDEO_ID_PATTERN = re.compile(r'(?:aweme_id|video_id|bvid|aid|item_id)["\']?\s*[:=]\s*["\']?(\w+)', re.I)


def find_key(obj, keys):
    for k in keys:
        if k in obj and obj[k] not in (None, ''):
            return k
    # 大小写不敏感兜底
    low = {str(k).lower(): k for k in obj}
    for k in keys:
        if k.lower() in low:
            v = obj[low[k.lower()]]
            if v not in (None, ''):
                return low[k.lower()]
    return None


def to_int(v):
    try:
        return int(float(str(v).replace(',', '').strip()))
    except (ValueError, TypeError):
        return 0


def to_str(v):
    return '' if v is None else str(v).strip()


def normalize_text(t):
    """正文里的 Tab/换行压成空格, 避免破坏 comments.txt 的列结构。"""
    return re.sub(r'[\t\r\n]+', ' ', to_str(t))


def guess_video_id(text, default):
    if default:
        return str(default)
    m = VIDEO_ID_PATTERN.search(text or '')
    if m:
        return m.group(1)
    return 'unknown'


def parse_rows(raw):
    """把输入解析成 [{video_id, like, text, title, create_time, play}]。"""
    rows = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                parts = item.split('\t')
                if len(parts) >= 3:
                    rows.append({'video_id': parts[0].strip(), 'like': to_int(parts[1]),
                                 'text': '\t'.join(parts[2:]),
                                 'title': '', 'create_time': '', 'play': 0})
                else:
                    rows.append({'video_id': '', 'like': 0, 'text': item,
                                 'title': '', 'create_time': '', 'play': 0})
                continue
            if not isinstance(item, dict):
                continue
            k = find_key(item, TEXT_KEYS)
            if not k:
                continue
            rows.append({
                'video_id': to_str(item.get(find_key(item, VIDEO_KEYS) or '', '')),
                'like': to_int(item.get(find_key(item, LIKE_KEYS) or '', 0)),
                'text': to_str(item.get(k)),
                'title': to_str(item.get(find_key(item, TITLE_KEYS) or '', '')),
                'create_time': item.get(find_key(item, TIME_KEYS) or '', ''),
                'play': to_int(item.get(find_key(item, PLAY_KEYS) or '', 0)),
            })
    return rows


def main():
    ap = argparse.ArgumentParser(description='整理评论为 cheat-on-audience 输入')
    ap.add_argument('input', help='输入文件路径')
    ap.add_argument('--out-dir', default='data', help='输出目录(默认 data)')
    ap.add_argument('--video-id', default='', help='默认视频 ID(单视频数据用)')
    ap.add_argument('--video-title', default='', help='默认视频标题')
    ap.add_argument('--video-url', default='', help='默认视频链接')
    ap.add_argument('--play', type=int, default=0, help='默认播放量')
    ap.add_argument('--create-time', default='', help='默认发布时间(unix 秒)')
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        sys.exit(f'输入文件不存在: {args.input}')

    with open(args.input, encoding='utf-8-sig') as f:
        head = f.read(2048)
        f.seek(0)
        if head.lstrip().startswith(('[', '{')):
            raw = json.load(f)
            # 兼容 dict 包裹的采集输出: 取 rows/comments/data 键里的列表
            if isinstance(raw, dict):
                for key in ('rows', 'comments', 'items', 'data', 'list'):
                    v = raw.get(key)
                    if isinstance(v, list):
                        raw = v
                        break
        elif ',' in head and ('text' in head.lower() or 'content' in head.lower() or 'comment' in head.lower()):
            reader = csv.DictReader(f)
            raw = list(reader)
        else:
            raw = [line.strip() for line in f if line.strip()]

    rows = parse_rows(raw)
    if not rows:
        sys.exit('未能从输入中解析出任何评论(需要 text/content/comment 字段或每行一条正文)')

    # 单视频数据: 统一补默认视频信息
    for r in rows:
        if not r['video_id']:
            r['video_id'] = args.video_id or 'unknown'
        if not r['title'] and args.video_title:
            r['title'] = args.video_title
        if not r['create_time'] and args.create_time:
            r['create_time'] = args.create_time
        if not r['play'] and args.play:
            r['play'] = args.play

    os.makedirs(args.out_dir, exist_ok=True)
    meta_path = os.path.join(args.out_dir, 'comments_raw.json')
    txt_path = os.path.join(args.out_dir, 'comments.txt')

    # 视频元数据: 按视频 ID 去重
    vids = {}
    for r in rows:
        vid = r['video_id']
        if vid not in vids:
            vids[vid] = {
                'aweme_id': vid,
                'title': r['title'] or vid,
                'create_time': r['create_time'] if r['create_time'] not in ('', 0, '0') else None,
                'play': r['play'] or 0,
            }
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(list(vids.values()), f, ensure_ascii=False, indent=1)

    with open(txt_path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(f"{r['video_id']}\t{r['like']}\t{normalize_text(r['text'])}\n")

    print(f'解析 {len(rows)} 条评论, 覆盖 {len(vids)} 个视频')
    print(f'  -> {meta_path}')
    print(f'  -> {txt_path}')
    if rows:
        print(f'  样例: {rows[0]["text"][:40]}')


if __name__ == '__main__':
    main()
