# AI大模型免费资源导航

**站点名：** AI大模型免费资源导航  
**主站（canonical）：** https://aiym168.github.io/  
**仓库：** https://github.com/aiym168/aiym168.github.io  

由 GitHub Actions 每 6 小时自动抓取、中文整理、构建并推送到 GitHub Pages（零人工）。

## 功能

- 深度百度 SEO：首页、分类页、条目详情页、日归档、JSON-LD、sitemap 索引/xml/txt、robots、404
- 可选百度普通收录推送（`BAIDU_PUSH_TOKEN`）

## 百度站长平台（需用户操作）

1. 打开 https://ziyuan.baidu.com 登录
2. 添加站点：`https://aiym168.github.io/`
3. 完成验证（HTML 标签或文件）。把验证码写入仓库：
   - Actions Secret `VERIFY_BAIDU`，或
   - `seo_config.json` 的 `baidu_site_verification`
4. 提交 sitemap：`https://aiym168.github.io/sitemap_index.xml`
5. 在站长平台创建「普通收录」推送 token，添加为仓库 Secret `BAIDU_PUSH_TOKEN`（可选）
6. **本仓库不会代为提交百度站长**——需你自己的百度账号完成以上步骤

## 全球优惠情报中心（deals/）

入口：https://aiym168.github.io/deals/index.html ，数据接口 `api/deals.json`。

- 采集：`deals_collect.py`（只用标准库，随每小时更新流程运行）——Epic 限免官方接口、币安活动/空投官方公告、KuCoin 活动官方公告、GitHub Changelog 与 OpenAI 官方 RSS（只收优惠类标题）、Doctor of Credit 与 LowEndBox 第三方 RSS（一律「待核实」）。
- 编辑核实条目：`data/deals/curated.json`。每条写明官方链接和 `verify` 关键文字，程序每 6 小时回访官方页面，文字还在才算「已核实」，否则自动改为「待核实」。只写官方页面上能看到的事实。
- 自动处理：标题指纹 + 官方链接去重、提取活动期间/截止时间、地区限制与隐藏条件（实名、新用户、名额、自动续费、绑卡）、参与类型（真正免费 / 免费试用 / 需要充值 / 需要交易量 / 需要邀请 / 付费折扣 / 抽奖）、按单人可得价值估值排序、过期自动归档。
- 大模型 API 最低价榜：`apiprice_collect.py` 每小时读取 OpenRouter 公开模型/端点接口、DeepInfra 与 Novita 公开模型列表和公开汇率接口，写入 `data/apiprices/`；`apiprice_build.py` 生成 `deals/api-prices.html` 与 `api/api-prices.json`。赞助位在 `data/sponsors.json`，默认为空、不显示。
- 页面：`deals_build.py` 生成 9 个模块页（A 今日最新、B 高价值排行、C AI、D Crypto、E 银行与银行卡、F VPS 与云、G 即将截止、H 已结束档案、I 软件与其他）和每条详情页。不要手改 `deals/` 下的页面。

## 本地

```bash
python3 fetch_auto.py
python3 build.py
```

## 数据接口 / 命令行

最简单（只读 JSON，不执行任何脚本）：

```bash
curl https://aiym168.github.io/api/latest.json
curl https://aiym168.github.io/api/v1/index.json      # v1：分页、字段定义、计数
```

命令行脚本：先下载、检查，再运行（不建议把远程脚本直接管道给 bash）：

```bash
curl -fsSLo ai168.sh https://aiym168.github.io/cli.sh
less ai168.sh
bash ai168.sh list
```

字段说明见 `api/v1/schema.json`：`requires_card` / `requires_realname` / `china_accessible` / `type` 无法从原文确定时为 `"unknown"`（页面显示“未注明”），`verified_at` 仅在对照官网核实后填写。

## 内容整理（curate.py）

每次构建都会经过 `curate.py`：相关性打分（不确定即排除）、去重、标题/摘要改写、Google News 跳转解析（解析不了即丢弃）、t.co 展开、截止时间提取、30 天归档、术语表修正（`glossary.py`）、规则分类与事实推断。人工核实的事实写在 `data/item_facts.json`，编辑整理条目在 `data/curated.json`。不要手改生成的页面（index.html、item/、c/、m/、archives/、api/）。
