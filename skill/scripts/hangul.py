"""한글 음차 지명 → 라틴 지명 매칭 키.

KOICA 사업명의 지명은 외국 지명을 한글로 음차한 것이다(`바디바스` ← Bardibas).
정방향 복원은 불가능하므로, 양쪽을 **같은 느슨한 키**로 눌러 비교한다.

  바디바스   → badibaseu → badibas   ┐
  Bardibas   → bardibas  → badibas   ┘ 일치

핵심 손실 정보(한글이 표기하지 못하는 것)를 양쪽에서 똑같이 지운다:
  · 유기음 h (ph/kh/th/bh/dh/gh)      · r/l 구분      · 겹자음
  · 한글이 끼워 넣는 매개모음 '으'    · 어말 모음 흔들림
"""
from __future__ import annotations

import re
import unicodedata

CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",
       "j", "jj", "ch", "k", "t", "p", "h"]
JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe",
        "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "p", "l", "l",
        "l", "l", "m", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]


def romanize(s: str) -> str:
    """한글 → 로마자(국어의 로마자 표기법 근사). 한글이 아닌 문자는 그대로 둔다."""
    out = []
    for ch in s:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            i = code - 0xAC00
            out.append(CHO[i // 588])
            out.append(JUNG[(i % 588) // 28])
            out.append(JONG[i % 28])
        else:
            out.append(ch)
    return "".join(out)


def loose_key(s: str) -> str:
    """한글·라틴 어느 쪽이든 같은 규칙으로 눌러 비교 키를 만든다."""
    if not s:
        return ""
    if re.search(r"[가-힣]", s):
        s = romanize(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z]", "", s)

    # ch 는 실제 소리이므로 c→k 치환 전에 보호한다
    s = s.replace("ch", "\x01")
    # 로망스어권 정자법 — 한글은 구분하지 못한다 (Liquica/리키사, Viqueque/비케케)
    s = s.replace("qu", "k").replace("q", "k")
    s = s.replace("c", "k").replace("x", "s").replace("v", "b")
    s = s.replace("\x01", "ch")
    # 유기음 표기 h 제거 (Bhaktapur/박타푸르, Phedikhola/페디콜라)
    s = re.sub(r"(?<=[pktbdg])h", "", s)
    # 한글이 끼워 넣는 매개모음
    s = s.replace("eu", "")
    # r/l 구분 없음
    s = s.replace("l", "r")
    # 겹자음·겹모음 축약
    s = re.sub(r"(.)\1+", r"\1", s)
    # 어말 모음은 음차마다 흔들린다 (Pokhara/포카라, Bardiya/버르디야)
    s = re.sub(r"[aeiou]+$", "", s)
    return s


def skeleton(s: str) -> str:
    """자음 골격. 한글의 모음 선택은 음차마다 흔들리므로 보조 비교축으로 쓴다."""
    k = loose_key(s)
    c = re.sub(r"[aeiou]", "", k)
    return re.sub(r"(.)\1+", r"\1", c) or k


def _ratio(ka: str, kb: str) -> float:
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    la, lb = len(ka), len(kb)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (ka[i - 1] != kb[j - 1]))
        prev = cur
    return 1.0 - prev[lb] / max(la, lb)


# 자음 골격이 이보다 짧으면 정보량이 부족해 서로 다른 지명이 붙는다
#   (바우카우 bk ↔ 비케케 bk — 둘 다 동티모르 지명이라 실제 위험)
SKELETON_MIN = 4


def similarity(a: str, b: str) -> float:
    """느슨한 키와 자음 골격 중 높은 쪽. 모음 표기가 흔들려도 잡아낸다."""
    full = _ratio(loose_key(a), loose_key(b))
    if full >= 1.0:
        return 1.0
    sa, sb = skeleton(a), skeleton(b)
    if min(len(sa), len(sb)) < SKELETON_MIN:
        return full
    # 골격 일치는 모음 정보를 버린 결과이므로 약간 할인한다
    return max(full, _ratio(sa, sb) * 0.95)
