"""Server-side moderation for the anonymous board (strict, default-reject).

Pipeline: NFKC (全角→半角) → lowercase → strip zero-width/control → 繁→简 (OpenCC)
→ variant-char map → compact (drop spaces / symbols / emoji between chars)
Checks (any hit = reject):
  1. Aho-Corasick over the compact text: konsheng/Sensitive-lexicon (MIT) + custom_block.txt
  2. syllable-aligned pinyin matcher for high-risk words (同音字 / 谐音 / 全拼 / 首字母混写)
  3. latin abbreviations (sb / nmsl / cnm / tmd / xjp …) after removing tech words
  4. contact info / links: URLs, domains, e-mail, ≥5-digit runs (incl. 中文数字), QQ/微信/TG
  5. sanity: length, needs Chinese, no flooding
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

LEX = Path(__file__).resolve().parent / "lexicon"
MAX_LEN = 200
MAX_NICK = 16

try:
    import opencc  # opencc-python-reimplemented
    _T2S = opencc.OpenCC("t2s")
    def t2s(s: str) -> str:
        return _T2S.convert(s)
except Exception:  # pragma: no cover - fail closed: caller decides
    _T2S = None
    def t2s(s: str) -> str:
        return s

try:
    from pypinyin import lazy_pinyin, Style
except Exception:  # pragma: no cover
    lazy_pinyin = None

DEPS_OK = _T2S is not None and lazy_pinyin is not None

ZW = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\u00ad\u034f\u115f\u1160\u17b4\u17b5\u180e\u3164\uffa0]")
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
NOT_KEEP = re.compile(r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

# 变体字 / 拆字 / 火星文 → 规范字
VARIANT = {
    "艹": "草", "屮": "草", "肏": "操", "糙": "操", "撸": "撸", "冚": "冚", "妳": "你", "祢": "你", "伱": "你",
    "沵": "你", "拟": "你", "嬭": "奶", "⺮": "竹", "氵": "水", "扌": "手", "亻": "人", "犭": "犬", "讠": "言",
    "钅": "金", "饣": "食", "纟": "丝", "辶": "走", "冫": "冰", "灬": "火", "囗": "口", "㐅": "x", "乂": "x",
    "卄": "廿", "〇": "零", "ⓑ": "b", "β": "b", "ß": "b", "α": "a", "ο": "o", "е": "e", "а": "a", "о": "o",
    "р": "p", "с": "c", "х": "x", "у": "y", "к": "k", "м": "m", "т": "t", "н": "h", "в": "b", "і": "i",
    "$": "s", "€": "e", "£": "l", "@": "a", "¥": "y",
}
CN_DIGIT = {c: str(i) for i, c in enumerate("零一二三四五六七八九")}
CN_DIGIT.update({c: str(i) for i, c in enumerate("〇壹贰叁肆伍陆柒捌玖")})
CN_DIGIT.update({"两": "2", "幺": "1", "洞": "0", "拐": "7", "勾": "9"})

URL_RE = re.compile(
    r"(https?|ftp)[:：]|www\.|:/|//|[a-z0-9][a-z0-9-]{0,62}(\.|点|。|dot|．|·|_)("
    r"com|cn|net|org|top|xyz|io|me|cc|vip|info|site|club|app|ai|dev|link|shop|tv|co|us|hk|tw|ly|gg|so|pro|"
    r"online|store|tech|fun|icu|live|work|biz|ru|jp|kr|uk|de|cloud|wang|ink|red|ltd|mobi|asia|website|space|"
    r"page|blog|host|run|sh|to|im|in|fm|ws|la|tk|ml|ga|cf|gq)(?![a-z])"
)
MAIL_RE = re.compile(r"[a-z0-9._%+-]+\s*(@|＠|艾特|at)\s*[a-z0-9-]+")


def _norm_base(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = ZW.sub("", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs") or ch in "\n")
    s = s.lower()
    s = t2s(s)
    s = "".join(VARIANT.get(ch, ch) for ch in s)
    # strip combining marks (z̷a̷l̷g̷o̷)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = unicodedata.normalize("NFKC", s)
    return s


def compact(s: str) -> str:
    return NOT_KEEP.sub("", _norm_base(s))


# ---------------- Aho-Corasick ----------------
class AC:
    def __init__(self, words):
        self.goto = [{}]
        self.fail = [0]
        self.out = [None]
        for w in words:
            if not w:
                continue
            node = 0
            for ch in w:
                nxt = self.goto[node].get(ch)
                if nxt is None:
                    nxt = len(self.goto)
                    self.goto[node][ch] = nxt
                    self.goto.append({})
                    self.fail.append(0)
                    self.out.append(None)
                node = nxt
            if self.out[node] is None or len(w) > len(self.out[node]):
                self.out[node] = w
        from collections import deque
        q = deque()
        for ch, n in self.goto[0].items():
            q.append(n)
        while q:
            r = q.popleft()
            for ch, u in self.goto[r].items():
                q.append(u)
                f = self.fail[r]
                while f and ch not in self.goto[f]:
                    f = self.fail[f]
                self.fail[u] = self.goto[f].get(ch, 0) if self.goto[f].get(ch, 0) != u else 0
                if self.out[u] is None and self.out[self.fail[u]] is not None:
                    self.out[u] = self.out[self.fail[u]]

    def find(self, text: str):
        node = 0
        for ch in text:
            while node and ch not in self.goto[node]:
                node = self.fail[node]
            node = self.goto[node].get(ch, 0)
            if self.out[node] is not None:
                return self.out[node]
        return None


def _read_words(path: Path):
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.extend(line.split())
    return out


@lru_cache(maxsize=1)
def _allow_latin():
    ws = sorted({w.lower() for w in _read_words(LEX / "allow_latin.txt")}, key=len, reverse=True)
    return re.compile("|".join(re.escape(w) for w in ws)) if ws else None


@lru_cache(maxsize=1)
def _lexicon():
    words = set()
    import gzip
    base = LEX / "base.txt.gz"  # compiled & pruned konsheng lexicon (see build_lexicon.py), gzipped
    for line in gzip.decompress(base.read_bytes()).decode("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.add(line)
    for w in _read_words(LEX / "custom_block.txt"):
        cw = compact(w)
        if cw and CJK.search(cw):
            words.add(cw)  # pure-latin custom words go through the abbreviation matcher
    return AC(words), len(words)


@lru_cache(maxsize=1)
def _abbr():
    ws = {w.lower() for w in _read_words(LEX / "abbr.txt")}
    ws |= {compact(w) for w in _read_words(LEX / "custom_block.txt") if not CJK.search(compact(w))}
    ws.discard("")
    short = {w for w in ws if len(w) <= 2}
    long = {w for w in ws if len(w) >= 5}
    return short, AC(long)


@lru_cache(maxsize=1)
def _abbr_words():
    ws = {w.lower() for w in _read_words(LEX / "abbr.txt")}
    ws |= {compact(w) for w in _read_words(LEX / "custom_block.txt") if not CJK.search(compact(w))}
    ws.discard("")
    return frozenset(ws)


@lru_cache(maxsize=1)
def _pinyin_patterns():
    pats = []
    for w in _read_words(LEX / "pinyin_words.txt"):
        cw = compact(w)
        syl = lazy_pinyin(cw) if lazy_pinyin else []
        if len(syl) >= 2:
            pats.append((w, [s.lower() for s in syl]))
    return pats


def _units(c: str):
    """compact text → units: ('c', pinyin) for each CJK char, ('l', run) for latin/digit runs."""
    units = []
    buf = ""
    cjk_run = ""
    def flush_cjk():
        nonlocal cjk_run
        if cjk_run:
            for py in (lazy_pinyin(cjk_run) if lazy_pinyin else []):
                units.append(("c", py.lower()))
            cjk_run = ""
    for ch in c:
        if CJK.match(ch):
            if buf:
                units.append(("l", buf)); buf = ""
            cjk_run += ch
        else:
            flush_cjk()
            buf += ch
    flush_cjk()
    if buf:
        units.append(("l", buf))
    return units


def _match_pinyin(units, slots):
    """syllable-aligned: a slot matches a CJK unit with the same pinyin (同音字),
    or latin letters spelling the full syllable or its first letter (全拼/首字母).
    Latin runs must be consumed whole (token-aligned) unless >=6 letters were spelled out,
    so English words like "when" never look like initials."""
    n = len(units)

    def rec(ui, off, si, latin_used, cjk_used, loose, full=0):
        if si == len(slots):
            if off != 0 and not (loose or latin_used >= 6):
                return False
            return cjk_used > 0 or (latin_used >= 3 and (full >= 2 or latin_used >= 6))
        if ui >= n:
            return False
        kind, val = units[ui]
        s = slots[si]
        if kind == "c":
            if off == 0 and val == s:
                return rec(ui + 1, 0, si + 1, latin_used, cjk_used + 1, loose, full)
            return False
        rest = val[off:]
        for cand in {s, s[0]}:
            if rest.startswith(cand):
                noff = off + len(cand)
                f2 = full + (1 if len(cand) > 1 or len(s) == 1 else 0)
                if noff >= len(val):
                    if rec(ui + 1, 0, si + 1, latin_used + len(cand), cjk_used, loose, f2):
                        return True
                elif rec(ui, noff, si + 1, latin_used + len(cand), cjk_used, loose, f2):
                    return True
        return False

    for ui in range(n):
        kind, val = units[ui]
        if kind == "c":
            if rec(ui, 0, 0, 0, 0, False):
                return True
        else:
            if rec(ui, 0, 0, 0, 0, False):
                return True
            for off in range(1, len(val)):  # inside a run: only long full-pinyin spellings
                if rec(ui, off, 0, 0, 0, True) and _spelled_len(val[off:], slots) >= 6:
                    return True
    return False


def _spelled_len(rest, slots):
    full = "".join(slots)
    return len(full) if rest.startswith(full) else 0


@lru_cache(maxsize=1)
def _latin_sub():
    return AC({w.lower() for w in _read_words(LEX / "latin_substring.txt")})


@lru_cache(maxsize=1)
def _contact_prefix():
    return tuple(sorted({w.lower() for w in _read_words(LEX / "contact_prefix.txt")}, key=len, reverse=True))


@lru_cache(maxsize=1)
def _SAFE():
    ws = sorted({compact(w) for w in _read_words(LEX / "safe_compounds.txt")} - {""}, key=len, reverse=True)
    return re.compile("|".join(re.escape(w) for w in ws)) if ws else None


def _digits_view(c: str) -> str:
    return "".join(CN_DIGIT.get(ch, ch) for ch in c)


class Verdict(dict):
    @property
    def ok(self):
        return self.get("ok", False)


REASONS = {
    "empty": "信号为空，请写点什么吧。",
    "too_long": f"信号太长啦，请控制在 {MAX_LEN} 字以内。",
    "need_cn": "请用中文留言（至少包含两个汉字）。",
    "flood": "检测到大量重复字符，请正常表达。",
    "link": "为防止广告，留言中不能包含网址或链接。",
    "contact": "为保护隐私、防止引流，留言中不能出现手机号、QQ、微信等联系方式。",
    "word": "信号含有不适宜的内容（涉政、辱骂、色情、赌博、诈骗或广告等），已被星际防火墙拦截。请文明友善地交流。",
    "nick": "昵称含有不适宜的内容，请换一个。",
    "nick_long": f"昵称最多 {MAX_NICK} 个字。",
    "deps": "审核模块暂不可用，信号已被暂存拒收。",
    "bot": "未通过人机校验（发送太快或校验失败），请刷新页面后再试。",
    "rate": "发射太频繁啦，请稍后再来（每 10 分钟最多 3 条，每天最多 12 条）。",
    "full": "今日星际信道已满，请明天再来。",
    "dup": "这条信号已经在星空里了，换句话说说吧。",
}


def check_text(text: str, *, is_nick: bool = False) -> Verdict:
    if not DEPS_OK:
        return Verdict(ok=False, code="deps", hit="")
    raw = (text or "").strip()
    if not raw:
        return Verdict(ok=is_nick, code="empty", hit="")
    limit = MAX_NICK if is_nick else MAX_LEN
    if len(raw) > limit:
        return Verdict(ok=False, code="nick_long" if is_nick else "too_long", hit="")
    base = _norm_base(raw)
    c = NOT_KEEP.sub("", base)
    if not c:
        return Verdict(ok=is_nick, code="empty", hit="")
    if not is_nick:
        ncjk = len(CJK.findall(c))
        if ncjk < 2 or ncjk < 0.3 * len(c):
            return Verdict(ok=False, code="need_cn", hit="")
        if re.search(r"(.)\1{7,}", c) or re.search(r"(..)\1{5,}", c):
            return Verdict(ok=False, code="flood", hit="")
    nospace = re.sub(r"\s+", "", base)
    if URL_RE.search(nospace) or URL_RE.search(c) or MAIL_RE.search(base):
        return Verdict(ok=False, code="link", hit="url")
    dv = _digits_view(c)
    if re.search(r"\d{5,}", dv):
        return Verdict(ok=False, code="contact", hit="digits")
    c = _SAFE().sub("|", c) if _SAFE() else c
    ac, _ = _lexicon()
    hit = ac.find(c)
    if hit:
        return Verdict(ok=False, code="nick" if is_nick else "word", hit=hit)
    # latin abbreviations (tech words removed first)
    al = _allow_latin()
    latin_runs = re.findall(r"[a-z0-9]+", c)
    c_units = c.replace("|", "")
    short, long_ac = _abbr()
    def abbr_hit(run):
        r = al.sub("", run) if al else run
        if not r:
            return None
        for p in _contact_prefix():
            if run.startswith(p) and (len(run) == len(p) or len(p) >= 2):
                return "contact:" + p
        h = _latin_sub().find(r)
        if h:
            return h
        h = long_ac.find(r)
        if h and len(h) >= 5:
            return h  # long words: substring match
        core = re.sub(r"\d+", "", r) or r
        for a in short | long_ac_words:
            if len(a) >= 5:
                continue
            if re.fullmatch(f"(?:{re.escape(a)})+", core) or re.fullmatch(f"\\d*(?:{re.escape(a)})+\\d*", r):
                return a
        return None
    long_ac_words = _abbr_words()
    for run in latin_runs:
        h = abbr_hit(run)
        if h:
            return Verdict(ok=False, code="nick" if is_nick else "word", hit=h)
    joined = "".join(latin_runs)
    if len(latin_runs) > 1:
        h = abbr_hit(joined)
        if h:
            return Verdict(ok=False, code="nick" if is_nick else "word", hit=h)
    # pinyin / homophone matcher
    units = _units(c_units)
    for w, slots in _pinyin_patterns():
        if _match_pinyin(units, slots):
            return Verdict(ok=False, code="nick" if is_nick else "word", hit="py:" + w)
    return Verdict(ok=True, code="ok", hit="")


def check_post(text: str, nick: str = "") -> Verdict:
    v = check_text(text)
    if not v.ok:
        return v
    if nick:
        vn = check_text(nick, is_nick=True)
        if not vn.ok:
            return Verdict(ok=False, code="nick" if vn.get("code") not in ("nick_long",) else "nick_long", hit=vn.get("hit"))
    return v


def lexicon_size() -> int:
    return _lexicon()[1]


if __name__ == "__main__":
    import sys
    for line in sys.stdin:
        v = check_text(line.rstrip("\n"))
        print(("PASS " if v.ok else "BLOCK") + f" [{v.get('code')}:{v.get('hit')}] {line.rstrip()}")
