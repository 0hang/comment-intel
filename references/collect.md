# 采集路由 — 各平台取评论（自包含，不再依赖 agent-reach）

本文件只在「需要采集评论」时读取。核心原则：

1. **动手前先体检**：登录态平台先确认登录态（douyin MCP `check_login_status` / 小红书 opencli 直接试）。
2. **只做读操作**：搜索、读帖、读评论。不写爬虫、不发帖、不点赞、不写评论。
3. **抓不到时的回退**（按顺序）：平台开放 API → 官方后台导出 → 用户手动复制。宁缺勿造。
4. **频率控制**：批量请求间隔 2-3 秒，高频会触发验证码（小红书尤其明显）。
5. **采集结果存任务目录**，不写进 workspace。

## 平台路由

| 用户给的目标 | 第一选择 | 备选/回退 |
|---|---|---|
| **B站** 视频/搜索 | **官方 API 直连**（见下方专节，自带脚本） | bili-cli（`bili search/video`，只读免登录） |
| **小红书** 笔记/关键词 | `opencli xiaohongshu search/note/comments -f yaml`（浏览器登录态） | xiaohongshu MCP / xhs-cli；Jina Reader 读笔记页 |
| **抖音** 视频/关键词 | **douyin MCP**（见下方专节） | 创作者后台导出；手动复制 |
| **X/Twitter** 关键词 | `twitter search "query" -n 10`（twitter-cli） | `opencli twitter search -f yaml`（浏览器登录态）；feed/user-posts 绕路 |
| **YouTube** 视频 | `yt-dlp --write-comments --skip-download`（需代理） | `--dump-json` 取元数据 |
| **Reddit** 帖子 | `opencli reddit read POST_ID -f yaml`（登录态） | rdt-cli |
| **V2EX** | 公开 API（无需登录） | — |
| 通用网页/文章 | `curl -s "https://r.jina.ai/URL"` | 用户手动复制 |

## B站 — 官方 API 直连（2026-09-08 实测，免登录）

OpenCLI 的 bilibili 通道会报 Navigation rejected；不要用 yt-dlp 读 B 站（风控 412）。直接跑本 skill 自带脚本：

```bash
python scripts/bili_collect.py --out-dir <任务目录>/bilibili --kws "怎么做自媒体,程序员接单,AI副业,知识付费,副业"
```

脚本自动完成：拿 cookie → 搜索 API 取高赞视频（含完整互动数据 stat：view/danmaku/reply/favorite/coin/share/like）→ 评论 API（mode=3 热度排序，翻 2 页）→ 输出 `bili_combined.json`：
- `rows`：评论数组（`aweme_id`/`text`/`like`/`title`/`play`，可直接喂 format_comments.py）
- `metas`：视频元数据（bvid → title/play/like/review/author/duration/pubdate/stat）

首次使用先拿 cookie（PowerShell 必须用 `curl.exe`，`curl` 是 Invoke-WebRequest 别名）：
```bash
curl.exe -s -c <任务目录>/bilibili/bili_ck.txt -o NUL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36" "https://www.bilibili.com/"
```

手动 curl 调试：
```bash
# 搜索（解析 result[] 里 result_type=video：bvid/aid/标题/play/like/review）
curl.exe -s -b bili_ck.txt -A <UA> -e "https://www.bilibili.com/" "https://api.bilibili.com/x/web-interface/search/all/v2?keyword=<URL编码>&page=1"
# 评论（字段映射 content.message→text、like→like、aweme_id=bvid；next=0/1 翻页）
curl.exe -s -b bili_ck.txt -A <UA> -e "https://www.bilibili.com/" "https://api.bilibili.com/x/v2/reply/main?type=1&oid=<aid>&mode=3&next=0"
```

## 小红书（OpenCLI 首选，浏览器登录态）

```bash
opencli xiaohongshu search "关键词" -f yaml        # 搜索笔记
opencli xiaohongshu note "<完整explore URL含xsec_token>" -f yaml  # 读笔记
opencli xiaohongshu comments "<完整explore URL含xsec_token>" -f yaml  # 评论（支持楼中楼）
opencli xiaohongshu feed -f yaml                  # 首页推荐
```

- **xsec_token 限制**：必须用搜索结果里的完整 explore URL（含 `xsec_token`），**不能用裸 note_id**。
- 偶发 Navigation rejected：等 3-5 秒重试一次。
- 报 AUTH_REQUIRED：浏览器里没登录小红书，让用户在 Chrome 登录一次。
- 频率：每次操作间隔 2-3 秒，高频触发验证码。

## 抖音（douyin MCP，本机已部署）

douyin MCP 已注册进 mcporter（本项目装于 `D:\data\Doubao\douyin-mcp`，Cookie 在项目根 `cookies.txt`，本地不上传）。**PowerShell 下用等号格式传参**（函数式括号+冒号会被 mcporter 解析失败）：

```bash
mcporter list                                          # 确认 douyin 在列（healthy 8 tools）
mcporter call douyin.check_login_status                # 先确认登录态
mcporter call douyin.search_videos 'keyword="AI工具"' 'count=10' 'sort_type=1'   # 1=按点赞排序
mcporter call douyin.get_video_detail 'aweme_id="<ID>"'                          # 视频标题/点赞/评论数
mcporter call douyin.get_video_comments 'aweme_id="<ID>"' 'count=50'             # 读评论
```

流程：`search_videos`（关键词 + 按点赞排序）→ 取前 N 个视频 ID → `get_video_detail` 拿标题/播放 → `get_video_comments` 读评论。

**字段映射**：
- 搜索列表在 `data[i].aweme_info`：`aweme_id`、`desc`→标题、`statistics.digg_count`→点赞、`statistics.comment_count`→评论数、`create_time`
- 评论对象：`content`→text（保留 `[表情]` 原文）、`like_count`→like（字符串转数字）、`comment_id`、`ip_location`、`sub_comment_count`

登录态失效（logged_in=false / 请求 403）：跳过抖音、简报注明，不中断整体。

## X / Twitter

```bash
# 首选 twitter-cli
twitter search "query" -n 10        # 搜索推文（GraphQL 端点偶发 404）
twitter tweet URL_OR_ID             # 读单条推文含回复
twitter feed -n 20                  # 首页时间线（最稳定）
twitter user-posts @username -n 20  # 用户时间线

# 备选 OpenCLI（浏览器登录态）
opencli twitter search "query" -f yaml
```

search 失败重试链：直接重试一次 → `pipx upgrade twitter-cli && twitter search ...` → `opencli twitter search -f yaml` → 改用 `feed`/`user-posts` 绕路。

## YouTube（需代理）

```bash
yt-dlp --proxy "http://127.0.0.1:7890" --write-comments --skip-download -o "<任务目录>/yt_%(id)s" "<视频URL>"
```

## Reddit（必须登录态）

```bash
opencli reddit search "query" -f yaml   # 搜索
opencli reddit read POST_ID -f yaml     # 帖子+评论
```

历史实测 OpenCLI reddit 偶发 Navigation rejected——失败则跳过注明。

## 通用网页

```bash
curl -s "https://r.jina.ai/URL"   # Jina Reader 转 markdown
```

## 采集时的字段要求

采集结果尽量保留（缺失不阻塞，格式化脚本补默认值）：

- **评论正文**（必需）— text / content / comment
- **点赞数**（强烈建议）— like / digg_count
- **视频 ID**（强烈建议）— aweme_id / bvid / video_id
- 视频标题、发布时间、播放量（可选，进图谱节点）

## 输出交接

采集文件（JSON/CSV/纯文本均可）交给主流程下一步：

```bash
python scripts/format_comments.py <采集文件> --out-dir <任务目录>/data \
    [--video-id <默认视频ID>] [--video-title <默认标题>] [--video-url <链接>] \
    [--play <播放量>] [--create-time <发布时间戳>]
```
