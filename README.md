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
