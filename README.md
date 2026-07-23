# KOICA 프로젝트맵 자동 생성

KOICA가 파워포인트로 손수 그리던 연도별 사업 지도(슬라이드당 도형 86개)를 자동 생성한다.
사업 목록을 주면 지명→좌표 해석, 카드 배치, 지시선 라우팅, 렌더링까지 처리한다.

```bash
# 1) 사이트에서 사업을 받아 체크박스로 고르고
skill/.venv/bin/python skill/scripts/pick_projects.py --country 네팔 --year 2026 --out nepal.json
# 2) 지도를 만든다 (out/<날짜_시각>/ 에 생성, out/latest 로 최신 접근)
skill/.venv/bin/python skill/scripts/make_map.py --input nepal.json --outdir out --lang ko en
```

만들고 나면 **정밀화한 위치를 oda-map-lab 에 돌려주라는 제안**이 뜬다.
`contribute.py` 가 `koica-contrib` 규격 파일을 만들어 주고, 제출은 사용자가 직접 한다.

## 구조

```
design.md                  ★ 디자인 단일 출처 — 토큰(YAML) + 판단 규칙
skill/                     → ~/.claude/skills/koica-project-map 로 심볼릭 링크
├── SKILL.md               Claude 가 읽는 워크플로
├── reference/
│   └── sector_map.yaml    세부 분야 214종 → 배지 5종(E/H/G/A/…)
├── scripts/
│   ├── make_map.py        전 과정 오케스트레이터
│   ├── fetch_projects.py  oda-map-lab → 국가별 사업 전량 수집
│   ├── pick_projects.py   브라우저 체크박스 UI (선택·편집)
│   ├── contribute.py      정밀 좌표 → 기여 파일
│   ├── geo_prepare.py     국가 경계·지명 사전 준비
│   ├── basemap_tiles.py   OSM 벡터 타일 → 배경 지도 (도로·하천)
│   ├── cdp.py             Chrome 원격제어 (타일 렌더 대기 후 캡처)
│   ├── resolve_places.py  지명 → 좌표 (+ 수동 보정)
│   ├── hangul.py          한글 음차 ↔ 라틴 지명 매칭
│   ├── layout.py          ★ 배치 계산 (투영·카드·슬롯·교차 제거)
│   ├── render_html.py     layout.json → SVG
│   ├── render_pptx.py     layout.json → 편집 가능한 PPTX
│   └── export.py          HTML → PDF/PNG
└── cache/                 경계 데이터 · 확정 지명 좌표 (자동 생성, 커밋 안 함)
tests/                     검증용 입력 (네팔·동티모르·우즈베키스탄)
```

> `design.md` 의 수치는 KOICA 내부 샘플 PPTX 를 실측해 얻은 것이다. 원본 파일은 내부
> 문서라 저장소에 포함하지 않는다 — 실측 결과인 `design.md` 만으로 재현에 충분하다.

## 설계 원칙

**배치 계산 1회 → 렌더러 2개.** `layout.py` 가 모든 좌표를 정해 `layout.json` 에 굳히고,
HTML(미리보기·PDF)과 PPTX(편집용)가 그것만 소비한다. 렌더러가 위치를 다시 계산하면 두 출력이 갈라진다.

**design.md = 무엇을 / layout.py = 어떻게.** 색·크기·여백 같은 기관 표준은 사람이 읽고 고치는
문서에 두되, 배치 알고리즘은 코드에 둔다. 산문으로 쓰면 실행마다 해석이 달라진다.
토큰은 design.md 안 YAML 블록에 있고 스크립트가 직접 파싱한다 — 문서와 코드가 갈라지지 않는다.

## 검증 결과

샘플 PPTX(네팔 slide1 · 동티모르 slide3) 재현 기준.

| 항목 | 결과 |
|---|---|
| 지명 해석률 | **100%** (네팔 13 / 동티모르 10 / 우즈베키스탄 4) |
| 지시선 교차 | **0건** (전 슬라이드) |
| 폰트 축소 | 국문 1.0배 (영문 병행 시 0.85배로 짝맞춤) |
| 레이아웃 자동선택 | 네팔 A(10건) · 동티모르 B(8건) · 우즈베키스탄 B(5건) |
| PPTX 편집성 | 슬라이드당 도형 93개 — 지도만 이미지, 나머지는 텍스트박스·도형 |
| 미지원 국가 | 우즈베키스탄 첫 시도 성공 (경계·지명 자동 확보) |

### 한글 음차 지명 매칭

`바디바스` ↔ `Bardibas` 처럼 한글로 음차된 외국 지명을 라틴 표기에 붙이는 것이 핵심 난제였다.
양쪽을 같은 느슨한 키로 눌러 비교한다 — 유기음 h, r/l 구분, 겹자음, 매개모음 `으`,
어말 모음, 로망스어권 정자법(`qu`→`k`, `v`→`b`)을 양쪽에서 똑같이 지운다.

샘플 PPT 지명 23개 기준 **정매칭 100%, 같은 국가 내 오탐 0건**.

## 알려진 한계

- **oda-map-lab 에서 받는 것과 안 받는 것이 갈린다.** 사업명·기간·예산·분야는 원문 그대로
  받아 쓰지만 **좌표는 쓰지 않는다** — 사업 지점 43%가 국가 중심점 폴백이다. 위치는 지명에서
  다시 푼다. 지명도 그룹 라벨이라 추정값이어서 `pick_projects.py` 의 사람 확인이 필수다
- **사이트에 없는 신규 사업이 있다.** 원천이 IATI 라 등록이 늦다 — 샘플 네팔 10건 중 3건이
  빠져 있었다. 선택 UI 의 `+ 직접 추가` 로 넣는다
- 지도 배경은 OSM 벡터 타일(versatiles)을 MapLibre 로 렌더해 쓴다. 네트워크나 Chrome 이
  없으면 Natural Earth 벡터 배경으로 자동 대체되지만, 그 경우 도로가 없고 하천도 성글다
- headless Chrome 이 이 환경에서 정상 종료하지 않아, `export.py` 는 산출 파일이 안정되면
  프로세스를 종료시킨다

## 출처

Natural Earth(퍼블릭 도메인) · [geoBoundaries](https://www.geoboundaries.org/)(CC BY) ·
[GeoNames](https://www.geonames.org/)(CC BY) · 지도 타일 [versatiles](https://versatiles.org/)
(© OpenStreetMap contributors, ODbL). 생성물 하단에 자동 표기된다.
