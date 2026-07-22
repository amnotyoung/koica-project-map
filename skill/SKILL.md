---
name: koica-project-map
description: KOICA 연도별 프로젝트맵(사업 위치 지도) 자동 생성 스킬. 사업 목록을 주면 지명→좌표 해석, 카드 배치, 지시선 라우팅을 자동 수행해 PPTX·PDF·HTML로 출력한다. 트리거 키워드 — "프로젝트맵 그려줘", "코이카 사업 지도", "국가별 사업현황 지도", "프로젝트맵 만들어줘", "사업 위치도", "koica-project-map 스킬로 ~". 사용자가 특정 국가의 KOICA 사업들을 지도 위에 카드·지시선으로 표시한 슬라이드를 원할 때 사용.
---

# koica-project-map — KOICA 프로젝트맵 자동 생성

파워포인트에서 슬라이드 한 장에 도형 86개를 손으로 맞추던 작업을 자동화한다.

디자인 기준은 **`design.md`** 단일 출처다. 색·크기·여백을 바꾸려면 그 파일을 고친다
(스크립트가 YAML 블록을 직접 파싱한다). 배치 알고리즘은 `scripts/layout.py` 에 있다.

## 워크플로

### 1. 사업 정보 → `projects.json`

사용자가 준 사업 정보를 아래 형식으로 만든다. **사업명은 원문 그대로** 둔다
(`사업명(기간/예산)` 형식 유지 — 임의로 줄이지 않는다).

```json
{
  "country": "네팔",
  "country_en": "Nepal",
  "region": "아시아태평양",
  "projects": [
    {
      "place": "카트만두/부트왈",
      "badges": ["G"],
      "name_ko": "네팔 한국 귀환노동자 안정적 재정착을 위한 단계별 지원체계 강화사업(2022-2028/800만불)",
      "name_en": "Project for strengthening stage-wise support system ...(2022-2028/$8.0mil)"
    }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `place` | 지명. 여러 곳은 `/` 로 연결. 끝에 `주`·`지역`·`전역`이 붙으면 면 단위로 인식 |
| `badges` | 분야 배지 `E`(교육) `H`(보건) `G`(공공행정) `A`(농림수산) `T`(기술환경에너지). 복수 가능 |
| `name_ko` / `name_en` | 사업명. 영문 슬라이드를 만들 때만 `name_en` 필요 |
| `kind` | (선택) `point` / `area` 강제 지정 |
| `place_en` | (선택) 영문 지명 직접 지정. 없으면 해석된 라틴 표기를 자동 사용 |
| `country_en` | (선택) 국가 영문명. Natural Earth 표기가 KOICA 관례와 다를 때 (`East Timor` → `Timor-Leste`) |

**분야 배지 정하기** — `reference/sector_map.yaml` 에서 세부 분야명을 찾아 5종 중 하나로 매핑한다.
매핑에 없으면 사업 성격을 보고 5종 중 하나로 분류한 뒤 **그 파일에 추가**하고 사용자에게 알린다.

### 2. 생성

```bash
skill/.venv/bin/python scripts/make_map.py --input projects.json --outdir out --lang ko en
```

지명 해석 → 배치 → HTML/PDF/PPTX 까지 한 번에 처리한다. 국가별 JSON 을 여러 개 넘기면
슬라이드가 순서대로 쌓인 덱 하나가 나온다.

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--lang` | `ko` | `ko` `en` 복수 지정 가능. 함께 지정하면 두 슬라이드의 폰트 배율을 맞춘다 |
| `--formats` | `html pdf pptx` | `png` 추가 가능 |
| `--detail` | `50m` | 국경 해상도. 작은 나라는 `10m` |
| `--scale` | `2` | PNG 배율 (2 = 192dpi) |

### 3. 미해석 지명 처리

실행 로그에 `✗ <지명> — ...` 이 뜨면 자동 해석에 실패한 것이다. 순서대로 대응한다.

1. **로마자 후보를 만들어 재시도** — 한글 음차의 원 표기를 추정해 `aliases` 에 넣는다.
   예: `바디바스` → `["Bardibas", "Bardibash"]`
   ```json
   {"place": "바디바스", "aliases": ["Bardibas"], "badges": ["E"], "name_ko": "..."}
   ```
2. **그래도 안 되면 사용자에게 묻는다.** 추측해서 엉뚱한 곳에 찍지 말 것
3. **좌표를 알면 사전에 등록** — 한 번 넣으면 계속 재사용된다
   ```bash
   python scripts/resolve_places.py --country 네팔 --set 바디바스 85.90 27.07 --set-kind point
   ```

### 4. 확인 · 조정

`out/<이름>_<언어>.html` 을 열어 확인한다. 로그의 **교차** 수가 0 이 아니면 지시선이
겹친 것이니 사용자에게 알린다. 핀 위치가 틀리면 3-3 의 `--set` 으로 고친 뒤 다시 돌린다.

### 5. 결과 안내

생성된 파일 경로를 알려준다. PPTX 는 지도만 이미지이고 **카드·배지·지시선·마커는 편집 가능한
도형**이라 파워포인트에서 그대로 손볼 수 있다는 점을 함께 안내한다.

## 산출물

```
out/
├── <이름>_ko.layout.json   # 배치 계산 결과 (모든 좌표)
├── <이름>_ko.html          # SVG 슬라이드 (미리보기)
├── <이름>_ko.pdf           # 인쇄·발표용
└── project_map.pptx        # 편집 가능한 덱 (여러 국가·언어를 한 파일로)
```

## 구성

| 파일 | 역할 |
|---|---|
| `design.md` | **디자인 단일 출처** — 토큰(YAML) + 판단 규칙 |
| `reference/sector_map.yaml` | 세부 분야 214종 → 배지 5종 매핑 |
| `scripts/geo_prepare.py` | 국가 경계·지명 사전 준비 (Natural Earth / geoBoundaries / GeoNames) |
| `scripts/basemap_tiles.py` | OSM 벡터 타일 → 배경 지도 (도로·하천 밀도) |
| `scripts/cdp.py` | Chrome 원격제어 — 타일 렌더 완료를 기다렸다 캡처 |
| `scripts/resolve_places.py` | 지명 → 좌표. `--set` 으로 수동 보정 |
| `scripts/hangul.py` | 한글 음차 ↔ 라틴 지명 매칭 |
| `scripts/layout.py` | **배치 계산** — 투영·카드·슬롯·교차 제거 |
| `scripts/render_html.py` | layout.json → SVG |
| `scripts/render_pptx.py` | layout.json → 편집 가능한 PPTX |
| `scripts/export.py` | HTML → PDF/PNG (headless Chrome) |
| `scripts/make_map.py` | 전 과정 오케스트레이터 |

`cache/` 는 국가별 경계 데이터와 확정 지명 좌표(`gazetteer.json`)를 쌓아둔다. 지우면 다시 받는다.

## 의존성

- Python 3.10+ · PyYAML
- **python-pptx** — `skill/.venv` 에 설치되어 있다. PPTX 를 만들려면 `skill/.venv/bin/python` 으로 실행할 것
- Google Chrome — PDF/PNG 출력 + 타일 배경 렌더(WebGL, headless 에서 SwiftShader 로 동작)
- 네트워크 — 경계·지명 데이터와 지도 타일. 모두 캐시되며, 없으면 Natural Earth 벡터 배경으로 자동 대체

venv 가 없으면 만든다:
```bash
python3 -m venv skill/.venv --system-site-packages && skill/.venv/bin/pip install python-pptx
```

## 주의

- **배치를 렌더러에서 다시 계산하지 말 것.** 좌표는 `layout.json` 이 유일한 출처다. 렌더러가 제 나름대로 위치를 잡으면 HTML 과 PPTX 가 갈라진다
- **사업을 임의로 빼지 말 것.** 카드가 넘치면 폰트 축소 → 지도 축소 순으로 대응하고, 그래도 안 되면 슬라이드 분할을 사용자에게 제안한다
- **oda-map-lab 데이터는 사업 선정 소스가 아니다.** 좌표 43%가 국가 중심점 폴백이고 한글 지명 커버리지가 낮다. 사업 목록은 사용자가 준다
- 출처 표기(Natural Earth · geoBoundaries · GeoNames)는 슬라이드 하단에 자동으로 들어간다
