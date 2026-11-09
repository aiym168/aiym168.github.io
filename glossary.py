#!/usr/bin/env python3
"""Translation glossary: protected AI/tech terms + fixes for common machine-translation errors.

Used by fetch_auto.free_translate (post-process every translation, including cache hits)
and by curate.py (final pass over every public title/summary).
"""
from __future__ import annotations

import re

# Terms that must stay in their original (English / brand) form.
PROTECTED_TERMS = [
    "LLM", "Claude", "Claude Code", "GPT", "ChatGPT", "Gemini", "DeepSeek", "Bixby", "Codex", "Cursor",
    "Copilot", "API", "SDK", "GPU", "CPU", "TPU", "Hugging Face", "HuggingChat", "Transformers", "Ollama",
    "OpenAI", "Anthropic", "Mistral", "Llama", "Qwen", "Kimi", "GLM", "MCP", "Agent", "Token", "Grok",
    "Sonnet", "Opus", "Haiku", "Hermes Agent", "OpenRouter", "Groq", "Cloudflare", "Workers AI", "Kaggle",
    "Colab", "NVIDIA", "NIM", "AMD", "Vercel", "Supabase", "GitHub", "Replit", "Perplexity", "Midjourney",
    "Stable Diffusion", "ComfyUI", "Antigravity", "Harness", "RAG", "CLI", "IDE",
]

# Ordered (regex, replacement). Longer / more specific patterns first.
FIXES: list[tuple[str, str]] = [
    (r"克劳德\s*代码", "Claude Code"),
    (r"Claude\s*代码", "Claude Code"),
    (r"克劳德", "Claude"),
    (r"法学硕士(?:学位)?", "LLM"),
    (r"大型语言模型\s*\(LLM\)", "大语言模型（LLM）"),
    (r"拜县", "Bixby"),
    (r"拥抱\s*脸|抱脸", "Hugging Face"),
    (r"拥抱聊天", "HuggingChat"),
    (r"爱马仕\s*(?:经纪人|代理人|代理|特工)", "Hermes Agent"),
    (r"爱马仕", "Hermes"),
    (r"双子座\s*(?:命令行界面|CLI)", "Gemini CLI"),
    (r"双子座", "Gemini"),
    (r"十四行诗", "Sonnet"),
    (r"俳句", "Haiku"),
    (r"作品\s*4", "Opus 4"),
    (r"变形金刚(?=\s*(?:库|模型|架构|v?\d))", "Transformers"),
    (r"副驾驶", "Copilot"),
    (r"光标\s*(?:IDE|编辑器|AI)", "Cursor"),
    (r"反重力", "Antigravity"),
    (r"(?:编码|编程)?线束", "Harness"),
    (r"深度求索", "DeepSeek"),
    (r"深度搜索\s*(?=V\d|R\d)", "DeepSeek "),
    (r"开放\s*AI(?![a-z])", "OpenAI"),
    (r"开放人工智能(?:公司)?", "OpenAI"),
    (r"人择(?:公司)?", "Anthropic"),
    (r"困惑度\s*(?:AI|Pro)", "Perplexity"),
    (r"格罗克", "Grok"),
    (r"英伟达", "NVIDIA"),
    (r"拥抱面", "Hugging Face"),
    (r"(?<![\u4e00-\u9fff])令牌|代币(?=\s*(?:额度|免费|/|每))", "Token"),
    (r"图形处理器", "GPU"),
    (r"型号选择", "模型选择"),
    (r"(?<=[的个种款])型号", "模型"),
    (r"免费代币", "免费 Token"),
    (r"应用程序编程接口", "API"),
    (r"软件开发工具包", "SDK"),
    (r"命令行界面", "CLI"),
    (r"模型上下文协议", "MCP"),
    (r"人工智能代理", "AI Agent"),
    (r"人工智能", "AI"),
]
_COMPILED = [(re.compile(p), r) for p, r in FIXES]

# Strings that indicate a translation is garbage and should be re-translated / not trusted.
BAD_MARKERS = ("法学硕士", "克劳德", "拜县", "抱脸", "爱马仕经纪人", "十四行诗", "MYMEMORY WARNING")


def fix(text: str | None) -> str:
    """Apply glossary fixes to translated text. Idempotent."""
    if not text:
        return text or ""
    out = str(text)
    for rx, rep in _COMPILED:
        out = rx.sub(rep, out)
    # spacing between CJK and latin brand tokens: "使用Claude免费" -> "使用 Claude 免费"
    out = re.sub(r"([\u4e00-\u9fff])([A-Za-z][A-Za-z0-9.+\-]*)", r"\1 \2", out)
    out = re.sub(r"([A-Za-z])([\u4e00-\u9fff])", r"\1 \2", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+([：，、。）！？；])", r"\1", out)
    out = re.sub(r"([（：，、。！？；])[ \t]+", r"\1", out)
    return out.strip()


def is_bad(text: str | None) -> bool:
    return bool(text) and any(m in text for m in BAD_MARKERS)


if __name__ == "__main__":
    import sys
    for line in sys.stdin:
        print(fix(line.rstrip("\n")))
