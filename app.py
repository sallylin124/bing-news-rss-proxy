from flask import Flask, request, Response
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import requests
import urllib.parse
import xml.etree.ElementTree as ET
import threading
import time
import re

app = Flask(__name__)

# ===== 快取機制 =====
cache = {}
CACHE_TTL_MINUTES = 30


def get_cached(keyword):
    key = keyword.lower().strip()
    if key in cache:
        data, timestamp = cache[key]
        if datetime.utcnow() - timestamp < timedelta(minutes=CACHE_TTL_MINUTES):
            return data
        else:
            del cache[key]
    return None


def set_cache(keyword, data):
    key = keyword.lower().strip()
    cache[key] = (data, datetime.utcnow())


# ===== 預熱 =====
def warmup():
    time.sleep(5)
    for kw in ["NVIDIA", "AI", "Microsoft", "TSMC"]:
        try:
            fetch_bing_news(kw)
            print(f"[Warmup] Cached: {kw}")
        except Exception as e:
            print(f"[Warmup] Failed: {kw} - {e}")

warmup_thread = threading.Thread(target=warmup, daemon=True)
warmup_thread.start()


# ===== 中英文對照表 =====
KEYWORD_FALLBACKS = {
    "台積電": ["TSMC", "台積電"],
    "輝達": ["NVIDIA", "輝達"],
    "黃仁勳": ["Jensen Huang", "黃仁勳", "NVIDIA"],
    "超微": ["AMD", "超微"],
    "英特爾": ["Intel", "英特爾"],
    "三星": ["Samsung", "三星"],
    "蘋果": ["Apple", "蘋果"],
    "微軟": ["Microsoft", "微軟"],
    "特斯拉": ["Tesla", "特斯拉"],
    "聯發科": ["MediaTek", "聯發科"],
    "高通": ["Qualcomm", "高通"],
    "半導體": ["semiconductor", "半導體"],
    "人工智慧": ["AI", "人工智慧"],
    "電動車": ["EV", "electric vehicle"],
    "量子電腦": ["quantum computer", "量子電腦"],
    "機器人": ["robot", "機器人"],
}


def get_search_keywords(keyword):
    """取得搜尋關鍵字列表（含 fallback）"""
    keywords = [keyword]
    # 檢查是否有 fallback
    for key, fallbacks in KEYWORD_FALLBACKS.items():
        if key in keyword or keyword.lower() in [f.lower() for f in fallbacks]:
            for fb in fallbacks:
                if fb.lower() != keyword.lower() and fb not in keywords:
                    keywords.append(fb)
            break
    return keywords


def try_rss_format(keyword):
    """嘗試用 format=rss 取得 RSS XML"""
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.bing.com/news/search?q={encoded}&format=rss"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    }

    resp = requests.get(url, headers=headers, timeout=15)
    content_type = resp.headers.get("Content-Type", "")

    if "xml" in content_type or resp.text.strip().startswith("<?xml"):
        # 確認 XML 裡面有 item
        if "<item>" in resp.text:
            return resp.text
    return None


def try_html_scrape(keyword):
    """用 HTML 解析方式取得新聞"""
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.bing.com/news/search?q={encoded}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    resp = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []

    news_cards = (
        soup.select("div.news-card") or
        soup.select("div.newsitem") or
        soup.select("article") or
        soup.select("div.card-with-cluster") or
        soup.select("div.t_t")
    )

    for card in news_cards[:20]:
        title_tag = (
            card.select_one("a.title") or
            card.select_one("h2 a") or
            card.select_one("h3 a") or
            card.select_one("a")
        )
        snippet_tag = (
            card.select_one("div.snippet") or
            card.select_one("p")
        )
        source_tag = card.select_one("div.source")

        if title_tag:
            title = title_tag.get_text(strip=True)
            link = title_tag.get("href", "")
            if link.startswith("/"):
                link = "https://www.bing.com" + link
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            source = source_tag.get_text(strip=True) if source_tag else ""

            if title and link and len(title) > 5:
                articles.append({
                    "title": title,
                    "link": link,
                    "description": f"[{source}] {snippet}" if source else snippet,
                })

    return articles


def fetch_bing_news(keyword, max_results=20):
    """搜尋 Bing News，支援多關鍵字 fallback"""
    # 檢查快取
    cached = get_cached(keyword)
    if cached:
        return cached

    # 取得搜尋關鍵字列表
    search_keywords = get_search_keywords(keyword)
    all_articles = []

    for kw in search_keywords:
        # 方法 1：嘗試 RSS 格式
        rss_result = try_rss_format(kw)
        if rss_result:
            set_cache(keyword, rss_result)
            return rss_result

        # 方法 2：HTML 解析
        articles = try_html_scrape(kw)
        for a in articles:
            if a not in all_articles:
                all_articles.append(a)

        if len(all_articles) >= max_results:
            break

    # 產生 RSS XML
    rss_xml = generate_rss_xml(keyword, all_articles[:max_results])
    if all_articles:
        set_cache(keyword, rss_xml)
    return rss_xml


def generate_rss_xml(keyword, articles):
    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = f"Bing News - {keyword}"
    ET.SubElement(channel, "link").text = (
        f"https://www.bing.com/news/search?q={urllib.parse.quote(keyword)}"
    )
    ET.SubElement(channel, "description").text = (
        f"Bing News search results for: {keyword}"
    )
    ET.SubElement(channel, "language").text = "zh-TW"
    ET.SubElement(channel, "lastBuildDate").text = now

    for article in articles:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article.get("title", "")
        ET.SubElement(item, "link").text = article.get("link", "")
        ET.SubElement(item, "description").text = article.get("description", "")
        ET.SubElement(item, "pubDate").text = now

    xml_str = '''<?xml version="1.0" encoding="UTF-8"?>\n'''
    xml_str += ET.tostring(rss, encoding="unicode", method="xml")
    return xml_str


@app.route("/rss")
def rss_proxy():
    keyword = request.args.get("q", "")
    max_results = int(request.args.get("max", "20"))

    if not keyword:
        return Response(
            "<error>Missing parameter: q</error>",
            status_code=400,
            mimetype="application/xml"
        )

    try:
        result = fetch_bing_news(keyword, max_results)
        return Response(result, mimetype="application/rss+xml")
    except Exception as e:
        error_rss = generate_rss_xml(keyword, [{
            "title": f"Search error: {str(e)}",
            "link": f"https://www.bing.com/news/search?q={urllib.parse.quote(keyword)}",
            "description": str(e)
        }])
        return Response(error_rss, mimetype="application/rss+xml")


@app.route("/health")
def health():
    return "OK"


@app.route("/")
def home():
    cached_keywords = list(cache.keys())
    cached_html = "".join([f"<li>{k}</li>" for k in cached_keywords]) if cached_keywords else "<li>None</li>"

    return f"""
    <h1>Bing News RSS Proxy V3</h1>
    <p>Usage: <code>/rss?q=KEYWORD</code></p>
    <h3>Features:</h3>
    <ul>
        <li>Chinese keyword fallback (e.g. 台積電 → TSMC)</li>
        <li>Cache (30 min TTL)</li>
        <li>RSS format + HTML scrape fallback</li>
    </ul>
    <h3>Examples:</h3>
    <ul>
        <li><a href="/rss?q=NVIDIA">/rss?q=NVIDIA</a></li>
        <li><a href="/rss?q=N1X">/rss?q=N1X</a></li>
        <li><a href="/rss?q=%E5%8F%B0%E7%A9%8D%E9%9B%BB">/rss?q=台積電</a></li>
        <li><a href="/rss?q=%E9%BB%83%E4%BB%81%E5%8B%B3">/rss?q=黃仁勳</a></li>
        <li><a href="/rss?q=%E5%8D%8A%E5%B0%8E%E9%AB%94">/rss?q=半導體</a></li>
    </ul>
    <h3>Cached keywords:</h3>
    <ul>{cached_html}</ul>
    <p>Cache TTL: {CACHE_TTL_MINUTES} minutes</p>
    <p>Powered by CADI Report Delivery Agent - V3</p>
    """


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
