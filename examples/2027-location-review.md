# 2027년 사업지 미확정 216건 재점검

2026년 11월 16일. 직전 준비 목록의 52개국 미확정 활동 216건을 대상으로 했다. 사업명·기간·금액·선정 상태는 기존 편집 입력을 사용했다. 인간 작성본이나 국가별 정답표는 입력에 사용하지 않았다.

## 누락 원인

- 199건은 KOICA IATI에 보고 지명이 한 곳, 17건은 보고 지명이 없었다. 199건의 위치 식별자는 모두 국가 코드였고, 131건은 같은 국가의 다른 미확정 사업과 보고 지명도 같았다. 사업지 판독에 지명 한 칸과 좌표만 사용하면 수도에 몰리는 문제가 생긴다.
- 국문 제목에 대학·병원·센터·학교·연구소·공항·시험소가 나오는 사업이 35건이었다. 기존 로직은 도시와 행정구역을 검색하고 별도 등록한 수혜기관만 인식했다. 이번 규칙은 국가별 GeoNames 시설 파일에서 이름과 별칭이 고유한 기존 시설을 찾아 사업명·본문의 교육·설치·개선 대상인지 대조한다. 신규 시설의 주소를 특정할 수 없는 경우 도시까지 확인하는 경로도 분리했다.
- 정보시스템·플랫폼·행정·디지털을 언급한 제목은 28건이고 지역사회·농촌·농가·취약계층 또는 복수 주·지역을 언급한 제목은 23건이었다. 앞의 제목 집계는 서로 겹친다. 중앙부처 소재지나 참여 기관 수로 실제 적용 지역을 판정하기 어려운 사업이 남는다.
- 같은 활동 ID에 이미 기재된 가나의 전년도 권역 4건이 해당 연도 조건에서 제외됐다. 2건은 현재 단계의 지역 범위를 다시 확인했다. 다른 2건은 단계 간 지역 차이와 참여기관 과업기간 차이 때문에 2027년 권역을 그대로 승계하기 어려웠다.

## 미시험 국가 적용 결과

| 구분 | 적용 국가 | 기존 미확정 | 최종 반영 | 남은 미확정 |
|---|---|---:|---:|---:|
| 1차 시험 및 보정 | 페루·키르기스스탄·우간다·우크라이나·이집트·코트디부아르·콜롬비아·팔레스타인·튀니지 | 54 | 4 | 50 |
| 보정 후 별도 시험 | 카메룬·볼리비아·타지키스탄·나이지리아·미얀마·세네갈·요르단·이라크·이란·도미니카공화국 | 33 | 0 | 33 |
| 나머지 국가 | 기존 생성 입력 중 미확정 활동 | 129 | 4 | 125 |
| **전체** | **52개국** | **216** | **8** | **208** |

첫 9개국에서 최초 시도한 신규 규칙만으로 추가된 위치는 0건이었다. 기존 규칙을 같은 입력에 재실행하면 페루 사업의 국문 제목 ‘쿠스코시’와 보고 지명으로 시 대표점이 생겼다. 영문 제목은 ‘Province of Cusco’다. 이 사례를 반영해 같은 지명의 행정단계가 충돌하면 지점과 권역을 모두 보류했다. 이후 시설명 어순·별칭과 사업 대상 문맥을 보완해 같은 9개국에서 4건이 반영됐다. 별도 10개국은 해당 보정에 사용하지 않았다.

## 반영된 핀과 권역

국·영문 배치에서 아래 여덟 활동의 경위도와 행정경계 ID를 각각 검사했다. 시설 대표점은 캠퍼스 또는 공항 위치다. 도시 대표점은 설치 부지의 좌표를 뜻하지 않는다. 가나의 권역은 참여지역이 속한 주 경계로 표시했다.

| 국가·사업 | 반영 및 근거 |
|---|---|
| 우간다 마케레레대 ICT 교육 | 마케레레대 캠퍼스 대표점. 대학의 사업 설명과 캠퍼스 내 기관의 위치를 대조했다. [대학 사업 설명](https://cocis.mak.ac.ug/wp-content/uploads/2026/02/Day1-Makerere-76th-Grad-Vice-Chancellors-Address.pdf) · [캠퍼스 소재 기관](https://renu.ac.ug/wp-content/uploads/2024/01/RENU-Newsletter-and-Annual-Report-2018.pdf) |
| 우크라이나 보리스필공항 현대화 | 키이우 시내 대신 보리스필 국제공항 대표점. 운영사의 사업 발표 및 공항 기준점과 대조했다. [사업 발표](https://kbp.aero/en/news/preparatory-stage-comprehensive-modernization-cooperation-korea-international-cooperation-agency-koica-launched-boryspil-international-airport/) · [공항 기준점](https://kbp.aero/wp-content/uploads/2023/11/PRAVYLA-gosp.dyaln-rev.-03.pdf) |
| 코트디부아르 펠릭스 우푸에부아니대 ICT | 코코디 캠퍼스 대표점. 프랑스어 시설명과 영문 사업명의 고유명사를 연결했다. [정부 사업 발표](https://www.gouv.ci/index.php/actualite/renforcement-des-tics-et-du-digital-a-luniversite-felix-houphouet-boigny-un-accord-de-59-milliards-fcfa-signe-entre-les-gouvernements-ivoirien-et-coreen-2428) · [대학 위치](https://islam.zmo.de/s/westafrica/item/558) |
| 콜롬비아 조선·해양산업 기술센터 | 카르타헤나 도시 대표점. 시청 발표에서 센터의 대상 도시를 확인했다. [카르타헤나 시청](https://www.cartagena.gov.co/noticias/corea-invertiria-12-millones-dolares-proyecto-gobierno-alcalde-dumek-turbay-para-construir-el-primer-centro-tecnologia-innovacion-para-industria-metalmecanica) |
| 가나대 연구·ICT 혁신센터 | 레곤 캠퍼스 대표점. 대학이 착공 장소를 명시한다. [가나대학교](https://www.ug.edu.gh/node/1109) |
| 파키스탄 물탄시 홍수방재 | 물탄 도시 대표점. 기존 도시 규칙을 재실행해 회수된 1건이다. [파키스탄 수도사업자 협의체](https://pwon.pk/wp-content/uploads/2026/05/PWON-Newsletter-2025.pdf?pid=6985) |
| 가나 모자·청소년보건 네트워크 | 아샨티·이스턴·센트럴 3개 주의 참여 지역. 보건청이 발표한 현장과 UNICEF 해당 단계의 기간을 확인했다. [가나 보건청](https://www.ghs.gov.gh/news-and-events/ghs-receives-three-toyota-hilux-pickups-to-strengthen-rmncahn-services) · [UNICEF](https://www.unicef.org/gok/contributions-and-impact/ghana) |
| 가나 농산업 가치사슬 | 센트럴·볼타 2개 주의 참여 지역. 협의의사록 체결 발표와 일치한다. [가나 국가개발계획위원회](https://ndpc.gov.gh/media_center/blog_details/koica-and-ndpc-sign-record-discussion-boost-agribusiness-value-chains-ghana) |

확인한 8건에서 대상지가 다른 핀이나 잘못된 주 경계는 발견되지 않았다. 반영되지 않은 사업은 이번 수치에서 제외했다. 예를 들어 콜롬비아 메데인 폐기물 사업은 원천 지명 하나와 달리 최근 서명 자료에 메데인·돈마티아스 두 지자체가 나오고 사업기간도 달라, 단일 도시 핀으로 승격하지 않았다. [콜롬비아 대통령실 국제협력청](https://www.apccolombia.gov.co/node/4932)

전체 선정 목록은 385건이며 기존 대표좌표 근거 검토 대상은 별도로 31건이다. 이번 결과물은 국가별 입력 JSON과 편집 화면, 대조 CSV다. 전체 PPT 시각 검수는 생성 단계에서 진행한다.
