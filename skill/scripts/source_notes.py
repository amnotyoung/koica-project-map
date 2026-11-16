"""Non-slide credits and evidence for presentations and standalone exports."""

def source_notes(L):
    source = L.get("source", {})
    details = ["지도 자료", "Natural Earth · https://www.naturalearthdata.com/",
               "geoBoundaries (CC BY) · https://www.geoboundaries.org/",
               "GeoNames (CC BY) · https://www.geonames.org/"]
    if L["map"].get("tiles"):
        details.append("VersaTiles · © OpenStreetMap contributors · https://www.openstreetmap.org/copyright")
    if source.get("boundary", "").startswith("Natural Earth"):
        details.append(f"국가 윤곽 · {source['boundary']} Admin 0 Countries (기본 de facto 경계) · https://www.naturalearthdata.com/about/disputed-boundaries-policy/")
    m = L["map"]
    if m.get("extent_basis"):
        basis = {"explicit":"입력에 지정한 범위", "projects":"사업지 집중 지역",
                 "main_landmasses":"주요 육지", "country":"국가 전체"}[m["extent_basis"]]
        details.append(f"도곽 선택 · {basis} · 서·남·동·북 순서 · 국가 도형 {m['country_bbox']} · 지도 맞춤 범위 {[round(v, 5) for v in m['bbox']]}")
    if source.get("projects"):
        details.append(f"사업 자료: {source['projects']}")
    if source.get("retrieved_at"):
        details.append(f"사업 자료 수집일: {source['retrieved_at']}")
    if source.get("build_id"):
        details.append(f"사업 데이터 판본: {source['build_id']}")
    for card in L["cards"]:
        provenance = card.get("provenance", {})
        for entry in provenance.get("_annual_plan", []):
            basis = "확정액" if entry["basis"] == "confirmed" else "요구액"
            details.append(f"{card['text']} · {entry['resolution']} {entry['page']}쪽 · 연간 {basis} {entry['annual_100m_krw']}억 원")
        if card.get("location_note"):
            details.append(f"{card['place']} · {card['text']} · {card['location_note']}")
        if provenance.get("_location_evidence"):
            details.append(f"{card['place']} 사업지 확인 근거 · {provenance['_location_evidence']}")
        for notice in provenance.get("_linked_notices", []):
            details.append(f"{card['text']} · 연결한 공고 {notice['title']} · " + " · ".join(notice["urls"]))
        urls = provenance.get("scope_sources") or []
        if urls:
            details.append(f"{card['place']} — {card['text']}: " + " · ".join(urls))
    park_source = source.get("national_parks") or {}
    if park_source:
        details.append(f"Protected Planet WDPCA, UNEP-WCMC/IUCN · {park_source.get('url','')} ({park_source.get('retrieved','')})")
    return "\n".join(details)
