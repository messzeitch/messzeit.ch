# -*- coding: utf-8 -*-
import re
import json
import requests
import pdfplumber
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import tz

ARCHIVE_URL = "https://www.kirchenblatt.ch/links/archiv"
OUT_FILE = "public/api/today.json"

# 关键词（德语常见写法）
KEYWORDS = [
    "Messe",
    "Hl. Messe",
    "Eucharistiefeier",
    "Eucharistie",
    "Gottesdienst",
]

# 可能出现的时间格式：09:30  /  9:30  /  09.30  /  9.30
TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:\.][0-5]\d\b")

def get_latest_pdf_url():
    """从归档页抓取最新一期 PDF 的绝对地址"""
    r = requests.get(ARCHIVE_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    # 策略：找第一个以 .pdf 结尾的链接；若有地区分支，可在这里加过滤条件
    # 例如：如果页面上含“Solothurn”字样的 a 标签才要 -> if "Solothurn" in a.get_text():
    for a in soup.select("a[href$='.pdf']"):
        href = a.get("href", "").strip()
        if not href:
            continue
        # 处理相对路径
        if href.startswith("/"):
            pdf_url = "https://www.kirchenblatt.ch" + href
        elif href.startswith("http"):
            pdf_url = href
        else:
            pdf_url = "https://www.kirchenblatt.ch/" + href
        return pdf_url

    raise RuntimeError("未在归档页找到 PDF 链接")

def download_pdf(url, path="tmp_kirchenblatt.pdf"):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    return path

def parse_today_from_pdf(pdf_path):
    """
    非严格解析：提取包含关键词+时间的行，作为候选项。
    你后续可以按堂区名/日期做更精细的正则或版面定位。
    """
    today = datetime.now(tz=tz.gettz("Europe/Zurich")).date()
    items = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            # 按行扫
            for raw_line in text.splitlines():
                line = " ".join(raw_line.split())  # 规整空白
                if any(k.lower() in line.lower() for k in KEYWORDS) and TIME_RE.search(line):
                    items.append({
                        "page": page_num,
                        "line": line,
                    })

    return {
        "date": today.isoformat(),
        "source": "Kirchenblatt",
        "archive_url": ARCHIVE_URL,
        "items": items
    }

def main():
    pdf_url = get_latest_pdf_url()
    pdf_path = download_pdf(pdf_url)
    data = parse_today_from_pdf(pdf_path)
    data["pdf_url"] = pdf_url

    # 确保输出目录存在（交给 workflow 的 mkdir -p；脚本里也兜底）
    import os
    os.makedirs("public/api", exist_ok=True)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] Wrote {OUT_FILE} with {len(data['items'])} items")

if __name__ == "__main__":
    main()
