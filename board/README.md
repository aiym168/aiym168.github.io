# 匿名留言板 · 星际信号站

页面：`/m/board.html`（由 `build.py` → `board/page.py` 生成），前端 `vendor/board.js`（three.js 星系）。

## 数据流（零服务器、零账号、零费用）
1. 访客浏览器：客户端预检（`vendor/board-rules.json`）→ 工作量证明（SHA-256 前缀 `0000`）→
   RSA-OAEP-2048 + AES-GCM-256 加密 → POST 到公共中继 `https://ntfy.sh/<topic>`（无需登录，缓存 12 小时）。
2. GitHub Actions `board.yml`（每 10 分钟）：拉取中继缓存 → 用仓库密钥 `BOARD_PRIVATE_KEY` 解密 →
   蜜罐 / 停留时间 / 工作量证明 / 每设备限速 / 全站日上限 → `board/filter.py` 严格审核 →
   通过的写入 `data/board/messages.json` 并发布 `api/board.json`。被拦截的内容**不会写入任何地方**，
   只在 `api/board_receipts.json` 里留一个随机回执号 + 原因码，供发送者页面显示“已拦截”。

## 审核（服务器端，默认拒绝）
- 归一化：NFKC（全角→半角）、小写、去零宽/控制字符、繁→简（OpenCC）、变体字映射、去掉字间空格/符号/表情。
- 词库：konsheng/Sensitive-lexicon（MIT，来源见 `lexicon/konsheng/`，编译并 gzip 为 `lexicon/base.txt.gz`）+ `custom_block.txt`，Aho-Corasick 匹配。
- 拼音/谐音：`pinyin_words.txt` 中的高危词按音节对齐匹配（同音字、全拼、首字母混写，如 席近平 / xi近平 / 傻b）。
- 缩写：`abbr.txt`、`latin_substring.txt`（sb / nmsl / cnm / tmd / xjp / fuck …），先剔除 `allow_latin.txt` 中的技术词。
- 联系方式与链接：网址、域名（含“点com”）、邮箱、≥5 位数字（含中文数字、①②）、QQ / 微信 / TG 前缀。
- 昵称同样审核；内容需含至少 2 个汉字；200 字上限。
- 测试：`python -m board.filter < 文本文件`。修改词库后运行 `python -m board.build_lexicon 语料.txt` 重新编译。

## 隐藏一条留言
- 在 `data/board/hidden.txt` 里加一行信号编号（如 `M-7F3A2C`），提交后自动触发审核任务并移除；或
- 在 GitHub → Actions → “Board ingest” → Run workflow，填入编号。
