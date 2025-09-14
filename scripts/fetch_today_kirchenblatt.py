# -*- coding: utf-8 -*-
import io, os, re, json, pdfplumber, requests, dateparser
from datetime import datetime
from zoneinfo import ZoneInfo

# 时区
TZ = ZoneInfo("Europe/Zurich")

# 先用你提供过的 Solothurn 期刊（后续可替换为最新一期 URL 或列表）
URLS = [
    "https://www.kirchenblatt.ch/assets/Kirchenblatt/kib-1925-solothurn.pdf",
]

OUT = "public/api/today.json"

# 星期、日期、时间的粗解析（Kirchenblatt 常见格式）
WEEKDAYS = ["Mo","Di","Mi","Do","Fr","Sa","So",
            "Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
TIME_RE = r"(?P<h>\d{1,2})[.:](?P<m>\d{2})(?:\s*Uhr)?"
DATE_RE = r"(?P<d>\d{1,2})[.\s](?:(?P<mon>\d{1,2})[.]|(?P<mon_name>[A-Za-zäöüÄÖÜ]+))\.?\s*(?P<y>\d{4})?"
LINE_RE = re.compile(rf"(?P<wd>{'|'.join(WEEKDAYS)})\s+{DATE_RE}\s+{TIME_RE}\s+(?P<after>.+)$")

# 只保留弥撒类关键词
MESSE_KEYWORDS = re.compile(r"\b(Messe|Hl\.\s*Messe|Eucharistiefeier)\b", re.I)

# 地点归一（先放几个，后面可以补）
PLACE_NORMALIZE = {
    r"\bKathedrale\s*St\.?\s*Urs(en)?\b": "Kathedrale St. Ursen, Solothurn",
    r"\bSt\.?\s*Marien\b": "St. Marien, Solothurn",
    r"\bSt\.?\s*Niklaus\b": "St. Niklaus, Solothurn",
    r"\bSt\.?\s*Eusebius\b": "St. Eusebius, Grenchen",
    r"\bSt\.?\s*Klem(e)?nz\b": "St. Klemenz, Bettlach",
}

def _norm(t: str) -> str:
    t = t.replace("\u00ad","")       # 软连字符
    t = re.sub(r"-\n","", t)         # 行尾连字断行
    t = re.sub(r"[ \t]+"," ", t)
    return t

def _text_from_pdf(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return _norm("\n".join((p.extract_text() or "") for p in pdf.pages))

def _year_hint(text: str) -> int:
    ys = re.findall(r"\b(20\d{2})\b", text)
    return int(ys[0]) if ys else datetime.now(TZ).year

def _parse_date(d, mon, mon_name, y, yh):
    # 兼容“13. Sep 2025”或“13.09.2025/13.09.”
    if mon_name:
        s = f"{d}. {mon_name} {y or yh}"
    else:
        s = f"{d}.{mon or ''}.{y or yh}"
    return dateparser.parse(s, languages=["de"], settings={"TIMEZONE":"Europe/Zurich"})

def _split_title_place(after: str):
    # 从尾部抓地点关键词片段
    m = re.search(r"(Kathedrale|Kirche|Kapelle|St\.\s[\wÄÖÜäöüß.\- ]+)[^,]*", after)
    if m:
        place = after[m.start():].strip(" )")
        title = after[:m.start()].strip(" -–,")
        return (title or "Messe"), place
    return after.strip(), None

def _normalize_place(s: str | None) -> str | None:
    if not s: return s
    out = s
    for pat, repl in PLACE_NORMALIZE.items():
        out = re.sub(pat, repl, out, flags=re.I)
    return out

def main():
    os.makedirs("public/api", exist_ok=True)

    # 抓取所有 URL 的文本拼一起（Kirchenblatt 各块儿可能跨页）
    all_text = ""
    for u in URLS:
        try:
            r = requests.get(u, timeout=30)
            r.raise_for_status()
            all_text += "\n" + _text_from_pdf(r.content)
        except Exception as e:
            print("Fetch error:", u, e)

    yh = _year_hint(all_text)

    today = datetime.now(TZ).date()
    start = datetime(today.year, today.month, today.day, 0, 0, tzinfo=TZ)
    end   = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=TZ)

    items = []
    for raw in all_text.splitlines():
        line = raw.strip()
        if not line: 
            continue
        m = LINE_RE.search(line)
        if not m: 
            continue

        gd = m.groupdict()
        dt = _parse_date(gd["d"], gd.get("mon"), gd.get("mon_name"), gd.get("y"), yh)
        if not dt:
            continue
        hh, mm = int(gd["h"]), int(gd["m"])
        when = datetime(dt.year, dt.month, dt.day, hh, mm, tzinfo=TZ)

        if not (start <= when <= end):
            continue

        title, place = _split_title_place(gd["after"])
        # 标题或尾部有 Messe 关键词才保留
        if not (MESSE_KEYWORDS.search(title) or MESSE_KEYWORDS.search(gd["after"])):
            continue

        place = _normalize_place(place)

        items.append({
            "title": title or "Messe",
            "start": when.isoformat(),
            "location": place,
            "kanton": "SO",
            "source": "kirchenblatt"
        })

    items.sort(key=lambda x: x["start"])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(items)} items -> {OUT}")

if __name__ == "__main__":
    main()
