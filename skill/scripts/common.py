"""KOICA 프로젝트맵 — 공용 유틸.

캐시 다운로드, 지오메트리 계산, design.md 토큰 로더, 문자열 정규화.
표준 라이브러리 + PyYAML 만 사용한다 (shapely/pyproj 불필요).
"""
from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_DIR / "cache"
GEO_CACHE = CACHE_DIR / "geo"
REFERENCE_DIR = SKILL_DIR / "reference"

UA = "koica-project-map/1.0 (KOICA project map generator)"


# ─────────────────────────────── 다운로드 · 캐시 ───────────────────────────────

def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def fetch(url: str, dest: Path, force: bool = False) -> Path:
    """URL을 dest에 내려받는다. 이미 있으면 재사용."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest
    log(f"  ↓ {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def fetch_json(url: str, dest: Path, force: bool = False):
    return json.loads(fetch(url, dest, force).read_text(encoding="utf-8"))


def unzip_member(zip_path: Path, member: str, dest: Path) -> Path:
    """zip 안의 파일 하나를 dest로 추출한다."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        dest.write_bytes(z.read(member))
    return dest


# ─────────────────────────────── 문자열 정규화 ───────────────────────────────

def norm(s: str) -> str:
    """발음기호 제거 · 소문자 · 구분자 통일. 지명 매칭 키로 쓴다."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[-_'`’.]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# ─────────────────────────────── 지오메트리 ───────────────────────────────

def iter_rings(geom: dict):
    """GeoJSON geometry → 좌표열 리스트.

    Polygon/MultiPolygon 뿐 아니라 LineString/MultiLineString 도 다뤄야 한다.
    하천은 MultiLineString 인데 이걸 빠뜨리면 bbox 가 [0,0,0,0] 이 되어
    화면 범위와 절대 교차하지 않고 조용히 사라진다.
    """
    if not geom:
        return
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Polygon":
        for ring in c:
            yield ring
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield ring
    elif t == "LineString":
        yield c
    elif t == "MultiLineString":
        for line in c:
            yield line


def outer_rings(geom: dict) -> list:
    """구멍(hole)을 제외한 외곽 링만. 각 폴리곤의 첫 링이 외곽이다."""
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Polygon":
        return [c[0]] if c else []
    if t == "MultiPolygon":
        return [poly[0] for poly in c if poly]
    return []


def bbox_of(geom: dict) -> list:
    xs, ys = [], []
    for ring in iter_rings(geom):
        for p in ring:
            xs.append(p[0])
            ys.append(p[1])
    if not xs:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs), min(ys), max(xs), max(ys)]


def ring_area(ring: list) -> float:
    """구면 보정 없는 평면 부호 면적 (신발끈 공식)."""
    a = 0.0
    n = len(ring)
    for i in range(n - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return a / 2.0


def centroid_of(geom: dict) -> list:
    """면적 가중 중심점. 폴리곤이 여러 개면 가장 큰 것 기준."""
    best, best_area = None, -1.0
    for ring in outer_rings(geom):
        a = abs(ring_area(ring))
        if a > best_area:
            best_area, best = a, ring
    if not best:
        return [0.0, 0.0]
    a = ring_area(best)
    if abs(a) < 1e-12:
        xs = [p[0] for p in best]
        ys = [p[1] for p in best]
        return [sum(xs) / len(xs), sum(ys) / len(ys)]
    cx = cy = 0.0
    for i in range(len(best) - 1):
        x0, y0 = best[i][0], best[i][1]
        x1, y1 = best[i + 1][0], best[i + 1][1]
        f = x0 * y1 - x1 * y0
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    return [cx / (6 * a), cy / (6 * a)]


def geom_area_deg2(geom: dict) -> float:
    """외곽 링 면적 합 (제곱도). 면 크기 비교용."""
    return sum(abs(ring_area(r)) for r in outer_rings(geom))


def bbox_intersects(a: list, b: list, pad: float = 0.0) -> bool:
    return not (a[2] + pad < b[0] or b[2] < a[0] - pad
                or a[3] + pad < b[1] or b[3] < a[1] - pad)


def simplify(ring: list, tol: float) -> list:
    """Douglas-Peucker. tol 단위는 도(degree)."""
    if len(ring) < 4 or tol <= 0:
        return ring

    def dp(pts):
        if len(pts) < 3:
            return pts
        x0, y0 = pts[0][0], pts[0][1]
        x1, y1 = pts[-1][0], pts[-1][1]
        dx, dy = x1 - x0, y1 - y0
        den = math.hypot(dx, dy)
        imax, dmax = 0, -1.0
        for i in range(1, len(pts) - 1):
            px, py = pts[i][0], pts[i][1]
            d = (abs(dy * px - dx * py + x1 * y0 - y1 * x0) / den) if den > 1e-15 \
                else math.hypot(px - x0, py - y0)
            if d > dmax:
                imax, dmax = i, d
        if dmax <= tol:
            return [pts[0], pts[-1]]
        return dp(pts[:imax + 1])[:-1] + dp(pts[imax:])

    closed = ring[0] == ring[-1]
    out = dp(ring)
    if closed and out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else ring


def round_ring(ring: list, nd: int = 4) -> list:
    return [[round(p[0], nd), round(p[1], nd)] for p in ring]


# ─────────────────────────────── design.md 토큰 ───────────────────────────────

_TOKENS = None


def design_tokens(path: Path | None = None) -> dict:
    """design.md 의 첫 ```yaml 블록을 파싱해 디자인 토큰을 돌려준다."""
    global _TOKENS
    if _TOKENS is not None and path is None:
        return _TOKENS
    import yaml

    if path is None:
        candidates = [
            SKILL_DIR.parent / "design.md",   # 개발 저장소
            SKILL_DIR / "design.md",          # 설치본
            REFERENCE_DIR / "design.md",
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            raise FileNotFoundError(
                "design.md 를 찾을 수 없습니다. 다음 중 한 곳에 두세요:\n  "
                + "\n  ".join(str(p) for p in candidates))
    blocks = re.findall(r"```yaml\n(.*?)```", path.read_text(encoding="utf-8"), re.S)
    if not blocks:
        raise ValueError(f"{path} 에 ```yaml 토큰 블록이 없습니다.")
    tokens = yaml.safe_load(blocks[0])
    if path is None:
        _TOKENS = tokens
    _TOKENS = tokens
    return tokens


def sector_map() -> dict:
    import yaml
    p = REFERENCE_DIR / "sector_map.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def read_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, data, indent: int | None = None) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    return p
