# 采集路由 — 各平台取评论（自包含，不再依赖 agent-reach）

本文件只在「需要采集评论」时读取。核心原则：

1. **动手前先体检**：登录态平台先确认登录态（douyin MCP `check_login_status` / 小红书 opencli 直接试）。
2. **只做读操作**：搜索、读帖、读评论。不写爬虫、不发帖、不点赞、不写评论。
3. **抓不到时的回退**（按顺序）：平台开放 API → 官方后台导出 → 用户手动复制。宁缺勿造。
4. **频率控制**：批量请求间隔 2-3 秒，高频会触发验证码；**小红书详情页/评论风控更严，间隔提到 8 秒**（见小红书专节）。
5. **采集结果存任务目录**，不写进 workspace。

## Windows / PowerShell 执行注意事项（2026-09-09 实测）

- 用 **`curl.exe`** 而不是 `curl`（PowerShell 里 `curl` 是 `Invoke-WebRequest` 别名）。
- 命令分隔用 **`;`** 而不是 `&&`（Windows PowerShell 5.1 不支持 `&&`，会报"标记不是此版本中的有效语句分隔符"）。
- 避免行内 `python -c "多行/含引号代码"`：PowerShell 解析器会打断内嵌引号（报"字符串缺少终止符"），把代码写成 `.py` 文件再执行。
- `>` 重定向产物编码不定（UTF-16LE / UTF-8-BOM / UTF-8）：解析时自动探测（本 skill 脚本已内置 `read_text()`）。
- opencli 参数 URL 含 `&` 会被 `.cmd` 截断：Python 子进程改用 node 直调 `main.js`（见小红书专节）。
- PowerShell 会把 stderr 输出标成红色"错误"（exit code -1），命令其实成功——以输出内容判断，不要被显示噪音误导。

## 平台路由

| 用户给的目标 | 第一选择 | 备选/回退 |
|---|---|---|
| **B站** 视频/搜索 | **官方 API 直连**（见下方专节，自带脚本） | bili-cli（`bili search/video`，只读免登录） |
| **小红书** 笔记/关键词 | `opencli xiaohongshu search/note/comments -f yaml`（浏览器登录态） | xiaohongshu MCP / xhs-cli；Jina Reader 读笔记页 |
| **抖音** 视频/关键词 | **douyin MCP**（见下方专节） | 创作者后台导出；手动复制 |
| **X/Twitter** 关键词 | `twitter search/tweet`（twitter-cli，需环境变量认证+Clash 代理，见专节） | `opencli twitter search -f yaml`（浏览器登录态）；feed/user-posts 绕路 |
| **YouTube** 视频 | `yt-dlp --write-comments --skip-download`（需代理） | `--dump-json` 取元数据 |
| **Reddit** 帖子 | `opencli reddit subreddit/read -f yaml`（search 不可用，见专节） | rdt-cli |
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
- **opencli 调用的 & 截断坑**：URL 里 `&xsec_source=` 会被 `.cmd` 批处理当命令分隔符截断。Python 子进程调用时改用 node 直调：
  `node "<npm 全局目录>/node_modules/@jackwener/opencli/dist/src/main.js" xiaohongshu comments "<URL>" -f yaml`（或 PowerShell 直接调 `opencli.cmd`）。
- **风控与降速（2026-09-09 实测）**：搜索页通常可通，但笔记详情页/评论会动态风控（`Navigation rejected`），触发后换新 token 也持续一段时间。应对：每次调用间隔 **8 秒**；被拒后等 8 秒重试 **1 次**；仍失败**降级为搜索元数据**（标题+点赞记入 `xhs_degraded.txt` 供简报使用），不中断整体。批量采集脚本见 `scripts/collect_xhs.py`。
- 报 AUTH_REQUIRED：浏览器里没登录小红书，让用户在 Chrome 登录一次。
- 风控窗口通常几小时到一天会过去；先在 Chrome 手动打开几篇笔记"预热"会话可降低被拒概率。

## 抖音（douyin MCP，Python 直连）

douyin MCP 项目装于本地（本机 `D:\data\Doubao\douyin-mcp`，Cookie 在项目根 `cookies.txt`，本地不上传）。

> ⚠️ **不要用 mcporter 调抖音**：`mcporter call douyin.*` 必现 `-32000 Connection closed`（实测死路）。
> 改用 **douyin-mcp 自带 .venv 的 Python 直接走 `mcp.client.stdio` 连 MCP**，脚本见 `scripts/collect_douyin.py`：

```bash
python scripts/collect_douyin.py <任务目录>/douyin --mcp-dir <douyin-mcp路径> --kws "AI副业,怎么做自媒体"
```

脚本自动完成：`check_login_status`（logged_in=false 直接跳过）→ 每个关键词 `search_videos`（sort_type=1 按点赞）取前 N 个视频 → `get_video_comments` 读评论（带请求超时、单请求失败跳过不中断）→ 输出 `douyin_combined.json`（rows: aweme_id/text/like/title/play，可直接喂 format_comments.py）。

手动调试（等号格式传参，函数式括号+冒号会被 mcporter 解析失败——但推荐直接用脚本）：
```bash
mcporter list                                          # 确认 douyin 在列（healthy 8 tools）
mcporter call douyin.check_login_status                # 先确认登录态
```

**字段映射**：
- 搜索列表在 `data[i].aweme_info`：`aweme_id`、`desc`→标题、`statistics.digg_count`→点赞、`statistics.comment_count`→评论数、`create_time`
- 评论对象：`content`→text（保留 `[表情]` 原文）、`like_count`→like（字符串转数字）、`comment_id`、`ip_location`、`sub_comment_count`

登录态失效（logged_in=false / 请求 403）：跳过抖音、简报注明，不中断整体。

## X / Twitter

**认证（2026-09-09 实测）**：twitter-cli 从运行中的浏览器提取 cookie 会失败，需手动配置用户级环境变量：
- 在 Chrome（已登录 x.com）按 F12 → Application → Cookies → x.com，复制 `auth_token` 与 `ct0` 两个值
- `setx TWITTER_AUTH_TOKEN "<值>"`、`setx TWITTER_CT0 "<值>"`（cookie 会过期，`twitter status` 报 not_authenticated 时重新导出）

**代理（必须）**：中国大陆直连 x.com 会被墙（curl 超时 / SSL 中断），调用前先注入：
```bash
$env:https_proxy = "http://127.0.0.1:7890"; $env:http_proxy = "http://127.0.0.1:7890"   # 或你的 Clash 地址
```

```bash
twitter status                        # 检查认证
twitter search "query" -n 10          # 搜索推文（GraphQL 端点偶发 404）
twitter tweet URL_OR_ID               # 读单条推文含回复（实测 1 条推文可读 49 条回复，含作者/赞/回复数/浏览）
twitter feed -n 20                    # 首页时间线（最稳定）
twitter user-posts @username -n 20    # 用户时间线

# 备选 OpenCLI（浏览器登录态，无需环境变量）
opencli twitter search "query" -f yaml
```

search 失败重试链：直接重试一次 → `pipx upgrade twitter-cli && twitter search ...` → `opencli twitter search -f yaml`（拿推文 URL）→ `twitter tweet URL` 读回复 → 改用 `feed`/`user-posts` 绕路。

## YouTube（需代理）

```bash
yt-dlp --proxy "http://127.0.0.1:7890" --write-comments --skip-download -o "<任务目录>/yt_%(id)s" "<视频URL>"
```

## Reddit（OpenCLI，浏览器登录态）

> ⚠️ **`opencli reddit search` 实测不可用**（`Pre-navigation to reddit.com failed: Navigation rejected`，与登录态无关）。
> 用 **subreddit / popular / read 通路**（2026-09-09 实测全部可用）：

```bash
opencli reddit subreddit sidehustle -f yaml   # 浏览板块热帖（副业相关：sidehustle/beermoney/learnprogramming/entrepreneur/freelance）
opencli reddit popular -f yaml                # 全站热门
opencli reddit read POST_ID -f yaml           # 帖子+评论（含 author/score/text，L0 评论层级）
opencli reddit subreddit-info <名称> -f yaml  # 板块元信息
```

- 要求 Chrome 打开且浏览器里登录过 reddit.com；中国大陆访问依赖浏览器走系统代理（Clash）。
- 采集流程：`subreddit` 拿热帖 ID → `read POST_ID` 读帖子+评论。
- 单个命令失败跳过注明，不中断整体。

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
