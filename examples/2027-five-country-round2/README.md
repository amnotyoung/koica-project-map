# 2027년 프로젝트맵 5개국 대조

2026년 11월 12일 기준 공개 원천으로 선정한 30개 사업이다. 담당자가 공고 후보의 포함 여부와 미확인 사업지를 추가 검토할 수 있다. 각 JSON에 사업 식별자, 국·영문 표기와 사업별 공개 근거가 있다.

| 국가 | 인간 작성본 슬라이드 | 원본 사업 | 첫 생성 | 수정 후 | 원본과 남은 차이 |
|---|---|---:|---:|---:|---|
| 몽골 | 14–15 | 15 | 4 | 9 | 원본의 2026년 종료 표기 4건, 관세·국토균형개발·녹색혁신연구소 3건이 이번 명부에 없다. 가스안전관리 1건은 공개 자료에서 추가됐다. |
| 라오스 | 10–11 | 17 | 8 | 11 | 원본에 2026년 종료 표기 5건과 2027년 신규 불발탄 사업이 더 있다. 불발탄 사업은 공고 검토 대상으로 두었다. |
| 말라위 | 45–46 | 1 | 1 | 1 | UNFPA가 명시한 데자·음친지 두 군의 경계를 함께 그렸다. |
| 엘살바도르 | 94–95 | 7 | 1 | 4 | 원본에 2026년 종료 표기 4건이 더 있다. 공개 IATI에서 확인한 건조회랑 원예 삼각협력 1건을 포함했다. |
| 파라과이 | 106–107 | 9 | 4 | 5 | 원본에 2025·2026년 종료 표기 3건과 국가건강검진 계획·시범사업이 더 있다. 원본 밖 멀티미디어 교육사업은 제목과 기간 필드가 달라 편집기의 기간 확인 대상으로 옮겼다. |

대조한 원본은 사용자가 제공한 「★ (업뎃) 2027년 KOICA 국별협력사업 프로젝트 맵_260702」이다. 원본에 적힌 종료연도는 위 표에서 원본과의 차이를 설명하는 데 사용했다. 원본의 지명이나 좌표는 지도 입력으로 전사하지 않았다.

## 공개 자료에 따른 차이

- 라오스 폐기물·하수처리 사업은 시행기관이 2023년 10월부터 2028년 6월까지로 공시했다. 국·영문에 같은 기간과 1,050만 달러를 표시하고 네 도시를 지도에 표시했다. [GGGI 사업 정보](https://gggi.org/project/scaling-out-sustainable-solid-waste-and-wastewater-management-in-lao-pdr-phase-ii/)
- 말라위 사업의 분야와 두 군 범위는 기금 협약 발표에서 확인했다. [UNFPA 발표](https://malawi.unfpa.org/en/news/koica-commits-usd-74-million-unfpa-and-government-malawi-empower-adolescent-girls-and-teen)
- 몽골 여성·청년 참여, 엘살바도르 산학협력, 파라과이 치과대학병원은 각 시행기관 발표와 IATI 활동을 연결했다. [UNDP Mongolia](https://www.undp.org/mongolia/press-releases/undp-and-koica-launch-second-phase-partnership-advance-womens-and-youth-leadership-mongolia) · [엘살바도르대학교](https://www.ues.edu.sv/ues-inicia-proyecto-de-innovacion-tecnologica/) · [아순시온 국립대학교](https://www.una.py/la-una-founa-y-koica-gestionan-un-moderno-hospital-odontologico-y-fortalecer-la-salud-bucodental-en-paraguay)
- 원전에서 시설명만 확인되는 사업은 카드에 시설을 적었다. 농가·학교·진료소의 개별 좌표를 확인할 수 없는 경우에는 핀을 생략했다. 원예 삼각협력 IATI 원문에 실린 좌표는 엘살바도르 밖이다. [KOICA IATI XML](https://www.odakorea.go.kr/opm/iati_act_KR-GOV-051.xml)
- 파라과이 원예사업은 시행기관 발표에 명시된 센트랄·카아과수·코르디예라·파라과리 4개 주 경계를 표시했다. [파라과이 정부 발표](https://www.ip.gov.py/ip/2026/05/07/organizaciones-productivas-podran-postularse-a-convocatoria-que-apunta-a-la-competitividad-con-financiamiento/)

## 재생성

저장소 최상위 폴더에서 다음 명령을 실행한다. 국가 순서와 판형을 지정해야 같은 순서로 10장이 나온다.

```sh
skill/.venv/bin/python skill/scripts/make_map.py \
  --input examples/2027-five-country-round2/{mongolia,laos,malawi,el-salvador,paraguay}.json \
  --outdir output/five-country-2027-round2/replay --formats pptx --detail 10m --page-format atlas-full
```
