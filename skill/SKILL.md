---
name: koica-project-map
description: KOICA 연도별 프로젝트맵(사업 위치 지도) 자동 생성 스킬. 국가 전체 또는 국가 내 특정 시·도·도시 범위에서 지명→좌표 해석, 상세 지도 생성, 카드 배치, 지시선 라우팅을 수행해 PPTX·PDF·HTML로 출력한다. 트리거 키워드 — "프로젝트맵 그려줘", "코이카 사업 지도", "국가별 사업현황 지도", "도시·시도 사업 지도", "프로젝트맵 만들어줘", "사업 위치도", "koica-project-map 스킬로 ~". 사용자가 KOICA 사업들을 지도 위에 카드·지시선으로 표시한 슬라이드를 원할 때 사용.
---

# koica-project-map — KOICA 프로젝트맵 자동 생성

파워포인트에서 슬라이드 한 장에 도형 86개를 손으로 맞추던 작업을 자동화한다.

디자인 기준은 **`design.md`** 단일 출처다. 색·크기·여백을 바꾸려면 그 파일을 고친다
(스크립트가 YAML 블록을 직접 파싱한다). 배치 알고리즘은 `scripts/layout.py` 에 있다.

## 워크플로

### 1. 사업 목록 만들기

**(a) 사이트에서 받아 고르기 — 권장**

```bash
skill/.venv/bin/python skill/scripts/pick_projects.py \
  --country 네팔 --year 2026 --out projects.json
```

oda-map-lab 에서 그 국가 KOICA 사업을 **전부** 끌어와 브라우저 체크박스 UI 를 연다.
사업명(국·영문)·지명·분야 배지를 그 자리에서 고칠 수 있고, 없는 사업은 `+ 직접 추가` 로 넣는다.
저장하면 `projects.json` 이 만들어지고 서버는 닫힌다.

- 국별협력사업(프로젝트 원조·30억원 이상·진행)은 **기본 체크**, 봉사단·연수는 해제 상태
- **지명은 추정값이다.** 원본 그룹 라벨을 옮긴 것이라 실제 대상지와 다를 수 있다
  (`룸비니` 그룹에 버르디야 사업이 들어 있는 식) — 이 확인이 이 단계의 핵심이다
- **좌표는 출처로 선별한다.** `국가(폴백)`은 버리고 지명에서 다시 풀며, 도시·도시(음차)·
  IATI 원본(공식좌표)은 지명이 바뀌지 않은 단일 대상지에 사용한다. 수정 화면에서 지명을
  바꾸면 기존 원천 좌표도 폐기된다
- 사이트에 아직 없는 신규 사업이 있다 (샘플 네팔 10건 중 3건). `+ 직접 추가` 로 넣는다

**(b) 직접 작성**

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
| `place` | 지명. 여러 곳은 `/` 로 연결. 끝에 `주`·`지역`·`전역`이 붙으면 지명 해석상 면 단위로 인식 |
| `badges` | 분야 배지 `E`(교육) `H`(보건) `G`(공공행정) `A`(농림수산) `T`(기술환경에너지). 복수 가능 |
| `name_ko` / `name_en` | 사업명. 영문 슬라이드를 만들 때만 `name_en` 필요 |
| `kind` | (선택) 지명 해석을 `point` / `area`로 강제. 마커 종류와는 무관 |
| `place_en` | (선택) 영문 지명 직접 지정. 없으면 해석된 라틴 표기를 자동 사용 |
| `country_en` | (선택) 국가 영문명. Natural Earth 표기가 KOICA 관례와 다를 때 (`East Timor` → `Timor-Leste`) |
| `map_bbox` | (선택) `[서, 남, 동, 북]` 지도 범위. 도시·시도급 확대 지도 또는 외곽 섬을 제외할 때 사용 |
| `map_density` | (선택) `standard` / `city`, 기본 `city`. 국가 전체와 도시·시도 지도 모두 5배 타일 밀도와 상세 도로·철도·토지피복을 사용 |
| `source_coord` | (자동) oda-map-lab 비폴백 좌표와 출처. 수집·수정 화면이 보존하며 직접 작성할 필요 없음 |

**도시·시도급 지도는 `map_bbox`를 반드시 지정한다.** `map_density`는 보통 적지 않는다.
국가 전체와 사용자 지정 범위 모두 과테말라시티 참조본 수준의 `city` 상세도가 기본이다.
전국 범위에서는 같은 피처 상세도를 유지하되 도로·하천 선을 축척에 맞춰 자동으로
가늘게 해 지시선과 사업 마커를 우선한다. 사용자가 단순화·경량 출력을 명시한 경우에만
`standard`로 낮춘다.

**같은 장소 사업은 입력에서 합치지 않는다.** 사업 레코드와 분야 배지는 각각 보존하고,
배치 엔진이 같은 지명·같은 좌표를 하나의 장소 블록으로 묶는다. 출력에서는 지명 헤딩과
지시선을 한 번만 쓰고 그 아래에 모든 사업을 이어 표시한다.

**분야 배지 정하기** — `reference/sector_map.yaml` 에서 세부 분야명을 찾아 5종 중 하나로 매핑한다.
매핑에 없으면 사업 성격을 보고 5종 중 하나로 분류한 뒤 **그 파일에 추가**하고 사용자에게 알린다.

### 2. 생성

```bash
skill/.venv/bin/python skill/scripts/make_map.py \
  --input projects.json --outdir out --lang ko en
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

원천 위치 처리 순서는 사용자 확정 gazetteer → oda-map-lab 비폴백 좌표 → 지명 자동해석이다.
비폴백 좌표가 없거나 여러 대상지가 묶인 경우 아래 순서로 대응한다.

1. **로마자 후보를 만들어 재시도** — 한글 음차의 원 표기를 추정해 `aliases` 에 넣는다.
   예: `바디바스` → `["Bardibas", "Bardibash"]`
   ```json
   {"place": "바디바스", "aliases": ["Bardibas"], "badges": ["E"], "name_ko": "..."}
   ```
2. **그래도 안 되면 사용자에게 묻는다.** 추측해서 엉뚱한 곳에 찍지 말 것
3. **좌표를 알면 사전에 등록** — 한 번 넣으면 계속 재사용된다
   ```bash
   skill/.venv/bin/python skill/scripts/resolve_places.py \
     --country 네팔 --set 바디바스 85.90 27.07 --set-kind point
   ```

### 4. 확인 · 조정

`out/<이름>_<언어>.html` 을 열어 확인한다. 로그의 **교차** 수가 0 이 아니면 지시선이
겹친 것이니 사용자에게 알린다. 핀 위치가 틀리면 3-3 의 `--set` 으로 고친 뒤 다시 돌린다.

- **마커를 반드시 확인한다.** 한 사업의 대상지가 1곳이면 행정구역 여부와 무관하게 빨간 점,
  2곳 이상이면 각 대상지에 내부가 빈 초록 테두리 원을 표시한다. 초록 원 안에 빨간 점이
  함께 보이면 렌더러 분기 오류이므로 결과를 내보내지 않는다.
- **반복 지명을 반드시 확인한다.** 같은 지명·같은 좌표의 사업이 여러 건이면 지명 헤딩과
  지시선은 장소 블록당 하나여야 한다. 사업명·분야 배지는 빠짐없이 모두 남아야 한다.
- **참조본과 데이터부터 대조한다.** 사업 수와 `지명 → 사업 수`를 먼저 표로 비교한다.
  참조본과 입력의 지명·사업 목록이 다르면 이를 레이아웃 차이로 숨기지 말고 데이터 차이로
  보고한다. 근거 없이 도시 사업을 전국사업으로 바꾸거나 누락 사업을 지어내지 않는다.
- **제목 블록을 반드시 확인한다.** 국문 슬라이드는 국문·영문명을 별도 텍스트 상자로
  만들지 않는다. 한 자동맞춤 텍스트 상자의 같은 문단에 23.09pt 국문 런과 10.9pt
  영문 런을 연속해서 넣어 `피지 Fiji`처럼 **한 줄**로 보이게 한다. 줄바꿈 문자나
  별도 영문 줄을 추가하지 않는다. 한글 런의 East Asian 글꼴도 `맑은 고딕`으로 명시한다.
  영문 슬라이드는 영문명만 박스 안에 둔다. 로마숫자는 Georgia 굵게, 테두리는
  2pt `#B0B1D6` 자유형 사각형이다. 제목 텍스트를 먼저, 박스를 나중에 그려 박스
  아래선이 국문 `ㅣ` 획 위에 놓이는 원본 z-order도 유지한다.
  LibreOffice·Quick Look은 원본의 자동맞춤 상자를 두 줄로 재배치할 수 있으므로 제목
  줄 수의 판정에 사용하지 않는다. OOXML에 한 문단·두 런·줄바꿈 없음이 있는지 검사하고,
  최종 기준은 Microsoft PowerPoint 표시다.

**PPTX를 생성한 요청에서는 PowerPoint 자체 렌더 검증을 생략하지 않는다.**
사용자가 HTML·PDF·layout JSON만 요청해 PPTX를 만들지 않은 실행에는 적용하지 않는다.

- macOS에 `/Applications/Microsoft PowerPoint.app`이 있으면 PPTX를 PowerPoint에서
  열어 PDF로 내보내고, `pdftoppm`으로 PNG를 만든 뒤 제목·카드·범례를 눈으로 확인한다.
  `open` 명령의 반환값을 변수로 쓰지 말고 `active presentation`을 잡는다.
  원본 PPTX는 `close ... saving no`로 닫아 수정하지 않는다.
  ```applescript
  tell application "Microsoft PowerPoint"
    open (POSIX file inputPath)
    set deckRef to active presentation
    save deckRef in (POSIX file outputPdf) as save as PDF
    close deckRef saving no
  end tell
  ```
- 참조 PPTX가 있으면 참조본도 같은 PowerPoint·같은 DPI로 렌더해 나란히 비교한다.
  제목은 텍스트 내용만 보지 말고 핀·흰 타원·로마숫자·외곽선까지 포함한 crop을 본다.
- PowerPoint를 사용할 수 없으면 OOXML에서 **한 텍스트 상자·한 문단·두 런·`a:br` 없음**,
  런 크기/글꼴/`spc`/`baseline`, 도형 좌표와 z-order를 검사한다. 결과 안내에는
  “PowerPoint 시각 렌더는 검증하지 못했고 구조만 검증했다”고 명시한다.
- LibreOffice·Quick Look 렌더는 다른 요소의 참고용일 수는 있어도 제목 줄 수·글꼴
  충실도의 합격 근거로 인용하지 않는다.

### 5. 결과 안내

생성된 파일 경로를 알려준다. PPTX 는 지도만 이미지이고 **카드·배지·지시선·마커는 편집 가능한
도형**이라 파워포인트에서 그대로 손볼 수 있다는 점을 함께 안내한다.

### 6. 수정 화면 제안

지도를 새로 생성하거나 수정본을 재생성한 뒤, 결과 안내 마지막에 사용자에게 다음 취지로 묻는다.

> 사업 선택·지명·분야·사업명을 수정할 수 있는 수정 화면을 열어드릴까요?

- **먼저 묻고 답을 기다린다.** 사용자의 동의 없이 편집 서버나 브라우저를 자동으로 열지 않는다.
- 사용자가 이미 같은 요청에서 수정 화면까지 열어 달라고 했다면 다시 묻지 말고 바로 연다.
- 사용자가 원하면 이번 생성에 사용한 **최종 입력 JSON**을 초안으로 편집 화면을 연다.
  원천 수집 초안을 다시 열어 수동 보정값을 잃지 않는다.
  ```bash
  skill/.venv/bin/python skill/scripts/pick_projects.py \
    --draft <최종입력.json> --out <이름>_edited.json
  ```
- 로그에 나온 로컬 URL을 브라우저에 열고, 기존 선택·지명·배지·국영문 사업명이 채워졌는지
  확인한 뒤 사용자에게 넘긴다.
- 사용자가 저장하면 `<이름>_edited.json` 으로 지도를 다시 생성하고 3~5단계 검수를 반복한다.
- 사용자가 필요 없다고 하면 편집 서버를 시작하지 않고 작업을 끝낸다.

### 7. 위치 정보 기여 제안

생성 로그에 `── 위치 정보 기여 제안 ──` 이 뜨면, 원천 데이터가 **국가 중심점**으로만 알고
있던 지점을 이번에 정밀화했다는 뜻이다. 사용자에게 알리고 원하면 파일을 만들어 준다.

```bash
skill/.venv/bin/python skill/scripts/contribute.py \
  --layout out/<이름>_ko.layout.json --author "이름"
```

`koica-contrib` 규격(schema v2) JSON 이 나온다. 국가폴백이던 지점은 `corrects` 로 묶여
"이 핀을 이 좌표로 고쳐 달라"는 형태가 된다.

- **자동으로 보내지 않는다.** 파일만 만들고 제출은 사용자가 한다
- 작성자 이름이 필수다 — **임의로 지어내지 말고 사용자에게 묻는다**
- 보내기 전에 파일을 열어 좌표·작성자를 확인하라고 안내한다

## 산출물

실행마다 **날짜·시각 하위폴더**로 나뉜다. 이전 결과를 덮어쓰지 않고 이력이 쌓인다.
`--flat` 을 주면 outdir 에 바로 쓴다(옛 방식·덮어쓰기).

```
out/
├── latest → 2026-07-23_1329/       # 최신 실행을 가리키는 심볼릭 링크
├── 2026-07-23_1329/                # 실행 1회분
│   ├── <이름>_ko.layout.json       # 배치 계산 결과 (모든 좌표)
│   ├── <이름>_ko.html · .pdf · .png
│   └── project_map.pptx            # 편집 가능한 덱 (여러 국가·언어를 한 파일로)
└── 2026-07-23_1015/                # 이전 실행 (남아 있음)
```

- 최신본은 항상 `out/latest/` 로 연다
- 산출물이 사라졌다는 문의가 오면 이 하위폴더 구조부터 확인한다 (옛 실행은 다른 폴더에 있다)

## 구성

| 파일 | 역할 |
|---|---|
| `design.md` | **디자인 단일 출처** — 토큰(YAML) + 판단 규칙 |
| `reference/sector_map.yaml` | 세부 분야 214종 → 배지 5종 매핑 |
| `scripts/fetch_projects.py` | oda-map-lab 에서 국가별 KOICA 사업 전량 수집 (초안) |
| `scripts/pick_projects.py` | 브라우저 체크박스 UI — 선택·편집 → `projects.json` |
| `scripts/contribute.py` | 정밀 좌표 → oda-map-lab 기여 파일 (전송은 사용자가) |
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
- **마커는 행정단위가 아니라 사업별 대상지 수로 정할 것.** 1곳은 빨간 점, 2곳 이상은 초록 테두리 원이며 두 종류를 겹쳐 그리지 않는다. HTML·PPTX 렌더러가 같은 `marker_kind` 분기를 써야 한다
- **같은 장소를 사업마다 반복하지 말 것.** 동일 지명·동일 좌표는 하나의 장소 블록으로 배치하고 헤딩·지시선은 한 번만 그린다. 사업명과 분야 배지는 각 사업별로 유지한다
- **사업을 임의로 빼지 말 것.** 카드가 넘치면 폰트 축소 → 지도 축소 순으로 대응하고, 그래도 안 되면 슬라이드 분할을 사용자에게 제안한다
- **oda-map-lab 좌표는 출처로 선별할 것.** `국가(폴백)`만 버리고 지명에서 다시 풀며, 그 밖의 유효 좌표는 지명이 바뀌지 않은 단일 대상지에 사용한다. 여러 대상지를 한 좌표로 복제하지 않는다
- **기여 파일을 대신 제출하지 말 것.** 남의 서비스로 데이터를 보내는 일은 사용자가 결정한다. 작성자 이름도 지어내지 않는다
- 출처 표기(Natural Earth · geoBoundaries · GeoNames)는 슬라이드 하단에 자동으로 들어간다
