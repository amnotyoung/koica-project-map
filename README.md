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

## 국가별 범용 생성

```bash
skill/.venv/bin/python skill/scripts/make_map.py \
  --country 네팔 동티모르 피지 우즈베키스탄 --year 2026 \
  --outdir out --lang ko --formats html png pptx
```

원본 PPTX 없이 공개 사업 자료와 지리 데이터로 그린다. 기본 선택은 해당 연도에
진행되는 KOICA 프로젝트 원조 중 30억원 이상이며, `--include-unselected`로
그 밖의 KOICA 사업도 포함할 수 있다. 실제 사용한 입력 JSON을 산출 폴더의
`inputs/`에 저장한다. 사업 수가 많으면 장소별 묶음을 유지하며 여러 장으로
나누고, 한 장소의 사업만으로 한 장을 넘을 때만 그 묶음을 나눈다.

- **출처 추적:** 사업별 원천 ID·자료 기준일·좌표 출처와 전체 데이터 build ID를
  입력 및 layout JSON에 남긴다. 수집일은 원천 자료의 기준일과 구별한다.
- **위치 신뢰도:** 원천 지도 그룹의 대표좌표는 개별 시설 좌표로 확정하지 않는다.
  사업명에 명시된 도시와 대표위치가 멀리 떨어져 있으면 해당 사업의 마커를 생략하고
  `위치 확인 필요`를 표시한다. 이 검사는 모든 위치 오류를 탐지하는 검증은 아니다.
  공개 자료에서 직접 생성할 때는 과거 수동 지명 사전을 기본으로 사용하지 않는다.
- **지도 표현:** Natural Earth 10m 경계와 geoBoundaries 행정경계, GeoNames 지명,
  OSM/VersaTiles 도로·수계를 조합한다. 기본 `atlas` 스타일은 흰 국토와 선명한
  수계·도로를 사용한다. 타일에 하천 선이 없는 z9 미만에서는 Natural Earth
  수계를 보완한다. 타일 로딩 실패는 경고하고 공개 벡터 자료로 대체한다.
- **범위와 라벨:** 도서국가는 주요 육지와 모든 사업 위치를 포함하는 범위를 계산하고
  필요하면 국가 전체 위치도를 추가한다. 지명은 사업 위치를 우선하며 지도 밖으로
  잘리거나 서로 겹치지 않게 배치한다.
- **글자:** 설치된 맑은 고딕이 있으면 실제 글꼴 폭과 자간으로 줄바꿈을 계산한다.
  `KOICA_FONT`·`KOICA_FONT_BOLD`로 설치 글꼴 경로를 지정할 수 있다. 없으면 근사
  폭을 사용하며 `font_metrics`에 기록한다. PPTX는 PowerPoint에서 최종 확인한다.

`map_density`는 `atlas`(기본, 520 CSS px/in), `city`(650), `standard`(130)를
지원한다. 지도 지물 상세도와 PNG 출력 배율(`--scale`)은 별개다. 생성한 지도가
사람의 위치 검수를 통과했다고 간주하지 않으며, 위치 기여는 별도 검수 후 수행한다.

## 기존 PPTX를 명시적으로 재사용하는 경우

`--reference-template`은 사용자가 기존 지도와 도형을 그대로 재사용하라고 요청한
경우에만 쓰는 별도 기능이다. 범용 지도 생성의 기본 경로가 아니며, 인간 작성본과
유사한 디자인을 요구했다는 이유만으로 이 경로로 바꾸지 않는다.
`reference_pptx.calibrate()`로 로컬 원본의 사업 ID와 텍스트 도형·문단을 연결할 수
있다. 위치·사업 목록·원본이 변경되면 재보정을 요구한다. 원본과 매니페스트는
공개 저장소에 포함하지 않는다. 이 경로는 PPTX만 출력한다.

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
│   ├── reference_pptx.py  로컬 인간 작성 PPTX의 서식·지도·도형 보존 + 사업명 갱신
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

## 초기 샘플 검증 기록 (범용 생성의 품질 보증이 아님)

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

- **oda-map-lab 좌표는 출처에 따라 선별한다.** `국가(폴백)` 좌표만 버리고 지명에서 다시
  풀며, 도시·도시(음차)·IATI 원본(공식좌표)은 그대로 쓴다. 단, 여러 대상지를 한 점으로
  묶은 그룹은 각 지명을 다시 푼다. 지명도 그룹 라벨이라 추정값이어서 `pick_projects.py` 의
  사람 확인이 필수다. 수정 화면에서 지명을 바꾸면 기존 원천 좌표는 자동으로 폐기된다
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

## 종속성 업데이트 자동화

`oda-map-lab`의 CI가 성공하면 전달된 커밋을 다시 체크아웃해 `map-base`와
기여 스키마 계약을 검증하고, 변경된 계약 잠금파일을 PR로 만든다. 매일
실행되는 점검은 이벤트 누락을 보정한다. 허용된 저장소와 검증 경로는
[`.github/dependencies.json`](.github/dependencies.json)에 고정되어 있다.

저장소 관리자는 다음 Actions secret을 등록한다.

- `DEPENDENCY_READ_TOKEN`: `oda-map-lab`의 **Contents: read**만 허용한
  fine-grained personal access token
- `DEPENDENCY_PR_TOKEN`: 이 저장소의 **Contents: write**와
  **Pull requests: write**만 허용한 fine-grained personal access token.
  자동 PR에서도 일반 CI를 시작하기 위해 사용한다.
- `DEPENDENCY_DISPATCH_TOKEN`: `country-report-skill`에
  `repository_dispatch`를 보낼 수 있도록 해당 저장소의 **Contents: write**만
  허용한 fine-grained personal access token

원천 저장소 이벤트와 별개로 Actions의 **Update repository dependencies**
워크플로를 수동 실행할 수 있다.

## 라이선스

[MIT 라이선스](LICENSE)를 따른다.

지도 배경 타일은 [versatiles](https://versatiles.org/)에서 받아 쓰며 OpenStreetMap 기여자의
자료다. 국가·행정경계 등 렌더링에 쓰는 외부 지리 자료는 각 출처의 조건을 그대로 유지한다.
이 저장소가 그 조건을 바꾸지 않는다.

