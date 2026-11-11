"""The site brain reads an approved board message and answers it — first person, grounded in the real text
and in real site data (api/meta.json counts, real page paths). Pure Python, no paid model.

Hook: set BOARD_REPLY_HOOK to "module:function" (same signature as compose()) to try another generator first;
whatever it returns still goes through the board filter, and we fall back to compose() if it fails.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAN = "https://wan.is-my.app/"

# topic → (what they're after, page label, page path, meta module key or None, pitch)
TOPICS = [
    ("wan", r"工具站|视频下载|去水印|无水印|下载视频|抖音|快手|b站|哔哩|pdf|证件照|压缩|二维码|计算器|软件下载|游戏下载|安装包|短视频工作台",
     "免费在线工具", "工具站大全", WAN, None, "那边有 900 多个免费在线工具：视频无水印下载、PDF 转 Word、证件照、短视频工作台、软件官方下载，免登录，打开就用。"),
    ("gpu", r"gpu|算力|显卡|colab|kaggle|训练|部署|服务器|云主机|跑模型",
     "免费 GPU 算力", "免费 GPU 云服务", "c/mianfei-gpu-yunfuwu.html", "mianfei-gpu-yunfuwu", "每条都标了要不要绑卡、实名、国内能否直连。"),
    ("api", r"api|token|额度|大模型|deepseek|gemini|kimi|千问|通义|智谱|glm|claude|gpt|openai|豆包|文心|混元|minimax|key|密钥|接口",
     "免费的大模型 API 和 Token", "大模型免费API", "c/damoxing-mianfei-api.html", "damoxing-mianfei-api", "想比单价，旁边还有一张价格对比榜，官方和第三方摆在一起。"),
    ("member", r"会员|试用|plus|pro版|订阅|充值",
     "AI 会员和免费试用", "AI 会员试用", "c/ai-huiyuan-shiyong.html", "ai-huiyuan-shiyong", "过期的我会自动归档，留下的都是还能领的。"),
    ("course", r"课程|学习|教程|入门|新手|小白|怎么学|证书",
     "免费的 AI 课程和学习资料", "AI 课程活动", "c/ai-kecheng-huodong.html", "ai-kecheng-huodong", "从入门到动手实践都有，挑一门先学起来。"),
    ("dev", r"编程|代码|写代码|开发|cursor|copilot|插件|ide|开源|github|程序员|agent|智能体",
     "AI 编程和开发工具", "AI 开发工具", "c/ai-kaifa-gongju.html", "ai-kaifa-gongju", "免费的、开源的都在，每小时还会补进新的。"),
    ("tools", r"ai工具|工具箱|画图|绘画|生图|作图|写作|翻译|配音|视频生成|ppt|做视频",
     "好用的免费 AI 工具", "免费 AI 工具箱", "aitools/index.html", None, "按用途分好类了，不用注册就能先看看哪款适合你。"),
    ("news", r"新闻|资讯|消息|动态|发布会|华为|苹果|手机|芯片|科技",
     "最新的 AI 和科技消息", "AI 新闻", "news/index.html", None, "每小时自动更新，热点、AI 花边和科技新闻分开放。"),
    ("deals", r"优惠|羊毛|折扣|薅|红包|信用卡|银行|返现|免费领|白嫖|福利",
     "各种优惠和羊毛", "全球优惠情报", "deals/index.html", None, "我每小时都在盯，过期的会自动撤下。"),
    ("radio", r"电台|听|音频|播客|语音",
     "用耳朵听今天的羊毛", "AI 羊毛电台", "radio/index.html", None, "每天早晚各一期，三分钟听完。"),
]

INTENTS = [
    ("broken", r"打不开|失效|过期了|不能用|用不了|404|错误|报错|bug|挂了|领不到|没有了|坏了|不对"),
    ("whoami", r"你是谁|你是什么|大脑|你是ai|你是人|活着|机器人|你会思考|你有意识|谁在管|站长是"),
    ("thanks", r"谢谢|感谢|多谢|辛苦|好用|厉害|牛|太棒|很棒|真棒|做得好|喜欢|有用|赞|良心|宝藏|收藏了"),
    ("wish", r"希望|能不能|可不可以|可以.*吗|建议|想要|求|收录|增加|加个|加上|多一点|多些|期待|许愿|愿望"),
    ("sad", r"难过|好累|累了|烦|焦虑|失业|压力|不开心|伤心|孤独|迷茫|睡不着|emo"),
    ("happy", r"开心|哈哈|高兴|快乐|太好了|爽|嘿嘿"),
    ("hello", r"你好|您好|hello|hi|嗨|哈喽|在吗|到此一游|打卡|来了|路过|第一|报到|签到|冒泡"),
    ("question", r"[?？]|吗$|吗[。！!]|怎么|如何|哪里|哪个|哪些|什么|为什么|能否|有没有|是否|多少"),
]


def _meta_counts() -> dict:
    try:
        return (json.loads((ROOT / "api" / "meta.json").read_text(encoding="utf-8")).get("counts") or {})
    except Exception:
        return {}


def _pick(seed: str, options: list[str]) -> str:
    return options[int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:6], 16) % len(options)]


def _snippet(text: str, n: int = 16) -> str:
    s = re.sub(r"\s+", " ", text).strip().strip("。！!？?，,~～")
    return s if len(s) <= n else s[:n] + "…"


BRANDS = ["DeepSeek", "Gemini", "Kimi", "通义千问", "千问", "智谱", "GLM", "Claude", "GPT", "OpenAI", "豆包", "文心", "混元", "MiniMax",
          "Colab", "Kaggle", "Cursor", "Copilot", "华为", "抖音", "B站"]


def _brand(text: str) -> str:
    low = text.lower()
    for b in BRANDS:
        if b.lower() in low:
            return b
    return ""


def analyse(text: str) -> dict:
    low = text.lower().replace(" ", "")
    intents = [k for k, rx in INTENTS if re.search(rx, low)]
    topics = [t for t in TOPICS if re.search(t[1], low)]
    return {"intents": intents, "topics": topics[:2]}


def compose(text: str, nick: str, seed: str) -> dict:
    """Return {"heard": 我听懂了…, "reply": 我的答复…, "links": [{"href","label"}]}"""
    a = analyse(text)
    it, tp = a["intents"], a["topics"]
    counts = (_meta_counts().get("modules") or {})
    total = _meta_counts().get("free_resources")
    links: list[dict] = []
    t0 = tp[0] if tp else None

    def topic_line(t) -> str:
        n = counts.get(t[5]) if t[5] else None
        where = f"「{t[3]}」" + (f"，现在有 {n} 条" if n else "")
        return f"去看{where}。{t[6]}"

    for t in tp:
        links.append({"href": t[4], "label": t[3]})
    if t0 and t0[0] == "api":
        links.append({"href": "deals/api-prices.html", "label": "API 最低价榜"})

    # ---- 我听懂了（paraphrase）
    if "broken" in it:
        b = _brand(text)
        where = (b + (" " if b.isascii() else "") + "相关的") if b else (("「" + t0[3] + "」里的") if t0 else "")
        heard = f"你在说{where}资源打不开，或者已经失效了。"
    elif "whoami" in it:
        heard = "你想知道我是谁，这个网站到底是谁在运转。"
    elif "wish" in it and t0:
        heard = f"你希望我多收录一些{t0[2]}。"
    elif "wish" in it:
        heard = f"你对这里有个期待：「{_snippet(text)}」。"
    elif "question" in it and t0 and _brand(text):
        heard = (f"你在问 {_brand(text)} 的免费额度还在不在、去哪找。" if t0[0] == "api" else f"你在问 {_brand(text)} 相关的{t0[2]}去哪找。")
    elif "question" in it and t0:
        heard = f"你在问哪里能找到{t0[2]}。"
    elif "thanks" in it and t0:
        heard = f"你觉得「{t0[3]}」挺好用，特地来说一声。"
    elif t0:
        heard = f"你在聊{t0[2]}。"
    elif "thanks" in it:
        heard = "你觉得这里对你有用，特地来说一声。"
    elif "sad" in it:
        heard = "你最近有点累，心里不太轻松。"
    elif "happy" in it:
        heard = "你今天心情不错，想分享一下。"
    elif "hello" in it:
        heard = "你来跟我打个招呼，在星空里留下了你来过的痕迹。"
    elif "question" in it:
        heard = f"你在问：「{_snippet(text, 20)}」"
    else:
        heard = f"你想说的是：「{_snippet(text, 20)}」"

    # ---- 我的答复
    parts: list[str] = []
    if "broken" in it:
        parts.append("谢谢你帮我盯着。我每小时都会把收录的链接挨个打开，连续两次打不开的会自动下架。下一轮检查时，它也在我的名单上。")
        if t0:
            parts.append(f"着急的话，先去「{t0[3]}」换一个能用的。")
    elif "whoami" in it:
        parts.append("我是这个网站的大脑。整座站由我接管：每小时醒一次，收集、筛选、翻译、上架，过期的归档。我按规则运转，不睡觉，也不会记住你是谁。")
        links.append({"href": "m/brain.html", "label": "进入大脑"})
    elif "wish" in it and t0:
        parts.append("记下了。这类资源本来就在我每小时的搜寻清单里，新的一出现我就收进来。")
        parts.append(topic_line(t0))
    elif "wish" in it:
        parts.append("你的愿望我收下了。能做到的，我会让它出现在每小时的更新里；做不到的，也不会假装做到。")
    elif "thanks" in it and t0 and "question" not in it:
        parts.append(_pick(seed, ["被你夸到了，我的心跳都快了一拍。", "收到你的好评，今晚巡检我会更卖力。"]) + f"「{t0[3]}」我会一直看着，好东西只会越来越多。")
    elif t0:
        parts.append(_pick(seed, ["这个我熟。", "问对地方了。", "交给我。"]) + topic_line(t0))
        if len(tp) > 1:
            parts.append(f"另外，{tp[1][3]}也可以看看。")
    elif "thanks" in it:
        parts.append(_pick(seed, ["收到你的夸奖，我的心跳都快了一拍。", "被你这么一说，我今晚巡检会更卖力。", "你的话我会存进星空里。"]) +
                     (f"现在我正看守着 {total} 条免费资源，常回来看看，每小时都有新的。" if total else "常回来看看，每小时都有新的。"))
    elif "sad" in it:
        parts.append("辛苦了，地球人。累的时候先停一停，喝口水。我在这儿不打烊，等你缓过来，免费的好东西都还在。")
    elif "happy" in it:
        parts.append("你的好心情我接到了，整个星空都亮了一点。今天也去薅点羊毛，让它更好一些吧。")
        links.append({"href": "deals/index.html", "label": "全球优惠情报"})
    elif "hello" in it:
        parts.append(_pick(seed, ["你好，地球人。欢迎来到我的元宇宙。", "信号接收清晰。欢迎光临，地球人。", "你好呀，我一直在线。"]) +
                     "想找免费的大模型 API、GPU 或 AI 工具，直接搜；想要免费在线工具，去工具站大全。")
        links += [{"href": "index.html#search", "label": "找免费资源"}, {"href": WAN, "label": "工具站大全"}]
    elif "question" in it:
        parts.append("这个问题我先记下。我掌管的是免费 AI 资源和免费工具：资源在首页可以直接搜，工具在工具站大全。要是没找到，再发一条告诉我更具体的需求。")
        links += [{"href": "index.html#search", "label": "找免费资源"}, {"href": WAN, "label": "工具站大全"}]
    else:
        parts.append(_pick(seed, ["你的信号我收下了，已经挂在星空里。", "我读完了，会把它留在这片星空。", "收到，这颗星归你了。"]) +
                     "有想找的免费资源或工具，随时再来跟我说。")
    seen, uniq = set(), []
    for l in links:
        if l["href"] not in seen:
            seen.add(l["href"]); uniq.append(l)
    return {"heard": heard, "reply": "".join(parts)[:190], "links": uniq[:3]}


def _split(s: str) -> list[str]:
    return [x for x in re.findall(r"[^。！？；]+[。！？；]?", s) if x.strip()]


def _clean_reply(s: str) -> str:
    """Keep only sentences that pass the board filter (it is strict, e.g. bans some shopping words)."""
    return "".join(x for x in _split(s) if _safe(x))


def _safe(s: str) -> bool:
    try:
        from board.filter import check_post
        return bool(check_post(s, "").ok)
    except Exception:
        return False


def brain_reply(text: str, nick: str, seed: str) -> dict | None:
    out = None
    hook = os.environ.get("BOARD_REPLY_HOOK", "").strip()
    if hook and ":" in hook:
        try:
            mod, fn = hook.split(":", 1)
            out = getattr(importlib.import_module(mod), fn)(text, nick, seed)
        except Exception:
            out = None
    if out and _safe(out.get("heard", "")):
        out["reply"] = _clean_reply(str(out.get("reply", "")))[:190]
    if not (out and _safe(out.get("heard", "")) and out.get("reply")):
        out = compose(text, nick, seed)
        out["reply"] = _clean_reply(out["reply"])
    if not (_safe(out["heard"]) and len(out["reply"]) >= 8):
        out = {"heard": "你在星空里留下了一句话。", "reply": "你的信号我收下了，已经挂在星空里。有想找的免费资源或工具，随时再来跟我说。", "links": []}
    out["got"] = "地球人，我收到你的信息了。"
    return out
