"""
Morning Study — generates the daily briefing and publishes it as a static web page.

Runs automatically via GitHub Actions. Writes:
  docs/index.html           - today's briefing (your morning URL)
  docs/archive/<date>.html  - every past briefing
Requires one secret: ANTHROPIC_API_KEY
"""

import html
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import anthropic
import markdown as md

MODEL = "claude-sonnet-4-6"
ROOT = Path(__file__).parent
QUEUE_FILE = ROOT / "queue.json"
DOCS = ROOT / "docs"
ARCHIVE = DOCS / "archive"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>The Morning Study — {date}</title>
<link href="https://fonts.googleapis.com/css2?family=Young+Serif&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=Fragment+Mono&display=swap" rel="stylesheet">
<style>
  :root {{ --ink:#202B38; --paper:#F7F6F1; --gold:#A87B24; --mute:#5D6774; --line:#DDD9CF; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:#2B333D;
         font-family:'Newsreader',Georgia,serif; font-size:1.06rem; line-height:1.75; }}
  header {{ background:linear-gradient(178deg,#141C26 0%,var(--ink) 55%,#33415280 90%,var(--paper) 100%);
            padding:3.2rem 1.4rem 4rem; text-align:center; }}
  .date {{ font-family:'Fragment Mono',monospace; font-size:.68rem; letter-spacing:.28em;
           color:#C9A45B; text-transform:uppercase; margin-bottom:1rem; }}
  h1 {{ font-family:'Young Serif',Georgia,serif; font-weight:400;
        font-size:clamp(2rem,7vw,3rem); color:#F2EFE7; margin:0; line-height:1.1; }}
  .tagline {{ font-style:italic; color:#9AA6B5; margin-top:.7rem; }}
  .shelf {{ max-width:680px; margin:-2rem auto 0; padding:0 1.2rem; }}
  .shelf-card {{ background:#fff; border:1px solid var(--line); border-radius:6px;
                 padding:.9rem 1rem; box-shadow:0 4px 18px rgba(32,43,56,.08); }}
  .spines {{ display:flex; gap:3px; height:26px; align-items:flex-end; margin-bottom:.55rem; }}
  .spine {{ flex:1; border-radius:2px 2px 0 0; }}
  .shelf-label {{ font-family:'Fragment Mono',monospace; font-size:.66rem;
                  letter-spacing:.14em; color:var(--mute); text-transform:uppercase; }}
  main {{ max-width:680px; margin:0 auto; padding:2.2rem 1.4rem 4rem; }}
  .eyebrow {{ font-family:'Fragment Mono',monospace; font-size:.66rem; letter-spacing:.22em;
              color:var(--gold); text-transform:uppercase; border-bottom:1px solid var(--line);
              padding-bottom:.5rem; margin:2.6rem 0 1.4rem; }}
  h2.book {{ font-family:'Young Serif',Georgia,serif; font-weight:400; font-size:1.8rem;
             color:var(--ink); margin:0 0 .3rem; line-height:1.2; }}
  .byline {{ font-style:italic; color:var(--mute); margin-bottom:1.6rem; }}
  main h1, main h2, main h3 {{ font-family:'Young Serif',Georgia,serif; font-weight:400;
                               color:var(--ink); line-height:1.3; margin:2.2rem 0 .8rem; }}
  main h1 {{ font-size:1.5rem; }} main h2 {{ font-size:1.35rem; }} main h3 {{ font-size:1.1rem; }}
  main a {{ color:var(--gold); text-underline-offset:3px; }}
  main li {{ margin-bottom:.6rem; }}
  main strong {{ color:var(--ink); }}
  footer {{ text-align:center; margin-top:4rem; font-family:'Fragment Mono',monospace;
            font-size:.64rem; letter-spacing:.2em; color:var(--mute); text-transform:uppercase; }}
  footer a {{ color:var(--mute); }}
</style>
</head>
<body>
<header>
  <div class="date">{date}</div>
  <h1>The Morning Study</h1>
  <div class="tagline">the news, then the next book</div>
</header>
<div class="shelf"><div class="shelf-card">
  <div class="spines">{spines}</div>
  <div class="shelf-label">Reading shelf · {remaining} of {total} remaining</div>
</div></div>
<main>
  <div class="eyebrow">I · The News — D1 Ticker &amp; Bloomberg</div>
  {news_html}
  {book_html}
  <footer>— end of this morning's study — <br><br><a href="{archive_link}">past briefings</a></footer>
</main>
</body>
</html>
"""


def collect_text(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


def get_news(client, today):
    prompt = f"""Today is {today}. Search the web for today's (or the most recent) top stories
from D1 Ticker (d1ticker.com — the college athletics business newsletter; NOT D1Baseball) and from Bloomberg. Write a morning digest in markdown: the 6-10 most
important items, each with a bolded one-line headline, 2-3 sentences of context entirely
in your own words (never copy source wording), and a markdown link. Lead with the most
important news from each source. If D1 Ticker is inaccessible, note it briefly and cover Bloomberg
more deeply. Output only the digest, no preamble."""
    r = client.messages.create(model=MODEL, max_tokens=4000,
                               tools=[{"type": "web_search_20250305", "name": "web_search"}],
                               messages=[{"role": "user", "content": prompt}])
    return collect_text(r)


def get_brief(client, title, author):
    prompt = f"""Write an extremely detailed key-ideas brief of "{title}" by {author}.
Target 2,500+ words in markdown, covering: (1) the central thesis and why it matters;
(2) every major framework, model, or argument, each explained fully with its logic;
(3) the most important supporting examples and stories, retold in your own words;
(4) how the argument builds across the book; (5) honest critiques or limitations;
(6) a closing "How to Apply This" section with concrete personal and professional
applications, ending with five key takeaways.
Convey all ideas entirely in your own words — never reproduce or closely paraphrase
the book's actual text. Output only the brief, no preamble. Use ## for section headers."""
    r = client.messages.create(model=MODEL, max_tokens=10000,
                               messages=[{"role": "user", "content": prompt}])
    return collect_text(r)


def build_page(today, queue, news_md, book, brief_md, is_archive=False):
    books = queue["books"]
    spines = ""
    for b in books:
        if b["completed"]:
            color, h = "#DDD9CF", 14
        elif book and b["title"] == book["title"]:
            color, h = "#A87B24", 26
        else:
            color, h = "#202B38", 20
        spines += f'<div class="spine" style="background:{color};height:{h}px" title="{html.escape(b["title"])}"></div>'

    news_html = md.markdown(news_md, extensions=["extra"])
    if book and brief_md:
        brief_html = md.markdown(brief_md, extensions=["extra"])
        book_html = (f'<div class="eyebrow">II · Today\'s Book</div>'
                     f'<h2 class="book">{html.escape(book["title"])}</h2>'
                     f'<div class="byline">by {html.escape(book["author"])}</div>{brief_html}')
    else:
        book_html = ('<div class="eyebrow">II · Today\'s Book</div>'
                     '<p><em>The shelf is empty — edit queue.json in your repository to add books.</em></p>')

    remaining = sum(1 for b in books if not b["completed"])
    return PAGE_TEMPLATE.format(
        date=today, spines=spines, remaining=remaining, total=len(books),
        news_html=news_html, book_html=book_html,
        archive_link="archive/" if not is_archive else "./",
    )


def write_archive_index():
    pages = sorted(ARCHIVE.glob("*.html"), reverse=True)
    items = "".join(
        f'<li style="margin-bottom:.6rem"><a href="{p.name}">{p.stem}</a></li>'
        for p in pages if p.name != "index.html"
    )
    (ARCHIVE / "index.html").write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex"><title>Past Briefings</title></head>'
        '<body style="font-family:Georgia,serif;max-width:680px;margin:2rem auto;padding:0 1.2rem">'
        f'<h1>Past Briefings</h1><ul>{items}</ul><p><a href="../">back to today</a></p></body></html>'
    )


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        sys.exit("ERROR: missing ANTHROPIC_API_KEY secret")

    client = anthropic.Anthropic(api_key=api_key)
    today = date.today().strftime("%A, %B %d, %Y")
    stamp = date.today().isoformat()

    queue = json.loads(QUEUE_FILE.read_text())
    book = next((b for b in queue["books"] if not b["completed"]), None)

    print("Generating news digest...")
    try:
        news_md = get_news(client, today)
    except Exception as e:
        news_md = f"_The news digest failed this morning ({e}). Book brief below._"

    brief_md = ""
    if book:
        print(f"Generating brief: {book['title']}...")
        brief_md = get_brief(client, book["title"], book["author"])
        book["completed"] = True
        book["completed_on"] = stamp

    DOCS.mkdir(exist_ok=True)
    ARCHIVE.mkdir(exist_ok=True)
    page = build_page(today, queue, news_md, book, brief_md)
    (DOCS / "index.html").write_text(page)
    (ARCHIVE / f"{stamp}.html").write_text(
        build_page(today, queue, news_md, book, brief_md, is_archive=True)
    )
    write_archive_index()
    QUEUE_FILE.write_text(json.dumps(queue, indent=2) + "\n")
    print(f"Published briefing for {stamp}. Book: {book['title'] if book else '(queue empty)'}")


if __name__ == "__main__":
    main()
