"""Non-slide credits and evidence for presentations and standalone exports."""

def source_notes(L):
    source = L.get("source", {})
    details = ["지도 자료", "Natural Earth · https://www.naturalearthdata.com/",
               "geoBoundaries (CC BY) · https://www.geoboundaries.org/",
               "GeoNames (CC BY) · https://www.geonames.org/"]
    if L["map"].get("tiles"):
        details.append("VersaTiles · © OpenStreetMap contributors · https://www.openstreetmap.org/copyright")
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
