# -*- coding: utf-8 -*-
"""B站只读采集：搜索关键词 -> 高赞视频（含完整互动数据）-> 热门评论。绕开 OpenCLI，走官方 API 直连。
只读操作，不写任何内容、不写评论。

用法:
  python bili_collect.py [--ck <cookie文件>] [--out-dir <输出目录>] [--kws 词1,词2,...]

默认: cookie 用 <out-dir>\\bili_ck.txt（不存在则匿名请求，评论只能拿到少量热门）；
输出 bili_combined.json 到 <out-dir>（结构 {rows:[{aweme_id,text,like,title,play}], metas:{bvid:{title,play,like,review,author,duration,pubdate,stat}}}）。

搜索 API 自带基础信息（标题/UP主/播放/点赞/评论数/时长/标签）；
view API 补齐完整互动数据（view/danmaku/reply/favorite/coin/share/like，需 Origin 请求头）。

首次使用先拿 cookie（PowerShell）:
  curl.exe -s -c <out-dir>\\bili_ck.txt -o NUL -A "Mozilla/5.0 ... Chrome/126.0.0.0 Safari/537.36" "https://www.bilibili.com/"
"""
import argparse, json, time, urllib.request, urllib.parse, http.cookiejar, os

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DEFAULT_KWS = ["怎么做自媒体", "程序员接单", "AI副业", "知识付费", "副业"]


def build_opener(ck_path):
    cj = http.cookiejar.MozillaCookieJar(ck_path)
    try:
        cj.load()
    except Exception:
        pass
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def make_get(opener):
    def get(url, origin=False):
        headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
        if origin:
            headers["Origin"] = "https://www.bilibili.com"
        req = urllib.request.Request(url, headers=headers)
        for _ in range(3):
            try:
                with opener.open(req, timeout=20) as r:
                    return json.loads(r.read().decode('utf-8', 'replace'))
            except Exception:
                time.sleep(2)
        return None
    return get


def search(get, kw, limit=5):
    q = urllib.parse.quote(kw)
    d = get(f"https://api.bilibili.com/x/web-interface/search/all/v2?keyword={q}&page=1")
    if not d or d.get('code') != 0:
        return []
    out = []
    for blk in d.get('data', {}).get('result', []):
        if blk.get('result_type') == 'video':
            for v in blk['data']:
                if v.get('bvid'):
                    out.append({
                        'bvid': v['bvid'], 'aid': v.get('id'), 'title': v.get('title', ''),
                        'author': v.get('author', ''), 'play': v.get('play', 0),
                        'like': v.get('like', 0), 'review': v.get('review', 0),
                    })
            break
    return out[:limit]


def view_detail(get, aid):
    """完整视频详情：stat 含 view/danmaku/reply/favorite/coin/share/like，另含 owner/duration/pubdate。"""
    d = get(f"https://api.bilibili.com/x/web-interface/view?aid={aid}", origin=True)
    if not d or d.get('code') != 0:
        return {}
    s = d.get('data') or {}
    owner = (s.get('owner') or {}).get('name', '')
    return {
        'duration': s.get('duration', 0),
        'pubdate': s.get('pubdate', 0),
        'owner': owner or s.get('tname', ''),
        'stat': s.get('stat', {}),
    }


def comments(get, bvid, aid, limit=30):
    rows = []
    for page in (0, 1):
        d = get(f"https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=3&next={page}")
        if not d or d.get('code') != 0:
            break
        reps = (d.get('data') or {}).get('replies') or []
        if not reps:
            break
        for x in reps:
            rows.append({'aweme_id': bvid, 'text': x['content']['message'], 'like': x.get('like', 0)})
            if len(rows) >= limit:
                return rows
        time.sleep(1)
    return rows


def main():
    ap = argparse.ArgumentParser(description='B站官方API直连采集（只读，含视频完整互动数据）')
    ap.add_argument('--ck', default='', help='cookie 文件路径（默认 <out-dir>/bili_ck.txt）')
    ap.add_argument('--out-dir', default='.', help='输出目录（默认当前目录）')
    ap.add_argument('--kws', default=','.join(DEFAULT_KWS), help='逗号分隔关键词列表')
    args = ap.parse_args()

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    ck = args.ck or os.path.join(out_dir, 'bili_ck.txt')
    kws = [k.strip() for k in args.kws.split(',') if k.strip()]

    opener = build_opener(ck)
    get = make_get(opener)

    all_rows, metas, done = [], {}, set()
    for kw in kws:
        print(f"== 搜索: {kw}")
        vs = search(get, kw, 4)
        for v in vs:
            if v['bvid'] in done:
                continue
            done.add(v['bvid'])
            detail = view_detail(get, v['aid'])
            meta = {k: v[k] for k in ('title', 'play', 'like', 'review', 'author')}
            meta.update({k: detail.get(k) for k in ('duration', 'pubdate', 'owner', 'stat')})
            metas[v['bvid']] = meta
            cs = comments(get, v['bvid'], v['aid'], 30)
            for c in cs:
                c['title'] = v['title']
                c['play'] = v['play']
            all_rows.extend(cs)
            print(f"  {v['bvid']} {v['title'][:30]} 评论{len(cs)} 赞{meta['like']} 播{meta['play']}")
            time.sleep(1)

    out_path = os.path.join(out_dir, 'bili_combined.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({"rows": all_rows, "metas": metas}, f, ensure_ascii=False, indent=1)
    print(f"\nTOTAL {len(all_rows)} 条评论, {len(metas)} 个视频（含完整 stat） -> {out_path}")


if __name__ == '__main__':
    main()
