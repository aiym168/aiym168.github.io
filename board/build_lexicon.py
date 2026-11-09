"""Dev-time: compile konsheng/*.txt into lexicon/base.txt, pruning entries that are
ordinary Chinese words (jieba freq) or that occur in benign corpora (cross-word false positives).
Usage: git clone https://github.com/konsheng/Sensitive-lexicon /tmp/lex &&
       cp /tmp/lex/Vocabulary/*.txt board/lexicon/konsheng/ (minus 非法网址.txt) &&
       python -m board.build_lexicon [benign_corpus.txt ...]   (needs jieba, pypinyin)
The raw konsheng files are not committed (only LICENSE/SOURCE + compiled base.txt.gz)."""
import os, sys
from pathlib import Path
import jieba
from board.filter import compact, CJK, _read_words, LEX

def main(corpora):
    freq = {}
    for l in open(os.path.join(os.path.dirname(jieba.__file__), "dict.txt"), encoding="utf-8"):
        p = l.split()
        if len(p) >= 2:
            freq[compact(p[0])] = max(freq.get(compact(p[0]), 0), int(p[1]))
    benign = "\n".join(compact(Path(c).read_text(encoding="utf-8", errors="ignore")) for c in corpora)
    custom = {compact(w) for w in _read_words(LEX / "custom_block.txt")}
    allow = {compact(w) for w in _read_words(LEX / "allow_words.txt")}
    from pypinyin import pinyin_dict
    syls = set()
    for v in pinyin_dict.pinyin_dict.values():
        for r in v.split(","):
            import unicodedata as ud
            syls.add("".join(c for c in ud.normalize("NFKD", r) if not ud.combining(c)).replace("ü", "v"))
    def is_pinyin(w):
        ok = [True] + [False] * len(w)
        for i in range(len(w)):
            if ok[i]:
                for j in range(i + 1, min(len(w), i + 6) + 1):
                    if w[i:j] in syls:
                        ok[j] = True
        return ok[-1]
    keep, dropped = set(), []
    for f in sorted((LEX / "konsheng").glob("*.txt")):
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            w = compact(line)
            if not w:
                continue
            n = len(CJK.findall(w))
            if w in allow:
                dropped.append((w, "allow")); continue
            if n == 0:
                if len(w) < 5 or w.isdigit() or not is_pinyin(w):
                    dropped.append((w, "latin")); continue
            elif len(w) < 2:
                continue
            if w in custom:
                keep.add(w); continue
            if n and len(w) <= 4 and freq.get(w, 0) >= 200:
                dropped.append((w, "freq")); continue
            if len(w) <= 3 and w in benign:
                dropped.append((w, "corpus")); continue
            keep.add(w)
    import gzip
    data = ("# compiled from konsheng/Sensitive-lexicon (MIT) by board/build_lexicon.py\n" + "\n".join(sorted(keep)) + "\n").encode("utf-8")
    (LEX / "base.txt.gz").write_bytes(gzip.compress(data, mtime=0))
    (Path("/tmp") / "board_pruned.txt").write_text("\n".join(f"{w}\t{why}" for w, why in sorted(set(dropped))) + "\n", encoding="utf-8")
    print("kept", len(keep), "dropped", len(set(dropped)))

if __name__ == "__main__":
    main(sys.argv[1:])
