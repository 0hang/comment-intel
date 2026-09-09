# Changelog

## v0.2.0 (2026-09-09)

- 采集通道实测更新（references/collect.md）：
  - **抖音**：mcporter 调抖音必现 Connection closed，改用 douyin-mcp .venv Python `mcp.client.stdio` 直连（新增 `scripts/collect_douyin.py`，带超时与单请求失败跳过）
  - **小红书**：详情页/评论动态风控应对——8 秒降速 + 重试 1 次 + 降级为搜索元数据；opencli 用 node 直调绕开 `.cmd` 截断 URL `&` 参数（新增 `scripts/collect_xhs.py`）
  - **X/Twitter**：补认证配置（TWITTER_AUTH_TOKEN/TWITTER_CT0 环境变量）与 Clash 代理注入；`twitter tweet` 实测可读单条推文含回复
  - **Reddit**：`opencli reddit search` 实测不可用，改走 `subreddit` / `popular` / `read` 通路（副业相关板块示例）
  - **Windows/PowerShell 执行注意事项**：`curl.exe`、`;` 代替 `&&`、避免行内 `python -c`、重定向编码自动探测、node 直调绕 `&` 截断

## v0.1.0 (2026-09-08)

- 首个开源版本：评论区情报自包含 skill
- 多平台只读采集：B站官方 API 直连（自带脚本，含视频完整互动数据）、小红书 OpenCLI、抖音 MCP、X/twitter-cli、YouTube yt-dlp、Reddit
- 图谱分析流水线：格式化 → 词表定制 → 逐条抽取 → 建图渲染（atlas.html 零依赖）
- 交付解读：关注点 TOP / 内容缺口选题 / 共现簇 / 金句库 / 成果案例
- 每日多平台关键词情报简报（飞书文档交付）流程
