"""Index KOICA regional programme tables from committee PDFs (requires pdfplumber)."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import pdfplumber


def extract(path, first_page, last_page):
    rows = []
    with pdfplumber.open(path) as document:
        for page in document.pages[first_page - 1:last_page]:
            for table in page.extract_tables():
                for cells in table:
                    if len(cells) != 9:
                        continue
                    _, group, title, kind, total, annual, status, period, _ = (c or "" for c in cells)
                    group = re.sub(r"\s+", "", group)
                    if not re.match(r"\[4\d{2}\]", group) or re.sub(r"\s+", "", kind) not in {"프로젝트", "프로그램"}:
                        continue
                    period = re.sub(r"\s+", "", period)
                    if not re.fullmatch(r"20\d\d[-~]20\d\d", period) or not title:
                        continue
                    rows.append({"page":page.page_number, "account":group, "title":" ".join(title.split()), "period":period.replace("~","-"),
                                 "annual_100m_krw":annual.strip(), "status":status.strip()})
            page.close()
    if not rows:
        raise ValueError(f"사업 표를 읽지 못했습니다: {path}")
    return rows


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("pdf", type=Path)
    cli.add_argument("out", type=Path)
    cli.add_argument("--year", type=int, required=True)
    cli.add_argument("--basis", choices=["confirmed","requested"], required=True)
    cli.add_argument("--resolution", required=True)
    cli.add_argument("--pages", nargs=2, type=int, required=True, metavar=("FIRST","LAST"), help="KOICA country accounts, physical PDF pages")
    args = cli.parse_args()
    doc = {"year":args.year, "basis":args.basis, "resolution":args.resolution,
           "source":"https://www.odakorea.go.kr/kor/bbs/PlanAndResulList?bbs_id=kor_001",
           "sha256":hashlib.sha256(args.pdf.read_bytes()).hexdigest(), "projects":extract(args.pdf, *args.pages)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.year, len(doc["projects"]))
