#!/usr/bin/env python3
"""Lọc 2 tin hot trong 24h từ các báo lớn VN -> caption + hashtag + bình luận -> docs/index.html (xem được trên điện thoại).

Chạy:  ANTHROPIC_API_KEY=... python news_hot.py        (dùng thật)
       python news_hot.py --demo                        (dữ liệu giả, không cần mạng/API)
"""
import os, re, sys, json, html, unicodedata, datetime as dt
from pathlib import Path

# Thứ tự = độ ưu tiên khi chọn link đại diện cho 1 sự kiện. Kiểm tra lại URL RSS nếu báo đổi.
FEEDS = {
    "VnExpress": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "Tuổi Trẻ": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "Thanh Niên": "https://thanhnien.vn/rss/home.rss",
    "Dân Trí": "https://dantri.com.vn/rss/home.rss",
    "VietNamNet": "https://vietnamnet.vn/rss/tin-moi-nhat.rss",
}
HOURS = 24
N_CANDIDATES = 12
N_PICKS = 2
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
OUT = Path("docs")

STOP = set("va cua cho cac nhung mot nay la co trong duoc voi den khi tu nguoi sau truoc se da dang nhu ve the "
           "tai ra len xuong khong bi do nen vi neu thi ma cung rat hon nhat moi".split())


def norm(s):
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def tokens(title):
    return {w for w in re.findall(r"[a-z0-9]+", norm(title)) if len(w) > 2 and w not in STOP}


def fetch_articles():
    import feedparser, requests
    now = dt.datetime.now(dt.timezone.utc)
    arts = []
    for order, (name, url) in enumerate(FEEDS.items()):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            feed = feedparser.parse(r.content)
        except Exception as e:
            print(f"[!] {name}: {e}", file=sys.stderr)
            continue
        n = max(len(feed.entries), 1)
        for i, e in enumerate(feed.entries):
            t = e.get("published_parsed") or e.get("updated_parsed")
            if not t:
                continue
            when = dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
            age = (now - when).total_seconds() / 3600
            if age > HOURS:
                continue
            summ = re.sub(r"<[^>]+>", " ", e.get("summary", ""))
            arts.append(dict(source=name, prio=order, title=e.get("title", "").strip(),
                             link=e.get("link", ""), summary=html.unescape(re.sub(r"\s+", " ", summ)).strip()[:400],
                             age=age, pos=i / n))
        print(f"[ok] {name}: {n} bài", file=sys.stderr)
    return arts


def cluster(arts):
    """Gom các bài cùng sự kiện (tiêu đề giống nhau) từ nhiều báo; càng nhiều báo đưa càng hot."""
    clusters = []
    for a in sorted(arts, key=lambda x: x["age"]):
        a["tok"] = tokens(a["title"])
        for c in clusters:
            inter = len(a["tok"] & c["tok"])
            if inter >= 3 and inter / max(1, min(len(a["tok"]), len(c["tok"]))) >= 0.5:
                c["items"].append(a)
                c["tok"] |= a["tok"]
                break
        else:
            clusters.append(dict(items=[a], tok=set(a["tok"])))
    for c in clusters:
        srcs = {i["source"] for i in c["items"]}
        best = min(i["age"] for i in c["items"])
        prominence = 1 - min(i["pos"] for i in c["items"])
        c["sources"] = sorted(srcs)
        c["score"] = len(srcs) * 10 + prominence * 3 + max(0, 24 - best) / 24 * 2
        c["main"] = min(c["items"], key=lambda i: (i["prio"], i["age"]))
    return sorted(clusters, key=lambda c: -c["score"])[:N_CANDIDATES]


PROMPT = """Bạn là biên tập viên kênh điểm tin ngắn (TikTok/YouTube Shorts/Facebook) bằng tiếng Việt.
Dưới đây là các sự kiện nổi bật trong 24h qua, kèm số báo đưa tin. Chọn đúng {n} sự kiện KHÁC NHAU, dễ làm video 30-60 giây,
có yếu tố gây chú ý. Tránh: chính trị nhạy cảm, tai nạn/thương vong chi tiết, vụ án chưa kết luận, tin chưa xác thực.
Với mỗi sự kiện viết lại HOÀN TOÀN bằng lời của bạn (không chép câu từ bài báo), không thêm thông tin ngoài dữ liệu cung cấp.
Trả về DUY NHẤT JSON: {{"picks":[{{"id":<số>,"hook":"câu mở đầu <=12 chữ","summary":"2-3 câu tóm tắt","comment":"1 câu nhận xét/góc nhìn ngắn, trung lập","hashtags":["#...","#..."]}}]}}
Hashtag: 5-7 cái, tiếng Việt không dấu/có dấu đều được, có 1-2 hashtag chủ đề rộng.

DỮ LIỆU:
{data}
"""


def ask_claude(cands):
    from anthropic import Anthropic
    data = "\n".join(f"[{i}] ({len(c['sources'])} báo: {', '.join(c['sources'])}) {c['main']['title']} — {c['main']['summary']}"
                     for i, c in enumerate(cands))
    msg = Anthropic().messages.create(model=MODEL, max_tokens=1500,
                                      messages=[{"role": "user", "content": PROMPT.format(n=N_PICKS, data=data)}])
    text = msg.content[0].text
    return json.loads(text[text.index("{"): text.rindex("}") + 1])["picks"]


def build_caption(p, c):
    m = c["main"]
    others = [s for s in c["sources"] if s != m["source"]]
    src = f"Nguồn: {m['source']} — {m['link']}" + (f"\nCũng được đưa tin bởi: {', '.join(others)}" if others else "")
    return (f"{p['hook']}\n\n{p['summary']}\n\n💬 {p['comment']}\n\n{src}\n"
            f"(Video do AI tạo, nội dung tổng hợp từ nguồn trên)\n\n{' '.join(p['hashtags'])}")


def render(items, stamp):
    cards = ""
    for i, it in enumerate(items):
        cap = html.escape(it["caption"])
        cards += f"""<section class=card><div class=meta>#{i+1} · {html.escape(', '.join(it['sources']))}</div>
<h2>{html.escape(it['title'])}</h2>
<a class=btn href="{html.escape(it['link'])}" target=_blank rel=noopener>Mở bài báo gốc</a>
<textarea id=t{i} readonly rows=14>{cap}</textarea>
<button class="btn pri" onclick="cp('t{i}',this)">Copy caption</button>
<button class=btn onclick="cp('l{i}',this)">Copy link</button>
<input id=l{i} value="{html.escape(it['link'])}" readonly hidden></section>"""
    return f"""<!doctype html><html lang=vi><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Tin hot {stamp}</title>
<style>:root{{color-scheme:light dark;--bg:#f5f5f7;--c:#fff;--t:#111;--m:#666;--a:#c8102e}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111;--c:#1c1c1e;--t:#eee;--m:#999}}}}
body{{margin:0;padding:12px;background:var(--bg);color:var(--t);font:16px/1.45 system-ui,sans-serif}}
h1{{font-size:18px;margin:4px 4px 12px}}.card{{background:var(--c);border-radius:14px;padding:14px;margin-bottom:14px}}
.meta{{color:var(--m);font-size:13px}}h2{{font-size:18px;margin:6px 0 10px}}
textarea{{width:100%;box-sizing:border-box;font:inherit;font-size:15px;padding:10px;border-radius:10px;border:1px solid #8884;background:transparent;color:inherit;margin:10px 0}}
.btn{{display:inline-block;padding:10px 14px;border-radius:10px;border:1px solid #8885;background:transparent;color:inherit;font:inherit;text-decoration:none;margin-right:6px}}
.pri{{background:var(--a);border-color:var(--a);color:#fff}}</style></head><body>
<h1>Tin hot · {stamp}</h1>{cards}
<script>function cp(id,b){{var e=document.getElementById(id),v=e.value;
(navigator.clipboard?navigator.clipboard.writeText(v):Promise.reject()).catch(function(){{e.hidden=false;e.select();document.execCommand('copy')}}).then(function(){{var o=b.textContent;b.textContent='Đã copy ✓';setTimeout(function(){{b.textContent=o}},1500)}})}}</script>
</body></html>"""


DEMO = [
    dict(source="VnExpress", prio=0, title="Nvidia công bố CEO tạm quyền sau khi ông Huang từ chức", link="https://example.com/a1",
         summary="Demo.", age=3, pos=0.0),
    dict(source="Tuổi Trẻ", prio=1, title="CEO Nvidia từ chức, bà Kress giữ chức tạm quyền", link="https://example.com/a2",
         summary="Demo.", age=4, pos=0.1),
    dict(source="Dân Trí", prio=3, title="Giá vàng trong nước tăng mạnh phiên sáng nay", link="https://example.com/b1",
         summary="Demo.", age=2, pos=0.2),
]


def main():
    demo = "--demo" in sys.argv
    arts = DEMO if demo else fetch_articles()
    cands = cluster(arts)
    if not cands:
        sys.exit("Không có bài nào trong 24h (kiểm tra RSS/mạng).")
    if demo or not os.getenv("ANTHROPIC_API_KEY"):
        picks = [dict(id=i, hook=c["main"]["title"], summary=c["main"]["summary"], comment="(chưa có API key nên chưa có bình luận)",
                      hashtags=["#tinhot"]) for i, c in enumerate(cands[:N_PICKS])]
    else:
        picks = ask_claude(cands)[:N_PICKS]
    items = []
    for p in picks:
        c = cands[int(p["id"])]
        items.append(dict(title=c["main"]["title"], link=c["main"]["link"], sources=c["sources"], caption=build_caption(p, c)))
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).strftime("%d/%m/%Y")
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(render(items, stamp), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Xong: {OUT/'index.html'}")


if __name__ == "__main__":
    main()
