from flask import Flask, request, Response
from bs4 import BeautifulSoup
from datetime import datetime
import requests
import urllib.parse
import xml.etree.ElementTree as ET

app = Flask(__name__)


@app.route("/rss")
def rss_proxy():
    """
    Bing News RSS Proxy
    Usage: GET /rss?q=NVIDIA
    """
    keyword = request.args.get("q", "")
    max_results = int(request.args.get("max", "20"))

    if not keyword:
        return Response(
            "<error>Missing parameter: q</error>",
            status_code=400,
            mimetype="application/xml"
        )

    try:
        # 1. 打 Bing News
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

        # 2. 檢查是否直接回傳 RSS XML
        content_type = resp.headers.get("Content-Type", "")

        if "xml" in content_type or resp.text.strip().startswith("<?xml"):
            return Response(resp.text, mimetype="application/rss+xml")

        # 3. 如果回傳 HTML，解析它
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []

        # 嘗試多種 selector
        news_cards = (
            soup.select("div.news-card") or
            soup.select("div.newsitem") or
            soup.select("article") or
            soup.select("div.card-with-cluster") or
            soup.select("div.t_t")
        )

        for card in news_cards[:max_results]:
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

                if title and link:
                    articles.append({
                        "title": title,
                        "link": link,
                        "description": f"[{source}] {snippet}" if source else snippet,
                    })

        # 4. 備用 selector
        if not articles:
            for a_tag in soup.select("a[href]"):
                href = a_tag.get("href", "")
                text = a_tag.get_text(strip=True)
                if (text and len(text) > 15 and
                    "bing.com/news" not in href and
                    not href.startswith("#") and
                    not href.startswith("javascript")):
                    if href.startswith("/"):
                        href = "https://www.bing.com" + href
                    articles.append({
                        "title": text,
                        "link": href,
                        "description": "",
                    })
                    if len(articles) >= max_results:
                        break

        # 5. 產生 RSS XML
        rss_xml = generate_rss_xml(keyword, articles)
        return Response(rss_xml, mimetype="application/rss+xml")

    except Exception as e:
        error_rss = generate_rss_xml(keyword, [{
            "title": f"Search error: {str(e)}",
            "link": f"https://www.bing.com/news/search?q={encoded}",
            "description": str(e)
        }])
        return Response(error_rss, mimetype="application/rss+xml")


def generate_rss_xml(keyword, articles):
    """Generate standard RSS 2.0 XML"""
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

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += ET.tostring(rss, encoding="unicode", method="xml")
    return xml_str


@app.route("/")
def home():
    return """
    <h1>Bing News RSS Proxy</h1>
    <p>Usage: <code>/rss?q=KEYWORD</code></p>
    <h3>Examples:</h3>
    <ul>
        <li><a href="/rss?q=NVIDIA">/rss?q=NVIDIA</a></li>
        <li><a href="/rss?q=N1X">/rss?q=N1X</a></li>
        <li><a href="/rss?q=AI">/rss?q=AI</a></li>
    </ul>
    <p>Powered by CADI Report Delivery Agent</p>
    """


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
