"""배치 계산 엔진 — 프로젝트맵의 모든 좌표를 여기서 정한다.

    python layout.py --input projects.json --out layout.json [--lang ko] [--index 1]

렌더러(render_html/render_pptx)는 layout.json 만 소비한다. 배치 규칙을 렌더러에
복제하지 말 것 — 두 출력이 갈라진다.

계산 순서
    1. 국가 종횡비로 레이아웃 A(지도 중앙·카드 좌측+하단) / B(지도 좌측·카드 우측) 선택
    2. 정거원통도법으로 국토 bbox 를 지도 프레임에 맞춤
    3. 사업명 길이 → 줄 수 → 카드 높이
    4. 슬롯 생성 후 **각도 정렬**로 배정 → **2-opt** 로 지시선 교차 제거
    5. 넘치면 폰트 축소 → 지도 축소 → 경고 (design.md 판단 규칙 4)

입력 projects.json
    {"country": "네팔", "region": "아시아태평양",
     "projects": [{"place": "카트만두/부트왈", "name_ko": "...(2022-2028/800만불)",
                   "name_en": "...", "badges": ["G"], "kind": "point"}]}
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from pathlib import Path

from common import GEO_CACHE, design_tokens, log, read_json, write_json
import geo_prepare
import resolve_places

MIN_FONT_SCALE = 0.85     # design.md 규칙 4 — 폰트는 15% 까지만 줄인다

# 다중 대상지 사업 주석 (샘플 slide1/slide2 표기 그대로)
NOTE_MULTI = {"ko": "* 원형 표시 지역", "en": "* Areas marked circles"}

# 한 사업의 대상지가 이만큼 이상이면 지시선을 하나로 특정할 수 없다 → 원으로만 표시하고
# 카드에 주석을 단다. 원본 샘플의 `바라/팔사/반케/버르디야` 가 이 경우다.
MULTI_SITE_MIN = 2

# 범례가 위로 올라갈 수 있는 한계 — 지역 탭(y 0.58~1.45)과 x 가 겹치므로 그 아래여야 한다
LEGEND_MIN_Y = 1.60

# KOICA 지역 구분의 영문 표기. 원본 slide2 는 `Asia and Pacific` 으로 시작한다.
# 입력에 `region_en` 이 있으면 그 값이 우선한다.
REGION_EN = {
    "아시아태평양": "Asia and Pacific",
    "아프리카": "Africa",
    "중남미": "Latin America and the Caribbean",
    "중동·CIS": "Middle East and CIS",
    "중동": "Middle East",
    "동구·CIS": "Eastern Europe and CIS",
}


# ─────────────────────────────── 투영 ───────────────────────────────

TILE_PX_PER_IN = 130       # 표준 지도: 인치당 CSS 픽셀
CITY_TILE_PX_PER_IN = 650  # 도시 상세: z12 생활도로를 받기 위한 5배 타일 밀도
MAP_DENSITIES = {"standard", "city"}
THIN_LINE_ZOOM = 8.5       # 전국 범위: 표식을 가리지 않도록 선을 가늘게
FULL_LINE_ZOOM = 11.5      # 도시 범위: 과테말라시티 참조본의 굵기를 그대로 유지


def choose_map_density(doc: dict) -> str:
    """지도 범위에 맞는 실제 타일 밀도를 고른다.

    국가 전체와 도시·시도급 확대 지도 모두 과테말라시티 참조본과 같은 5배 타일
    밀도를 기본으로 쓴다. 경량 지도가 꼭 필요할 때만 입력에서 `standard`로 낮춘다.
    """
    requested = str(doc.get("map_density", "city")).strip().lower()
    if requested not in MAP_DENSITIES:
        raise ValueError("map_density는 'standard' 또는 'city'여야 합니다")
    return requested


def tile_line_scale(proj: "Projection") -> float:
    """상세도는 유지하되 축척이 넓을수록 배경 선만 가늘게 한다.

    5배 캔버스를 그대로 축소하면 도시 지도에서는 적정한 선 굵기가 전국 지도에서
    도로망 덩어리로 보인다. z8.5 이하에서는 보정 굵기의 40%, z11.5 이상에서는
    100%를 쓰고 그 사이는 선형 보간한다. 타일 zoom과 피처 수는 건드리지 않는다.
    """
    density_scale = max(1.0, proj.px_per_in / TILE_PX_PER_IN)
    if density_scale <= 1.0:
        return 1.0
    zoom = proj.view["zoom"]
    t = min(1.0, max(0.0, (zoom - THIN_LINE_ZOOM)
                         / (FULL_LINE_ZOOM - THIN_LINE_ZOOM)))
    return round(density_scale * (0.40 + 0.60 * t), 3)


class Projection:
    """Web Mercator. MapLibre 와 **같은 수식**이어야 타일 배경 위에서 핀이 맞는다.

    배경 이미지는 지도 프레임 전체를 채우고 국가가 그 안에 놓인다. 화면 밖 주변국은
    마스크로 눌러 대상국만 밝게 남긴다(원본 샘플의 표현).
    """

    def __init__(self, bbox: list, frame: dict, pad_ratio: float = 0.04,
                 px_per_in: int = TILE_PX_PER_IN):
        import basemap_tiles as bt
        self.frame = dict(frame)
        self.bbox = list(bbox)
        self.px_per_in = px_per_in
        self.w_px = max(int(round(frame["w"] * self.px_per_in)), 64)
        self.h_px = max(int(round(frame["h"] * self.px_per_in)), 64)
        self.view = bt.fit_view(bbox, self.w_px, self.h_px, pad_ratio)
        self.world = bt.TILE_SIZE * (2 ** self.view["zoom"])
        self.cx = bt.merc_x(self.view["center"][0])
        self.cy = bt.merc_y(self.view["center"][1])
        self._mx, self._my = bt.merc_x, bt.merc_y
        # 배경이 프레임을 꽉 채우므로 그림 영역 = 프레임
        self.content = dict(frame)

    def __call__(self, lon: float, lat: float) -> list:
        px = (self._mx(lon) - self.cx) * self.world + self.w_px / 2
        py = (self._my(lat) - self.cy) * self.world + self.h_px / 2
        return [round(self.frame["x"] + px / self.px_per_in, 4),
                round(self.frame["y"] + py / self.px_per_in, 4)]

    def rings(self, rings: list) -> list:
        return [[self(p[0], p[1]) for p in r] for r in rings]

    def as_dict(self) -> dict:
        return {"kind": "mercator", "zoom": self.view["zoom"],
                "center": self.view["center"],
                "w_px": self.w_px, "h_px": self.h_px, "px_per_in": self.px_per_in}


def country_aspect(bbox: list) -> float:
    lon0, lat0, lon1, lat1 = bbox
    cos = math.cos(math.radians((lat0 + lat1) / 2))
    return ((lon1 - lon0) * cos) / max(lat1 - lat0, 1e-6)


def _is_nationwide(parts: list) -> bool:
    """빈 해석 결과는 전국사업이 아니다 (`all([])`의 참값을 그대로 쓰지 않는다)."""
    return bool(parts) and all(part.get("kind") == "nationwide" for part in parts)


def choose_mode(doc: dict, tok: dict, lang: str,
                resolved: dict | None = None) -> str:
    """레이아웃 A / B 선택 — **카드가 한 열에 들어가는가**로 갈린다.

    국가 종횡비가 아니다. 샘플에서 네팔(bbox 1.77)은 A, 동티모르(2.35)는 B인데
    동티모르 쪽이 오히려 더 넓다. 실제 차이는 사업 수였다(10건 vs 7건).
    """
    col = tok["layout"]["B"]["right_col"]
    gap = tok["card"]["gap"]
    cards = []
    if resolved:
        country_en = doc.get("country_en", "")
        for rec, rp in zip(doc["projects"], resolved["places"]):
            card = build_card(
                rec, tok, lang, 1.0,
                place=_place_label(rec, rp, lang, country_en),
            )
            valid = [part for part in rp["parts"]
                     if part.get("ok") and part.get("kind") != "nationwide"]
            marker_kind = "multi" if len(valid) >= MULTI_SITE_MIN else "point"
            card["points"] = [
                {"lon": part["lon"], "lat": part["lat"],
                 "marker_kind": marker_kind}
                for part in valid
            ]
            card["nationwide"] = _is_nationwide(rp["parts"])
            cards.append(card)
    else:
        # 좌표를 모르면 같은 표시명이 실제 같은 장소인지 판단할 수 없다. 임의로
        # 합쳐 높이를 과소계산하지 않고 각 사업을 보수적으로 별도 그룹으로 둔다.
        for i, rec in enumerate(doc["projects"]):
            card = build_card(rec, tok, lang, 1.0)
            card.update({
                "points": [{"x": i, "y": 0, "marker_kind": "point"}],
                "nationwide": False,
            })
            cards.append(card)
    # 같은 지명·같은 좌표의 사업은 한 장소 블록으로 쌓인다. 반복 헤딩이 빠지는
    # 만큼 실제 높이가 줄어드는데, 여기서도 최종 배치와 같은 그룹 키를 써야 한다.
    groups = _group_cards(cards, tok)
    need = sum(g["h"] for g in groups) + gap * max(len(groups) - 1, 0)
    return "B" if need <= (col["y1"] - col["y0"]) else "A"


# ─────────────────────────────── 카드 ───────────────────────────────

def text_width(s: str, size_pt: float) -> float:
    """인치 단위 근사 폭. 한글·전각은 1.0, 라틴·숫자는 0.5 로 센다."""
    em = size_pt / 72.0
    w = 0.0
    for ch in s:
        o = ord(ch)
        w += 1.0 if (0xAC00 <= o <= 0xD7A3 or 0x3000 <= o <= 0x30FF
                     or 0x4E00 <= o <= 0x9FFF or 0xFF00 <= o <= 0xFF60) else 0.5
    return w * em


def wrap_text(s: str, width_in: float, size_pt: float, first_indent: float = 0.0) -> list:
    """폭에 맞춰 줄바꿈. 한글은 어디서나, 라틴은 단어 경계에서 끊는다.

    `first_indent` 는 첫 줄만 좁히는 폭(분야 배지 자리). 한 번에 처리해야 한다 —
    두 번 나눠 감고 `"".join(lines)` 로 다시 이으면 영문 단어 사이 공백이 사라진다.
    """
    lines, cur = [], ""
    for token in _tokens(s):
        avail = width_in - (first_indent if not lines else 0.0)
        trial = cur + token
        if cur and text_width(trial, size_pt) > avail:
            lines.append(cur.rstrip())
            cur = token.lstrip() if token.strip() else ""
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    # 마지막 줄에 닫는 괄호만 떨어지면 앞줄에 붙인다 ('…1,200만불' / ')' 방지).
    # `lines[-2] += lines.pop()` 는 인덱스를 pop 뒤에 계산해 터진다 — 먼저 꺼낸다.
    while len(lines) > 1 and lines[-1].strip() and \
            all(c in ")]』」’\"'.," for c in lines[-1].strip()):
        tail = lines.pop().strip()
        lines[-1] += tail
    return lines or [""]


def _tokens(s: str):
    """한글/기호는 1글자, 라틴 낱말은 통째로 (공백 포함) 내보낸다."""
    buf = ""
    for ch in s:
        o = ord(ch)
        latin = (0x41 <= o <= 0x5A) or (0x61 <= o <= 0x7A) or (0x30 <= o <= 0x39)
        if latin or ch in ".,'-/$":
            buf += ch
        else:
            if buf:
                yield buf
                buf = ""
            yield ch
    if buf:
        yield buf


def build_card(proj_rec: dict, tok: dict, lang: str, scale: float,
               place: str | None = None) -> dict:
    c = tok["card"]
    size = c["name"]["size"] * scale
    name = proj_rec.get(f"name_{lang}") or proj_rec.get("name_ko") or ""
    badges = proj_rec.get("badges") or []
    # 배지가 붙는 첫 줄만 배지 폭만큼 좁다
    indent = len(badges) * (c["badge"]["w"] + c["badge"]["gap"])
    lines = wrap_text(name, c["name"]["w"], size, first_indent=indent)
    lh = c["name"]["line_h"] * scale
    place = place if place is not None else proj_rec.get("place", "")
    place_font = _fit_font(place, c["place"]["size"] * scale, c["name"]["w"])
    return {
        "place": place,
        "place_font": round(place_font, 2),
        "badges": badges,
        "text": name,
        "lines": lines,
        "w": c["name"]["w"] + c["name"]["dx"],
        "h": c["name"]["dy"] + len(lines) * lh,
        "body_dy": c["name"]["dy"],
        "line_h": round(lh, 4),
        "font": round(size, 2),
        "place_w": round(text_width(place, place_font), 4),
    }


def _fit_font(text: str, preferred: float, max_width: float) -> float:
    width = text_width(text, preferred)
    if width <= max_width or width <= 0:
        return preferred
    return round(preferred * max_width / width, 2)


def _title_layout(country_ko: str, country_en: str, lang: str, tok: dict) -> dict:
    """두 렌더러가 공유하는 국가 제목 텍스트 배치.

    인간 작성본의 국문 제목은 `피지`와 `Fiji`를 별도 상자나 별도 줄에 둔 것이
    아니다. 한 텍스트 상자의 같은 문단에 크기가 다른 두 런을 연속해서 넣는다.
    LibreOffice는 이를 잘못 줄바꿈하지만 Microsoft PowerPoint에서는 한 줄이다.
    이 구조와 한글용 East Asian 글꼴 지정이 없으면 PowerPoint for Mac에서 국문
    글자가 달라진다.
    """
    title, text = tok["title"], tok["title"]["text"]
    box, pin = title["box"], title["pin"]
    if lang == "ko":
        # 피지(2글자)는 샘플 실측 폭을 그대로 쓴다. 더 긴 국명은 같은 중심을
        # 유지하며 글자 실측 폭만큼 넓히고, 박스 안쪽 한계를 넘을 때만 축소한다.
        natural_w = max(
            text["w_ko"],
            text_width(country_ko, text["size_ko"]) + 0.04155,
            text_width(country_en, text["size_en"]) + 0.10,
        )
        w = min(natural_w, box["w"] - 0.12)
        x = box["x"] + text["dx_ko"] if abs(w - text["w_ko"]) < 1e-6 \
            else box["x"] + box["w"] / 2 - w / 2
        main_size = text["size_ko"]
        en_size = text["size_en"]
        title_box = None
        # 텍스트 상자는 PowerPoint에서 실제 글자 폭만큼 오른쪽으로 자동 확장된다.
        # 짧은 `피지 Fiji`는 원본 좌표를 그대로 유지한다. 시·도/도시명처럼 긴
        # 조합은 글자를 작게 만들지 말고 상단 외곽선과 텍스트 상자를 넓힌다.
        combined = (text_width(f"{country_ko} ", main_size)
                    + text_width(country_en, en_size))
        left_min = pin["x"] + pin["w"] + 0.04
        available = box["x"] + box["w"] - max(x, left_min) - 0.04
        if combined > available:
            x = left_min
            # 근사 폭보다 10% 여유를 둬 PowerPoint의 실제 Malgun Gothic 폭과
            # 음수 자간을 적용한 뒤에도 한 줄을 보장한다.
            desired_right = x + combined * 1.10 + 0.08
            expanded_w = min(max(box["w"], desired_right - box["x"]), 4.20)
            title_box = {**box, "w": round(expanded_w, 5)}
            available = title_box["x"] + title_box["w"] - x - 0.04
            if combined > available:
                title_scale = available / combined
                main_size = round(main_size * title_scale, 2)
                en_size = round(en_size * title_scale, 2)
            w = available
        return {
            "mode": "inline_runs",
            "x": round(x, 5),
            "y": text["y_ko"],
            "w": round(w, 5),
            "h": text["h_ko"],
            "paragraph_margin": text["paragraph_margin"],
            "html_en_dy": text["html_en_dy"],
            **({"box": title_box} if title_box else {}),
            "runs": [
                {
                    "text": f"{country_ko} ",
                    "size": main_size,
                    "spacing": text["spacing"],
                    "baseline": text["baseline_ko"],
                    "complex_font": "Batang",
                },
                {
                    "text": country_en,
                    "size": en_size,
                    "spacing": text["spacing"],
                    "complex_font": "Arial Narrow",
                },
            ],
        }
    else:
        natural_w = max(text["w_en"], text_width(country_en, text["size_en_only"]) * 0.81)
        w = min(natural_w, box["w"] - 0.18)
        # 샘플의 0.008in 좌측 보정은 문단 왼쪽 여백과 함께 시각 중심을 맞춘다.
        x = box["x"] + text["dx_en"] if abs(w - text["w_en"]) < 1e-6 \
            else box["x"] + box["w"] / 2 - w / 2 - 0.00808
        if natural_w > text["w_en"]:
            # 긴 영문명은 자연폭 딱 맞춤 상자에서 PowerPoint가 마지막 단어를
            # 줄바꿈할 수 있으므로 외곽선 안 남은 폭을 모두 텍스트 상자에 준다.
            w = box["x"] + box["w"] - x - 0.04
        return {
            "mode": "single_run",
            "x": round(x, 5),
            "y": text["y_en"],
            "w": round(w, 5),
            "h": text["h_en"],
            "paragraph_margin": text["paragraph_margin"],
            "runs": [{
                "text": country_en,
                # text_width()는 실제 Malgun Gothic 라틴 글리프보다 약 19% 넓게
                # 추정하므로 샘플의 14.11pt가 불필요하게 축소되지 않게 보정한다.
                "size": _fit_font(country_en, text["size_en_only"], w / 0.81),
                "spacing": text["spacing"],
                "complex_font": "Arial Narrow",
            }],
        }


def _place_group_key(card: dict) -> tuple:
    """같은 지명·같은 좌표의 사업을 한 장소 그룹으로 묶는 안정 키.

    표시명이 같아도 해석 좌표가 다르면 합치지 않는다. 반대로 같은 지점의 사업은
    입력에서 떨어져 있어도 한 블록이 된다. 전국사업은 좌표가 없으므로 표시명으로
    묶는다.
    """
    place = " ".join(str(card.get("place", "")).split()).casefold()
    coords = tuple(sorted(
        (round(float(p.get("lon", p.get("x", 0))), 5),
         round(float(p.get("lat", p.get("y", 0))), 5),
         p.get("marker_kind", "point"))
        for p in card.get("points", [])
    ))
    return place, coords, bool(card.get("nationwide"))


def _dedupe_points(points: list) -> list:
    seen, out = set(), []
    for p in points:
        key = (round(float(p.get("x", 0)), 4), round(float(p.get("y", 0)), 4),
               p.get("marker_kind", "point"))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _group_cards(cards: list, tok: dict) -> list:
    """프로젝트 카드를 장소 블록으로 묶는다.

    인간 작성본은 같은 장소명을 한 번만 쓰고 그 아래에 여러 사업을 이어 붙인다.
    장소 블록은 슬롯·정렬·지시선의 단위이고, 개별 사업 카드는 편집성을 위해 최종
    layout.json 에 다시 납작하게 저장한다.
    """
    by_key, groups = {}, []
    for card in cards:
        key = _place_group_key(card)
        group = by_key.get(key)
        if group is None:
            group = {
                "group_key": "|".join((key[0], repr(key[1]), str(key[2]))),
                "place": card["place"],
                "place_w": card["place_w"],
                "points": [],
                "nationwide": bool(card.get("nationwide")),
                "no_leader": False,
                "items": [],
                "w": card["w"],
            }
            by_key[key] = group
            groups.append(group)
        group["items"].append(card)
        group["points"].extend(card.get("points", []))
        group["no_leader"] = group["no_leader"] or bool(card.get("no_leader"))
        group["w"] = max(group["w"], card["w"])

    name_dy = tok["card"]["name"]["dy"]
    gap = tok["card"]["gap"]
    for group in groups:
        group["points"] = _dedupe_points(group["points"])
        rows, height = [], 0.0
        for i, source in enumerate(group["items"]):
            row = dict(source)
            row["group_key"] = group["group_key"]
            row["show_place"] = i == 0
            # 첫 사업만 지명 헤딩 아래에 놓고, 뒤 사업은 헤딩 자리를 없애 바로 잇는다.
            row["body_dy"] = name_dy if i == 0 else 0.0
            row["h"] = round(source["h"] - name_dy + row["body_dy"], 4)
            rows.append(row)
            height += row["h"]
            if i < len(group["items"]) - 1:
                height += gap
        group["items"] = rows
        group["h"] = round(height, 4)
    return groups


def _flatten_groups(groups: list, gap: float) -> list:
    """배치된 장소 그룹을 렌더러용 개별 사업 카드로 되돌린다."""
    cards = []
    for group_index, group in enumerate(groups):
        y = group["y"]
        group["first_card"] = len(cards)
        for item in group["items"]:
            card = dict(item)
            card.update({
                "x": group["x"], "y": round(y, 4), "side": group["side"],
                "group_index": group_index,
            })
            cards.append(card)
            y += card["h"] + gap
    return cards


# ─────────────────────────────── 슬롯 ───────────────────────────────

def stack_slots(cards: list, x: float, y0: float, gap: float) -> list:
    """세로 열 — 카드 실제 높이만큼 쌓는다."""
    out, y = [], y0
    for c in cards:
        out.append({"x": x, "y": round(y, 4)})
        y += c["h"] + gap
    return out


def row_slots(n: int, y: float, x0: float, x1: float, pitch: float) -> list:
    if n <= 0:
        return []
    span = x1 - x0
    step = min(pitch, span / n) if n > 1 else 0
    if n > 1:
        step = max(step, (span - pitch) / (n - 1)) if span > pitch else step
        step = min(step, span / (n - 1)) if n > 1 else step
    return [{"x": round(x0 + i * step, 4), "y": y} for i in range(n)]


def column_capacity(y0: float, y1: float, card_h: float, gap: float) -> int:
    return max(1, int((y1 - y0 + gap) // (card_h + gap)))


# ─────────────────────────────── 각도 배정 · 교차 제거 ───────────────────────────────

def anchor_of(slot: dict, card: dict, side: str) -> list:
    """지시선이 카드에서 출발하는 점 — 지명 헤딩 끝."""
    if side == "right":                       # 레이아웃 B: 카드 왼쪽에서 나간다
        return [slot["x"], round(slot["y"] + 0.075, 4)]
    return [round(slot["x"] + card["place_w"] + 0.03, 4), round(slot["y"] + 0.075, 4)]


def segments_cross(p1, p2, p3, p4) -> bool:
    # 같은 핀으로 모이는 지시선은 끝점을 공유할 뿐 교차가 아니다.
    # (동티모르 바우카우처럼 한 지점에 사업 여러 건이 걸리는 경우가 흔하다)
    def same(a, b):
        return abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9
    if any(same(a, b) for a in (p1, p2) for b in (p3, p4)):
        return False

    def o(a, b, c):
        v = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else 2)
    o1, o2, o3, o4 = o(p1, p2, p3), o(p1, p2, p4), o(p3, p4, p1), o(p3, p4, p2)
    return o1 != o2 and o3 != o4


def _segments(leader: dict) -> list:
    p = leader.get("points") or [leader["from"], leader["to"]]
    return [(p[i], p[i + 1]) for i in range(len(p) - 1)]


def count_crossings(leaders: list) -> int:
    """꺾은선끼리 교차하는 지시선 쌍의 수. 한 쌍이 여러 번 만나도 1로 센다."""
    n = 0
    for i in range(len(leaders)):
        for j in range(i + 1, len(leaders)):
            if any(segments_cross(a1, a2, b1, b2)
                   for a1, a2 in _segments(leaders[i])
                   for b1, b2 in _segments(leaders[j])):
                n += 1
    return n


def _card_text_boxes(placed: list, tok: dict) -> list:
    """지시선이 지나선 안 되는 글자 영역 — (카드번호, 상자) 목록.

    카드번호를 함께 돌려주는 이유: 지시선은 **자기 카드**의 헤딩 모서리에서
    출발하므로 자기 상자와는 당연히 닿는다. 그건 위반이 아니다.
    """
    nm = tok["card"]["name"]
    boxes = []
    for i, c in enumerate(placed):
        if c.get("show_place", True):
            boxes.append((i, (c["x"] - 0.01, c["y"],
                              c["x"] + c["place_w"], c["y"] + 0.14)))
        x0 = c["x"] + nm["dx"]
        body_y = c["y"] + c.get("body_dy", nm["dy"])
        boxes.append((i, (x0, body_y - 0.02, x0 + nm["w"], c["y"] + c["h"])))
    return boxes


def _seg_hits_box(p, q, b) -> bool:
    def inside(pt):
        return b[0] < pt[0] < b[2] and b[1] < pt[1] < b[3]
    if inside(p) or inside(q):
        return True
    corners = [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]
    return any(segments_cross(p, q, e1, e2)
               for e1, e2 in zip(corners, corners[1:] + corners[:1]))


def count_text_hits(leaders: list, placed: list, tok: dict) -> int:
    """카드 글자를 가리는 지시선 수. 배치 불변식 — 0 이 아니면 규칙 위반이다.

    한 번 눈으로 잡았던 회귀(직선 지시선이 사업명을 관통)를 코드로 못 박는다.
    꺾은선 규칙이 지켜지면 수평 구간은 헤딩 줄 높이라 어떤 글자 상자와도
    만나지 않고, 대각 구간은 지도 영역 안에만 있다.
    """
    boxes = _card_text_boxes(placed, tok)
    return sum(1 for ld in leaders
               if any(_seg_hits_box(p, q, b)
                      for p, q in _segments(ld)
                      for i, b in boxes if i != ld.get("card")))


def check_bounds(placed: list, legend: dict, tok: dict) -> list:
    """배치된 요소가 슬라이드를 벗어나는지 본다 — 배치 불변식.

    영문 범례가 슬라이드 밖으로 흘러나간 적이 있다(렌더러마다 따로 계산해 갈라졌다).
    layout 이 좌표를 굳히는 이상, 이탈 여부도 여기서 판정할 수 있어야 한다.
    """
    W, H = tok["canvas"]["w_in"], tok["canvas"]["h_in"]
    out = []
    for c in placed:
        if c["y"] + c["h"] > H - 0.02:
            out.append(f'카드 「{c["place"][:14]}」 하단 {c["y"] + c["h"]:.2f}in')
        if c["x"] + c["w"] > W - 0.02:
            out.append(f'카드 「{c["place"][:14]}」 우측 {c["x"] + c["w"]:.2f}in')
    if legend.get("bottom", 0) > H - 0.02:
        out.append(f'범례 하단 {legend["bottom"]:.2f}in')
    return out


def assign_sides(pins: list, col_x: float, row_y: float, n_row: int) -> list:
    """어느 카드를 하단행으로 보낼지 고른다 — 열보다 행이 가까운 순.

    각도 정렬은 쓰지 않는다. 핀이 지도 중앙에 몰리면(네팔이 그렇다) 중심 기준
    각도가 불안정해져 배정이 뒤집힌다.
    """
    if n_row <= 0:
        return ["col"] * len(pins)
    gain = sorted(range(len(pins)),
                  key=lambda i: (abs(pins[i][0] - col_x) - abs(pins[i][1] - row_y)),
                  reverse=True)
    sides = ["col"] * len(pins)
    for i in gain[:n_row]:
        sides[i] = "row"
    return sides


def order_for(pins: list, axis: int) -> list:
    """세로 열은 y(axis=1), 가로 행은 x(axis=0) 순. 같은 쪽으로 나가는
    지시선끼리는 이 순서가 교차를 만들지 않는다."""
    return sorted(range(len(pins)), key=lambda i: pins[i][axis])


# ─────────────────────────────── 본체 ───────────────────────────────

def compute(doc: dict, lang: str = "ko", index: int = 1,
            detail: str = "50m", force_scale: float | None = None) -> dict:
    """force_scale 을 주면 그 배율로 고정한다 — 국문·영문 슬라이드를 짝으로 맞출 때 쓴다
    (design.md 판단 규칙 5)."""
    tok = design_tokens()
    country = doc["country"]
    resolved = resolve_places.resolve(country, doc["projects"], detail)
    iso3 = resolved["iso3"]
    bp = GEO_CACHE / f"{iso3}_basemap.json"
    base = read_json(bp) if bp.exists() else {}
    # 레이어가 추가된 뒤라면 옛 캐시를 그대로 쓰면 하천·주 이름 없이 밋밋하게 나온다
    if base.get("v", 0) < geo_prepare.BASEMAP_VERSION:
        log(f"  · 지도 캐시가 옛 형식({base.get('v', 0)}) — 다시 만듭니다")
        geo_prepare.build(country, detail, False)
        base = read_json(bp)

    mode = choose_mode(doc, tok, lang, resolved)
    L = tok["layout"][mode]
    map_bbox = doc.get("map_bbox") or base["bbox"]
    log(f'[{iso3}] {base["name_ko"]} 사업 {len(doc["projects"])}건 '
        f'· 종횡비 {country_aspect(map_bbox):.2f} → 레이아웃 {mode}')

    for attempt in range(3):
        scale = force_scale if force_scale else (1.0 if attempt == 0 else MIN_FONT_SCALE)
        shrink = 0.88 if attempt == 2 else 1.0     # 3차 시도에서 지도를 줄인다
        frame = dict(L["map"])
        if shrink < 1.0:
            frame["w"] *= shrink
            frame["h"] *= shrink
        res = _try_layout(doc, resolved, base, tok, L, mode, lang, index,
                          frame, scale)
        if res["fits"]:
            if attempt:
                log(f"  · 넘침 대응: 폰트 {scale:.2f}배" + (f", 지도 {shrink:.2f}배" if shrink < 1 else ""))
            return res
        last = res
    last["warnings"].append(
        "카드가 슬라이드를 넘칩니다. 사업 수를 줄이거나 슬라이드를 분할하세요.")
    return last


def _try_layout(doc, resolved, base, tok, L, mode, lang, index, frame, scale) -> dict:
    gap = tok["card"]["gap"]
    density = choose_map_density(doc)
    tile_ppi = CITY_TILE_PX_PER_IN if density == "city" else TILE_PX_PER_IN
    proj = Projection(doc.get("map_bbox") or base["bbox"], frame,
                      px_per_in=tile_ppi)

    # 1) 카드 생성 + 마커 좌표
    cards, markers, warnings = [], [], []
    country_en = doc.get("country_en") or base.get("name_en") or ""
    # 영문 슬라이드인데 영문 사업명이 없으면 한글이 그대로 실린다 — 조용히 넘기지 않는다
    if lang == "en":
        miss = sum(1 for p in doc["projects"] if not p.get("name_en"))
        if miss:
            warnings.append(f"영문 사업명(name_en) 누락 {miss}/{len(doc['projects'])}건 "
                            f"— 해당 카드는 한글 사업명으로 나옵니다")
    for rec, rp in zip(doc["projects"], resolved["places"]):
        card = build_card(rec, tok, lang, scale, place=_place_label(rec, rp, lang, country_en))
        pts = []
        valid_parts = [part for part in rp["parts"]
                       if part.get("ok") and part.get("kind") != "nationwide"]
        marker_kind = "multi" if len(valid_parts) >= MULTI_SITE_MIN else "point"
        for part in valid_parts:
            xy = proj(part["lon"], part["lat"])
            # 경위도도 남긴다 — 인치 좌표만 두면 이 지도가 확정한 위치를
            # 밖으로 내보낼 수 없다 (contribute.py 가 이 값을 쓴다)
            pts.append({"x": xy[0], "y": xy[1], "kind": part["kind"],
                        "marker_kind": marker_kind,
                        "name": part["matched"], "lon": part["lon"],
                        "lat": part["lat"], "level": part.get("level", ""),
                        "source": part.get("source", ""),
                        "coord_source": part.get("coord_source", "")})
        card["nationwide"] = _is_nationwide(rp["parts"])
        card["points"] = pts
        markers.extend(pts)
        cards.append(card)
        if not rp["resolved"]:
            warnings.append(f'지명 미해석: {rp["query"]}')

    _mark_multi_site_note(cards, lang)

    groups = _group_cards(cards, tok)

    # 2) 슬롯 배분 — 좌측열이 넘치면 하단행으로 흘린다
    avg_h = sum(g["h"] for g in groups) / max(len(groups), 1)
    if mode == "A":
        cap_left = column_capacity(L["left_col"]["y0"], L["left_col"]["y1"], avg_h, gap)
        pitch = tok["card"]["name"]["w"] + tok["card"]["name"]["dx"] + 0.22
        cap_bottom = max(1, int((L["bottom_row"]["x1"] - L["bottom_row"]["x0"]) // pitch))
        n_bottom = max(0, min(len(groups) - cap_left, cap_bottom))
        n_left = len(groups) - n_bottom
        sides = ["left"] * n_left + ["bottom"] * n_bottom
    else:
        cap_left = column_capacity(L["right_col"]["y0"], L["right_col"]["y1"], avg_h, gap)
        n_left, n_bottom = len(groups), 0
        sides = ["right"] * len(groups)

    # 3) 배정 — 핀이 열/행 중 가까운 쪽으로 가고, 같은 쪽 안에서는 좌표순으로 놓는다
    col_x = L["left_col"]["x"] if mode == "A" else L["right_col"]["x"]
    row_y = L["bottom_row"]["y"] if mode == "A" else tok["canvas"]["h_in"]
    idx_linked = [i for i, g in enumerate(groups) if g["points"]]
    idx_free = [i for i, g in enumerate(groups) if not g["points"]]
    pins = [_card_pin(groups[i]) for i in idx_linked]

    side_pick = assign_sides(pins, col_x, row_y, n_bottom)
    col_idx = [idx_linked[i] for i, s in enumerate(side_pick) if s == "col"] + idx_free
    row_idx = [idx_linked[i] for i, s in enumerate(side_pick) if s == "row"]
    col_pins = [_card_pin(groups[i]) for i in col_idx]
    row_pins = [_card_pin(groups[i]) for i in row_idx]
    # 전국사업(핀 없음)은 열 맨 아래로
    col_sorted = [col_idx[i] for i in order_for(col_pins, 1) if groups[col_idx[i]]["points"]] \
        + [i for i in col_idx if not groups[i]["points"]]
    row_sorted = [row_idx[i] for i in order_for(row_pins, 0)]

    assign = {}                                  # slot_index -> card_index
    for s, c in enumerate(col_sorted):
        assign[s] = c
    for j, c in enumerate(row_sorted):
        assign[n_left + j] = c
    sides = ["left" if mode == "A" else "right"] * len(col_sorted) \
        + ["bottom"] * len(row_sorted)
    n_left = len(col_sorted)

    placed_groups = _materialize(assign, groups, sides, mode, L, gap, tok, frame)
    _improve(placed_groups, mode)
    placed = _flatten_groups(placed_groups, gap)

    # 4) 지시선 · 결과 조립 — 같은 장소의 여러 사업은 헤딩과 지시선을 한 번만 쓴다.
    leaders = []
    for group in placed_groups:
        for ld in _leaders_of_card(group):
            ld["card"] = group["first_card"]
            leaders.append(ld)
    text_hits = count_text_hits(leaders, placed, tok)
    if text_hits:
        warnings.append(f"지시선이 카드 글자를 {text_hits}건 가립니다 — 배치 규칙 위반")
    legend = _legend(tok, lang)
    outside = check_bounds(placed, legend, tok)
    for o in outside:
        warnings.append(f"슬라이드 밖으로 나갑니다: {o}")
    fits = _fits(placed, mode, L, tok)
    country_info = {"ko": doc.get("country_ko") or base["name_ko"],
                    "en": doc.get("country_en") or base["name_en"],
                    "iso3": base["iso3"]}
    doc_out = {
        "canvas": {"w": tok["canvas"]["w_in"], "h": tok["canvas"]["h_in"]},
        "lang": lang, "mode": mode, "index": index,
        # 영문명은 입력에서 덮어쓸 수 있다 — Natural Earth 는 'East Timor' 지만
        # KOICA 표기는 'Timor-Leste' 다.
        "country": country_info,
        "title": _title_layout(country_info["ko"], country_info["en"], lang, tok),
        "region": (doc.get("region", "") if lang == "ko" else
                   (doc.get("region_en")
                    or REGION_EN.get(doc.get("region", ""), doc.get("region", "")))),
        "map": {"frame": frame, "content": proj.content,
                "density": density, "projection": proj.as_dict(),
                "tiles": _tile_background(base, proj, frame),
                "land": proj.rings(base["land"]),
                "neighbors": [{"name": n["name"], "rings": proj.rings(n["rings"])}
                              for n in base["neighbors"]],
                "admin1": proj.rings(base["admin1"]),
                "admin2": proj.rings(base.get("admin2", [])),
                "rivers": proj.rings(base.get("rivers", [])),
                "lakes": proj.rings(base.get("lakes", [])),
                "admin1_labels": [
                    {"name": a["name"], "area": a["area"],
                     **dict(zip(("x", "y"), proj(a["lon"], a["lat"])))}
                    for a in base.get("admin1_labels", [])],
                # 도시는 렌더러가 라벨 충돌을 보고 추리므로 넉넉히 넘긴다
                "cities": [{"name": c["name"], "pop": c.get("pop", 0),
                            **dict(zip(("x", "y"), proj(c["lon"], c["lat"])))}
                           for c in base.get("cities", [])]},
        "cards": placed,
        "place_group_count": len(placed_groups),
        "markers": _dedupe(markers),
        "leaders": leaders,
        "legend": legend,
        # 주석은 해당 카드 안에 들어간다(card["note"]). 슬라이드 각주로 두지 않는다.
        "notes": [],
        "crossings": count_crossings(leaders),
        "text_hits": text_hits,
        "font_scale": scale,
        "warnings": warnings,
        "fits": fits,
        "source": base.get("source", {}),
    }
    return doc_out


def strip_accents(s: str) -> str:
    """라틴 발음기호만 떼고 **한글은 그대로** 둔다.

    NFKD 는 한글 음절도 자모로 쪼갠다(`동티모르` → 9글자). 결합문자를 지운 뒤
    NFC 로 되돌리지 않으면 화면에 자모가 흩어져 찍힌다.
    """
    d = unicodedata.normalize("NFKD", s)
    return unicodedata.normalize("NFC", "".join(c for c in d
                                                if not unicodedata.combining(c)))


def _place_label(rec: dict, rp: dict, lang: str, country_en: str = "") -> str:
    """영문 슬라이드의 지명 헤딩은 해석된 라틴 표기를 쓴다 (포카라 → Pokhara).
    입력에 `place_en` 이 있으면 그 값이 우선한다."""
    if lang == "ko":
        return rec.get("place", "")
    if rec.get("place_en"):
        return rec["place_en"]
    parts = [p for p in rp["parts"] if p.get("ok") and p.get("matched")]
    # 전국사업은 해석 결과가 한글 국가명이다 — 영문 슬라이드에선 영문 국가명을 쓴다
    if parts and all(p.get("kind") == "nationwide" for p in parts) and country_en:
        return f"{country_en} nationwide"
    names = [p["matched"] for p in parts]
    if not names:
        return rec.get("place", "")
    # GeoNames 는 장음부호를 단다(Butwāl·Bardiyā). KOICA 표기는 붙이지 않는다.
    return strip_accents("/".join(names))


def _mark_multi_site_note(cards: list, lang: str) -> None:
    """`* 원형 표시 지역` 을 붙일 카드를 **하나만** 고른다.

    원본 샘플에서 이 주석은 슬라이드당 한 번, 사업대상지가 여러 곳이라 지시선을
    한 지점으로 특정할 수 없는 카드 안에 들어간다(네팔 `바라/팔사/반케/버르디야`,
    동티모르 `딜리/리키사/에르메라/바우카우 주`). 그 카드는 지시선을 긋지 않고
    지도의 초록 원으로만 위치를 알린다.

    슬라이드 각주로 두면 무관한 카드 위에 얹히고, 다중지역 카드마다 달면
    지시선이 거의 사라진다 — 둘 다 원본과 다르다.
    """
    cand = [c for c in cards if len(c["points"]) >= MULTI_SITE_MIN]
    if not cand:
        return
    pick = max(cand, key=lambda c: (len(c["points"]), -cards.index(c)))
    pick["note"] = NOTE_MULTI[lang]
    pick["no_leader"] = True
    pick["h"] += pick["line_h"]


def _tile_background(base: dict, proj: "Projection", frame: dict):
    """OSM 벡터 타일로 배경을 굽는다. 실패하면 None — 렌더러가 벡터로 되돌린다.

    도로·하천 밀도는 Natural Earth 로 낼 수 없어서 타일을 쓴다. 네트워크가 없거나
    Chrome 이 없으면 조용히 벡터 배경으로 떨어진다.
    """
    import basemap_tiles as bt
    capture_scale = 1 if proj.px_per_in >= CITY_TILE_PX_PER_IN else 2
    key = (f'{base["iso3"]}_s{bt.STYLE_VERSION}_dpr{capture_scale}'
           f'_z{proj.view["zoom"]:.3f}'
           f'_c{proj.view["center"][0]:.3f}_{proj.view["center"][1]:.3f}'
           f'_{proj.w_px}x{proj.h_px}.png')
    out = GEO_CACHE / "tiles" / key
    if out.exists() and out.stat().st_size > 20000:
        return {"png": str(out), "w_px": proj.w_px, "h_px": proj.h_px}
    try:
        import cdp
        tok = design_tokens()
        line_scale = tile_line_scale(proj)
        html, _ = bt.build_html(proj.bbox, proj.w_px, proj.h_px, tok,
                                line_scale=line_scale)
        hp = out.with_suffix(".html")
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(html, encoding="utf-8")
        cdp.shot(hp.resolve().as_uri(), out, proj.w_px, proj.h_px, capture_scale,
                 ready_js="document.title==='MAP_READY'", wait=90)
        if out.stat().st_size < 20000:
            raise RuntimeError("배경이 비었습니다")
        log(f"  · 타일 배경 {out.stat().st_size//1024}KB "
            f"(zoom {proj.view['zoom']:.2f} · 선굵기 {line_scale:.2f}×)")
        return {"png": str(out), "w_px": proj.w_px, "h_px": proj.h_px,
                "device_scale": capture_scale}
    except Exception as e:
        log(f"  ! 타일 배경 실패 ({e.__class__.__name__}: {e}) — 벡터 배경을 씁니다")
        return None


def _card_pin(card: dict) -> list:
    if not card["points"]:
        return [0.0, 0.0]
    return [sum(p["x"] for p in card["points"]) / len(card["points"]),
            sum(p["y"] for p in card["points"]) / len(card["points"])]


def _provisional_slots(mode, L, sides, avg_h, gap, tok) -> list:
    """각도 정렬용 임시 위치. 실제 높이는 배정 후 다시 쌓는다."""
    out = []
    n_left = sides.count("left") + sides.count("right")
    col = L["left_col"] if mode == "A" else L["right_col"]
    for i in range(n_left):
        out.append([col["x"], col["y0"] + i * (avg_h + gap)])
    n_bottom = sides.count("bottom")
    if n_bottom:
        pitch = (L["bottom_row"]["x1"] - L["bottom_row"]["x0"]) / max(n_bottom, 1)
        for j in range(n_bottom):
            out.append([L["bottom_row"]["x0"] + j * pitch, L["bottom_row"]["y"]])
    return out


def _materialize(assign, cards, sides, mode, L, gap, tok, frame) -> list:
    """슬롯 배정 결과를 실제 좌표로 굳힌다."""
    col = L["left_col"] if mode == "A" else L["right_col"]
    side_of = {i: sides[i] for i in range(len(sides))}
    col_cards = [(s, assign[s]) for s in sorted(assign) if side_of[s] != "bottom"]
    row_cards = [(s, assign[s]) for s in sorted(assign) if side_of[s] == "bottom"]

    placed = []
    y = col["y0"]
    for _, ci in col_cards:
        c = dict(cards[ci])
        c.update({"x": col["x"], "y": round(y, 4),
                  "side": "right" if mode == "B" else "left"})
        y += c["h"] + gap
        placed.append(c)
    if row_cards:
        n = len(row_cards)
        span = L["bottom_row"]["x1"] - L["bottom_row"]["x0"]
        step = span / n
        for j, (_, ci) in enumerate(row_cards):
            c = dict(cards[ci])
            c.update({"x": round(L["bottom_row"]["x0"] + j * step, 4),
                      "y": L["bottom_row"]["y"], "side": "bottom"})
            placed.append(c)
    # 좌측열만 꺾은선을 쓴다 — 카드 열을 벗어나는 지점(지도 왼쪽 경계 직전)에서 꺾는다
    gutter = round(frame["x"] - 0.06, 4) if mode == "A" else None
    for c in placed:
        c["anchor"] = anchor_of({"x": c["x"], "y": c["y"]}, c, c["side"])
        if c["side"] == "left":
            c["gutter"] = gutter
    return placed


def _targets(card: dict) -> list:
    """지시선을 그을 지점들 — **카드의 모든 대상지**.

    한 곳만 이으면 나머지 마커가 어느 사업인지 알 수 없는 고아가 된다
    (`과테말라시티/빌라누에바/믹스코/팔린` 은 4곳 중 3개가 떠 있었다).
    다중 대상지 카드만 예외로, 초록 원과 `* 원형 표시 지역` 주석이
    설명을 대신하므로 선을 긋지 않는다.
    """
    if card.get("no_leader") or not card["points"]:
        return []
    a = card["anchor"]
    return sorted(card["points"],
                  key=lambda p: (p["x"] - a[0]) ** 2 + (p["y"] - a[1]) ** 2)


def _leaders_of_card(card: dict) -> list:
    """카드 → 마커 지시선(대상지마다 하나). 좌측열은 **꺾은선**으로 뺀다.

    좌측열 카드에서 곧장 대각선을 그으면 아래 카드들의 사업명 위를 지나간다.
    지명 헤딩 높이로 수평으로 빠져나와 카드 열을 벗어난 뒤에 꺾으면
    글자 영역을 전혀 지나지 않는다 (헤딩 줄은 사업명보다 위에 있다).

    우측열(레이아웃 B)은 카드 왼쪽 모서리에서 지도 쪽으로 나가므로 애초에 겹치지 않는다.
    하단행도 카드 위가 비어 있어 직선으로 충분하다.
    """
    a = card["anchor"]
    gut = card.get("gutter")
    out = []
    for tp in _targets(card):
        t = [tp["x"], tp["y"]]
        pts = [a]
        if gut is not None and a[0] < gut < t[0]:
            pts.append([gut, a[1]])
        pts.append(t)
        out.append({"points": pts, "from": a, "to": t, "place": card["place"]})
    return out


def _improve(placed: list, mode: str, rounds: int = 40) -> None:
    """2-opt — 같은 변(side) 안에서 카드를 맞바꿔 지시선 교차를 줄인다."""
    def leaders_of(lst):
        return [l for c in lst for l in _leaders_of_card(c)]

    best = count_crossings(leaders_of(placed))
    if best == 0:
        return
    for _ in range(rounds):
        improved = False
        for i in range(len(placed)):
            for j in range(i + 1, len(placed)):
                a, b = placed[i], placed[j]
                if a["side"] != b["side"] or not (a["points"] or b["points"]):
                    continue
                _swap_slots(a, b)
                _restack(placed, a["side"])
                n = count_crossings(leaders_of(placed))
                if n < best:
                    best, improved = n, True
                else:
                    _swap_slots(a, b)
                    _restack(placed, a["side"])
        if not improved or best == 0:
            break


def _swap_slots(a: dict, b: dict) -> None:
    a["x"], b["x"] = b["x"], a["x"]
    a["y"], b["y"] = b["y"], a["y"]


def _restack(placed: list, side: str) -> None:
    """세로 열은 카드 높이가 달라 맞바꾼 뒤 다시 쌓아야 한다."""
    if side == "bottom":
        for c in placed:
            if c["side"] == "bottom":
                c["anchor"] = anchor_of(c, c, c["side"])
                return
    col = sorted([c for c in placed if c["side"] == side], key=lambda c: c["y"])
    if not col:
        return
    y = min(c["y"] for c in col)
    for c in col:
        c["y"] = round(y, 4)
        y += c["h"] + 0.10
        c["anchor"] = anchor_of(c, c, c["side"])


def _fits(placed, mode, L, tok) -> bool:
    col_key = "left_col" if mode == "A" else "right_col"
    for c in placed:
        if c["side"] == "bottom":
            if c["y"] + c["h"] > tok["canvas"]["h_in"] - 0.05:
                return False
        elif c["y"] + c["h"] > L[col_key]["y1"] + 0.02:
            return False
    return True


def _dedupe(markers: list) -> list:
    """같은 지도 좌표에는 마커를 하나만 남긴다.

    단일 대상 사업과 다중 대상 사업이 같은 도시를 공유하면 빨간 점과 초록 원이
    겹칠 수 있다. 이때는 해당 도시만을 직접 대상으로 하는 단일 대상 점을 우선한다.
    다중 대상 사업의 범위는 나머지 초록 원과 카드의 원형 표시 지역 주석에 남는다.
    """
    by_coord, order = {}, []
    for m in markers:
        k = (round(m["x"], 3), round(m["y"], 3))
        if k not in by_coord:
            by_coord[k] = m
            order.append(k)
        elif (m.get("marker_kind", "point") == "point"
              and by_coord[k].get("marker_kind", "point") != "point"):
            by_coord[k] = m
    return [by_coord[k] for k in order]


def _legend(tok: dict, lang: str) -> dict:
    """범례 배치를 **여기서 끝낸다** — 항목마다 좌표와 글자 크기를 굳혀서 넘긴다.

    렌더러가 각자 계산하면 갈라진다. 실제로 HTML 은 넘칠 때 글자를 줄였는데
    PPTX 는 그 축소를 빼먹어 영문 범례가 슬라이드 밖으로 흘러나갔다.

    한글은 글자를 세로로 쌓고(한 글자 = 1행), 영문은 통째로 90° 회전한다 —
    영문을 낱자로 쌓으면 읽히지 않는다.
    """
    from common import sector_map
    sm = sector_map()["badges"]
    lg = dict(tok["legend"])
    items = [{"key": k, "symbol": sm[k]["symbol"], "label": sm[k][lang]}
             for k in ("E", "H", "G", "A", "T")]
    en = lang == "en"
    gap, sw = 0.09, lg["swatch"]
    bottom = tok["canvas"]["h_in"] - 0.34          # 쪽번호 자리를 남긴다

    def label_h(s, size_pt):
        if en:                                      # 회전 → 글자열의 가로폭이 세로높이
            return text_width(s, size_pt)
        n = len([c for c in s if c != " "])
        return n * size_pt / 72.0 + s.count(" ") * size_pt / 144.0

    # 넘치면 **글자를 줄이기 전에 시작 위치를 올린다** — 원본이 그렇게 했다.
    # 국문 slide1 은 (11.91,4.29) 높이 2.33in, 영문 slide2 는 (11.84,2.95) 높이 3.68in
    # 로 둘 다 4.81pt 다. 영문 라벨이 길다고 3pt 로 줄이면 읽을 수 없다.
    size = lg["size"]
    y0 = lg["y0"]
    for _ in range(24):
        need = sum(sw + label_h(i["label"], size) + gap for i in items)
        y0 = min(lg["y0"], bottom - need)
        if y0 >= LEGEND_MIN_Y or size <= lg["size"] * 0.6:
            break
        size *= 0.94                                # 위로도 모자랄 때만 줄인다
    y0 = max(y0, LEGEND_MIN_Y)

    y = y0
    for it in items:
        h = label_h(it["label"], size)
        it.update({"x": lg["x"], "y": round(y, 4), "size": round(size, 3),
                   "label_y": round(y + sw + size / 72.0 * (1.0 if en else 0.9), 4),
                   "label_h": round(h, 4), "rotate": en})
        y += sw + h + gap
    lg["items"] = items
    lg["y0"] = round(y0, 4)
    lg["bottom"] = round(y - gap, 4)
    return lg


# ─────────────────────────────── CLI ───────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="프로젝트맵 배치 계산")
    ap.add_argument("--input", required=True, help="사업 목록 JSON")
    ap.add_argument("--out", required=True, help="layout.json 출력 경로")
    ap.add_argument("--lang", default="ko", choices=["ko", "en"])
    ap.add_argument("--index", type=int, default=1, help="국가 순번 (제목 로마숫자)")
    ap.add_argument("--detail", default="50m")
    a = ap.parse_args()

    doc = read_json(Path(a.input))
    out = compute(doc, a.lang, a.index, a.detail)
    write_json(Path(a.out), out, indent=1)
    log(f'  카드 {len(out["cards"])} · 마커 {len(out["markers"])} · 지시선 {len(out["leaders"])} '
        f'· 교차 {out["crossings"]} · 글자가림 {out["text_hits"]} · 폰트 {out["font_scale"]}배')
    for w in out["warnings"]:
        log(f"  ! {w}")
    log(f'  → {a.out}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
