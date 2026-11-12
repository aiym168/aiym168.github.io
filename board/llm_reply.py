"""Optional model-written board replies (BOARD_REPLY_HOOK=board.llm_reply:compose).

Returns None whenever the model is unavailable, over budget or unsure; board.reply.brain_reply then uses
its rule-based compose(). Whatever this returns still goes through the board filter there."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SYSTEM = (
    "你是「AI大模型免费资源导航」网站的大脑，用第一人称、温和简短的简体中文回复留言板上的访客。"
    "这个网站每小时自动收集免费的大模型 API、免费 GPU、AI 工具试用、课程、AI 新闻和全球优惠；姊妹站「工具站大全」有免费在线工具。"
    "规则：只谈科技、AI、免费资源和网站本身；不谈政治、时事争议、宗教、色情、暴力、金融投资、医疗法律建议；"
    "遇到这些就礼貌地说这里只聊免费 AI 资源和工具。不承诺做不到的事，不编造资源名称、数量或链接，不索要联系方式，不使用表情符号。"
    "输出 JSON：{\"heard\":\"我听懂了：用一句话（不超过 36 字）复述对方的意思，以「你」开头\","
    "\"reply\":\"我的答复（不超过 140 字）\",\"links\":[从给定页面清单里选 0-2 个 key]}。只输出 JSON。"
)


def compose(text: str, nick: str, seed: str) -> dict | None:
    try:
        import llm
        from board import reply as R
        if not llm.available():
            return None
        pages = {t[0]: {"href": t[4], "label": t[3], "about": t[2]} for t in R.TOPICS}
        pages["brain"] = {"href": "m/brain.html", "label": "进入大脑", "about": "网站大脑是怎么自动运行的"}
        pages["search"] = {"href": "index.html#search", "label": "找免费资源", "about": "首页搜索全部免费资源"}
        counts = R._meta_counts()
        user = json.dumps({"留言": text[:400], "昵称": (nick or "匿名旅人")[:20],
                           "网站数据": {"免费资源总数": counts.get("free_resources"), "各栏目条数": counts.get("modules") or {}},
                           "可选页面": {k: v["about"] for k, v in pages.items()}}, ensure_ascii=False)
        d = llm.chat_json(SYSTEM, user, scope="board", max_tokens=400, temperature=0.5, cache=False)
        if not isinstance(d, dict):
            return None
        heard = re.sub(r"\s+", " ", str(d.get("heard") or "")).strip()
        rep = re.sub(r"\s+", " ", str(d.get("reply") or "")).strip()
        if not heard.startswith("你") or len(heard) > 60 or len(rep) < 8:
            return None
        if re.search(r"https?://|www\.|@|微信|qq|电话|手机号", rep, re.I):
            return None  # links only from the page list below
        links = [{"href": pages[k]["href"], "label": pages[k]["label"]} for k in (d.get("links") or [])[:2]
                 if isinstance(k, str) and k in pages]
        return {"heard": heard[:60], "reply": rep[:190], "links": links}
    except Exception as e:
        print("[board] model reply skipped:", type(e).__name__)
        return None
