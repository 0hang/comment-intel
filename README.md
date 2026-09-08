# Comment Intel — 评论区情报

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

把「评论区」从散装文本变成可交互、可追溯的知识图谱，并产出可直接用的内容结论：**关注点 TOP 榜、内容缺口选题、共现簇、金句库、成果案例**。

自包含单 Skill：多平台采集（只读）→ 格式化 → 定制词表 → 逐条抽取 → 建图渲染 → 交付解读/每日飞书简报，全部内置，不依赖其他 skill。

## 它能做什么

- **即时分析**：给一个平台链接或一批评论文件 → 输出可交互知识图谱 `atlas.html` + 五类内容结论
- **每日情报简报**：定时跑多平台关键词采集（抖音/小红书/B站/X/YouTube）→ 分析 → 生成飞书文档发送

## 快速开始

```bash
# 1. 安装（放到任意 skill root，如 ~/.agents/skills/comment-intel）
# 2. 采集（以 B站为例，其余平台见 references/collect.md）
python scripts/bili_collect.py --out-dir ./bilibili --kws "怎么做自媒体,程序员接单,AI副业"

# 3. 格式化
python scripts/format_comments.py ./bilibili/bili_combined.json --out-dir ./data

# 4. 定制 references/schema.md 词表（采样 30-50 条评论后）→ LLM 逐条抽取到 data/extracted_*.json

# 5. 建图 + 渲染
python scripts/build_graph.py
python scripts/render.py        # 产出 atlas.html，零依赖单文件，双击即开
```

## 平台支持（全部只读）

| 平台 | 通道 | 登录态 |
|---|---|---|
| B站 | 官方 API 直连（自带脚本 `scripts/bili_collect.py`） | 免登录 |
| 小红书 | OpenCLI（浏览器登录态） | 需要 |
| 抖音 | douyin MCP（Cookie 本地） | 需要 |
| X/Twitter | twitter-cli / OpenCLI | 需要 |
| YouTube | yt-dlp + 代理 | 可匿名 |
| Reddit | OpenCLI | 需要 |

详细命令、字段映射、登录态与频率控制见 [`references/collect.md`](references/collect.md)。

## 工作流

```
采集（多平台，只读）→ format_comments.py 格式化
→ 采样通读 30-50 条 → 定制 schema.md 词表
→ LLM 逐条抽取（is_sarcasm 阴阳怪气 / is_ask 提问 / is_win 成果）
→ build_graph.py 建图（每条边挂评论原文证据）
→ render.py 渲染 atlas.html → 交付五类结论 / 每日飞书简报
```

## 目录结构

```
comment-intel/
├── SKILL.md              # 主流程（即时分析 + 每日简报）
├── references/
│   ├── collect.md        # 采集路由（各平台命令/字段映射/登录态）
│   └── schema.md         # 抽取规范（字段定义 + 词表）
├── scripts/
│   ├── bili_collect.py   # B站官方API直连采集（含视频完整互动数据）
│   ├── format_comments.py# 评论整理为标准输入
│   ├── build_graph.py    # 抽取结果 → graph.json（证据链建图）
│   ├── render.py         # graph.json → atlas.html（零依赖交互图谱）
│   └── export.py         # 发布：GitHub Pages / mermaid / digest / llms.txt
├── templates/viewer.html # 渲染模板
└── docs/                 # GitHub Pages 产物（.nojekyll）
```

## 隐私与安全

- 只做读操作：搜索、读帖、读评论。不写爬虫、不发帖、不点赞、不写评论
- 登录态平台的 Cookie 只存本地，不上传
- `graph.json` 含评论原文（不含昵称 UID）；发布公开仓库前由你决定
- 高频请求会触发平台验证码，采集间隔 2-3 秒

## 依赖

- Python 3.10+
- 平台通道：opencli（小红书/X/Reddit）、douyin MCP（抖音）、twitter-cli（X）、yt-dlp（YouTube）、curl.exe（B站）
- 飞书交付：lark-doc 能力（每日简报场景）

## 致谢

- 采集路由与平台命令整合自 [Agent-Reach](https://github.com/Panniantong/Agent-Reach)
- 图谱分析流程、schema 与脚本（build_graph/render/export）整合自 [cheat-on-audience](https://github.com/XBuilderLAB/cheat-on-audience)

## License

[MIT](LICENSE)
