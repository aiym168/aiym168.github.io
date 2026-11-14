# AI大模型免费资源导航

**站点名：** AI大模型免费资源导航  
**主站（canonical）：** https://aiym168.github.io/  
**仓库：** https://github.com/aiym168/aiym168.github.io  

由自动任务抓取、中文整理、构建并推送到 GitHub Pages（零人工）。GitHub 的定时任务不是唯一保证，见下面「自动更新靠什么保证」。

## 自动更新靠什么保证

GitHub Actions 的 `schedule` 会在平台忙的时候被静默丢掉：那一次既不会成功，也不会失败。所以定时任务不是内容更新的唯一保证。公开内容超过 75 分钟，就会跑完整的采集和发布（心跳、只签到的提交不算）。

还有两条不依赖 GitHub 定时器的路：

1. **备用服务器自己的唤醒时刻。** 服务商在每小时的第 19 分和第 49 分把服务器叫醒，并保持 20 分钟。服务器里的任务在第 20 分和第 50 分检查；内容已经旧于 75 分钟就发布。这个唤醒不需要有人去开机。两次唤醒之间留有空隙，避免上一段“保持醒着”的结束和下一次唤醒撞在同一分钟、服务器反而继续睡过整点。
2. **仓库以外的免费定时请求。** 它调用 GitHub 的 `repository_dispatch`，流水线跑在 GitHub 托管的机器上。备用服务器可以一直睡着，GitHub 的定时器也可以被丢掉。这一条要等下面的一次性设置做完，并且本变更已经在默认分支上，才会开始。

错过的定时点写在 `data/_internal_status.json` 的 `schedule_health` 里：内容年龄、引擎 A 缺了哪几次、看门狗缺了哪几次。看门狗每次实际跑完会把这份记录提交上去，提交说明是「status check」，那不是一次内容更新。对外页面不写这些。

### 需要你做的一次设置（免费）

没有这一步时，第 1 条仍然有效。第 2 条要等令牌和定时任务建好。

1. 打开 GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token。
2. 只选择仓库 `aiym168/aiym168.github.io`。权限只给 **Contents: Read and write**。设一个到期日；到期前换一次令牌，否则外部定时会悄悄停掉。这个令牌能推送本仓库的代码，不要写进仓库，也不要发给别人。
3. 打开 https://cron-job.org 注册（服务本身不收费，最短可以每分钟一次）。新建一个任务：
   - 地址：`https://api.github.com/repos/aiym168/aiym168.github.io/dispatches`
   - 时间：每 15 分钟
   - 方法：POST
   - 请求头：
     - `Accept: application/vnd.github+json`
     - `Authorization: Bearer <刚生成的令牌>`
     - `X-GitHub-Api-Version: 2022-11-28`
     - `Content-Type: application/json`
   - 正文：`{"event_type":"keepalive"}`
4. 用它的测试运行。GitHub 返回 **204**（没有正文）就是成功。Actions 里会出现 “External keepalive”。
5. 本变更进入默认分支后，在 Actions 里手动运行一次 “Watchdog (self-heal)”，把备用服务器的唤醒窗口写成上面的新时刻。不跑的话，要等下一次看门狗或这次外部保活自己去写。服务器上的钟点会在它下一次启动任务时自己改过来。

也可以不建 cron-job.org，改用任何能发带请求头的 POST 的免费定时器，地址和正文同上。

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
