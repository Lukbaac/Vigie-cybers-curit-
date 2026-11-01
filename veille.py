#!/usr/bin/env python3
"""Collecte les flux de sources.json, met à jour l'archive et génère le site et la lettre.

Bibliothèque standard uniquement. Usage : python3 veille.py [--no-fetch]
"""
import concurrent.futures
import datetime as dt
import email.utils
import html.parser
import http.client
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "articles.json"
STATUS = ROOT / "status.json"
SITE = ROOT
UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC).replace(microsecond=0)
KEEP_DAYS = 7
MAX_FEED_BYTES = 8_000_000
SUMMARY_LEN = 260
FEED_TEXT_LEN = 1500
ARTICLE_TEXT_LEN = 3000
MAX_IDEA_LEN = 320
MIN_IDEA_LEN = 110
STORY_STOPWORDS = set(
    "donnees personnelles fuite violation cyberattaque victime cnil rgpd amende amendes euros millions sanction sanctionne "
    "sanctions inflige societe societes entreprise entreprises france francais francaise protection droit droits sante "
    "numerique securite clients contre apres pour avec dans plus cette comment leur leurs nouvelle nouveau sans sous "
    "data privacy".split()
)
TOPIC_LABELS = {"rgpd": "RGPD & données", "numerique": "Droit du numérique", "sante": "Droit de la santé", "cyber": "Cybersécurité"}
TOPIC_COLORS = {"rgpd": "#3d4fc4", "numerique": "#0f7a78", "sante": "#b5345c", "cyber": "#a85c00"}
PAGE_META = (
    '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    '<meta name="robots" content="noindex">'
    '<link rel="manifest" href="manifest.webmanifest"><link rel="icon" href="icon.svg" type="image/svg+xml">'
    '<link rel="alternate" type="application/rss+xml" title="Vigie" href="feed.xml">'
    '<link rel="apple-touch-icon" href="icon-180.png">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="Vigie">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
    '<meta name="theme-color" content="#1c2340"></head><body>'
)


def fold(text):
    """Minuscule-insensible géré à part : retire seulement accents et apostrophes typographiques."""
    text = unicodedata.normalize("NFKD", text.replace("’", "'"))
    return "".join(c for c in text if not unicodedata.combining(c))


def compile_terms(terms):
    """Un terme tout en majuscules (DSA, DORA…) n'est reconnu qu'en majuscules."""
    exact = [re.escape(fold(t)) for t in terms if t.isupper()]
    loose = [re.escape(fold(t)) for t in terms if not t.isupper()]
    patterns = []
    if exact:
        patterns.append(re.compile(r"(?<!\w)(?:" + "|".join(exact) + r")(?!\w)"))
    if loose:
        patterns.append(re.compile(r"(?<!\w)(?:" + "|".join(loose) + r")(?!\w)", re.I))
    return patterns


def matches(patterns, text):
    return any(p.search(text) for p in patterns)


def clean(text, limit=None):
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = html.unescape(html.unescape(re.sub(r"<[^>]+>", " ", text)))  # certains flux encodent deux fois
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
    return text


def parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return min(parsed.astimezone(UTC), NOW)


def local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(node, *names):
    for child in node:
        if local(child.tag) in names and (child.text or "").strip():
            return child.text
    return ""


def entry_link(node):
    for child in node:
        if local(child.tag) != "link":
            continue
        if child.get("href") and child.get("rel", "alternate") == "alternate":
            return child.get("href")
        if (child.text or "").strip():
            return child.text.strip()
    return ""


def fetch(source):
    request = urllib.request.Request(source["url"], headers={"User-Agent": "Mozilla/5.0 (Vigie, veille RSS)"})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(MAX_FEED_BYTES + 1)
    data = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("flux trop volumineux")
    if b"<!ENTITY" in data[:4096]:
        raise ValueError("entités XML refusées")
    entries = []
    for node in ET.fromstring(data).iter():
        if local(node.tag) not in ("item", "entry"):
            continue
        title = clean(child_text(node, "title"))
        link = entry_link(node)
        name = source["name"]
        if name == "Google Actualités":
            publisher = child_text(node, "source").strip()
            if publisher:
                name = publisher
                title = re.sub(r"\s+-\s+" + re.escape(publisher) + r"$", "", title)
            summary = ""
        else:
            summary = clean(child_text(node, "description", "summary", "content", "encoded"), FEED_TEXT_LEN)
        if title and link.startswith(("http://", "https://")):
            date = parse_date(child_text(node, "pubdate", "published", "updated", "date"))
            entries.append({"title": title, "link": link, "summary": summary, "date": date, "source": name})
    return entries


class ParagraphParser(html.parser.HTMLParser):
    """Récupère les paragraphes d'une page, en privilégiant ceux du corps de l'article."""

    SKIP = {"script", "style", "nav", "footer", "aside", "form", "header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = self.main = 0
        self.current = None
        self.in_main, self.others = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("article", "main"):
            self.main += 1
        elif tag == "p" and not self.skip:
            self.current = []

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in ("article", "main"):
            self.main = max(0, self.main - 1)
        elif tag == "p" and self.current is not None:
            text = re.sub(r"\s+", " ", "".join(self.current)).strip()
            if len(text) >= 60 and "\ufffd" not in text:  # paragraphe mal encodé par le site
                (self.in_main if self.main else self.others).append(text)
            self.current = None

    def handle_data(self, data):
        if self.current is not None and not self.skip:
            self.current.append(data)


def article_text(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Vigie, veille RSS)"})
    with urllib.request.urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        page = response.read(MAX_FEED_BYTES).decode(charset, "replace")
    parser = ParagraphParser()
    parser.feed(page)
    return "\n".join(parser.in_main or parser.others)[:ARTICLE_TEXT_LEN]


def safe_article_text(article):
    try:
        return article_text(article["link"])
    except (OSError, ValueError, http.client.HTTPException):
        return ""


def main_idea(title, text):
    """Garde les premières phrases complètes qui disent autre chose que le titre. Gratuit : aucune IA."""
    text = re.sub(r"^Tribune[^–-]{0,40}[–-]\s*", "", text.strip())
    text = re.sub(r"\s*The post .*$", "", text, flags=re.S)
    text = re.sub(r"\s*(\(\.\.\.\)|\[(…|\.\.\.)\]|…|\.\.\.)\s*$", "", text)
    sentences = re.split(r"(?<=[.!?…»])\s+(?=[A-ZÀ-Ý«\"])", text)
    if sentences and not re.search(r"[.!?»\"]$", sentences[-1]):
        sentences.pop()  # phrase coupée par le site source
    title_words = set(re.findall(r"\w{4,}", fold(title).lower()))
    idea = ""
    for sentence in sentences:
        words = set(re.findall(r"\w{4,}", fold(sentence).lower()))
        if not idea and words and len(words & title_words) / len(words) > 0.8:
            continue  # simple reprise du titre
        if idea and len(idea) + len(sentence) > MAX_IDEA_LEN:
            break
        idea = f"{idea} {sentence}".strip()
        if len(idea) >= MIN_IDEA_LEN:
            break
    if len(idea) > MAX_IDEA_LEN:
        idea = idea[:MAX_IDEA_LEN].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
    return idea


def add_idea(article):
    """L'aperçu du flux suffit le plus souvent ; sinon on lit le début de la page de l'article."""
    feed_text = article["summary"]
    if "(not verified)" in feed_text:  # métadonnées de la Commission européenne mêlées au texte
        feed_text = ""
    idea = main_idea(article["title"], feed_text)
    if len(idea) < MIN_IDEA_LEN:
        page_idea = main_idea(article["title"], safe_article_text(article))
        idea = page_idea if len(page_idea) > len(idea) else idea
    if not idea and feed_text:
        idea = clean(re.sub(r"\s*\((\.\.\.|…)\)\s*$", "…", feed_text), MAX_IDEA_LEN)
    article["summary"] = idea


def story_words(title):
    """Les mots qui distinguent une affaire : Fnac, Darty… sans le vocabulaire commun à toutes les actualités."""
    return set(re.findall(r"\w{4,}", fold(title).lower())) - STORY_STOPWORDS


def classify(entry, source, topic_terms, nature_terms, exclude_terms, company_terms, context_terms):
    text = fold(entry["title"] + " " + entry["summary"][:SUMMARY_LEN])
    if not source.get("official") and matches(exclude_terms, text):
        return [], []
    topics = [t for t, terms in topic_terms.items() if matches(terms, text)]
    if "cyber" not in topics and matches(company_terms, text) and matches(context_terms, text):
        topics.append("cyber")
    if not source.get("filter"):
        topics = list(dict.fromkeys(source.get("topics", []) + topics))
    elif source.get("topics"):
        topics = list(dict.fromkeys(source["topics"] + topics))
    topics.sort(key=list(TOPIC_LABELS).index)  # le RGPD d'abord : c'est le coeur du métier de DPO
    natures = [n for n, terms in nature_terms.items() if matches(terms, text)]
    if source.get("alert"):
        natures.insert(0, "Alerte")
    return topics, natures


def title_key(title):
    return re.sub(r"[^a-z0-9]+", "", fold(title).lower())[:90]


def collect(archive, config):
    topic_terms = {t: compile_terms(v) for t, v in config["keywords"].items()}
    nature_terms = {n: compile_terms(v) for n, v in config["natures"].items()}
    exclude_terms = compile_terms(config["exclude"])
    company_terms = compile_terms(config["cyber_companies"])
    context_terms = compile_terms(config["cyber_context"])
    trusted = {fold(name).lower() for name in config["trusted_publishers"]}
    known_ids = {a["id"] for a in archive}
    known_titles = {title_key(a["title"]) for a in archive}
    sources = config["sources"]
    statuses, added, new_articles = [], 0, []
    stories = [story_words(a["title"]) for a in archive]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        futures = [pool.submit(fetch, s) for s in sources]
    for source, future in zip(sources, futures):
        try:
            entries = future.result()
        except Exception as exc:  # une source en panne ne bloque jamais les autres
            statuses.append({"name": source["name"], "ok": False, "error": str(exc)[:120]})
            continue
        new = 0
        for entry in entries:
            uid = hashlib.sha1(entry["link"].encode()).hexdigest()[:16]
            key = title_key(entry["title"])
            date = entry["date"] or NOW
            if uid in known_ids or key in known_titles or date < NOW - dt.timedelta(days=KEEP_DAYS):
                continue
            if source["name"] == "Google Actualités" and fold(entry["source"]).lower() not in trusted:
                continue
            words = story_words(entry["title"])
            if any(part in entry["link"] for part in source.get("skip_url", [])):
                continue
            # Une affaire déjà couverte n'est pas répétée par la presse générale (sources "filter") ;
            # les autorités et les sources spécialisées, lues en premier, restent toutes affichées.
            if source.get("filter") and any(len(words & known) >= 2 for known in stories):
                continue
            topics, natures = classify(entry, source, topic_terms, nature_terms, exclude_terms, company_terms, context_terms)
            if not topics:
                continue
            new_articles.append({
                "id": uid, "title": entry["title"], "link": entry["link"], "summary": entry["summary"],
                "source": entry["source"], "date": date.isoformat(), "topics": topics, "natures": natures,
                "added": NOW.isoformat(), "official": bool(source.get("official")), "lang": source.get("lang", "fr"),
            })
            stories.append(words)
            known_ids.add(uid)
            known_titles.add(key)
            new += 1
        added += new
        statuses.append({"name": source["name"], "ok": True, "items": len(entries), "new": new})
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        list(pool.map(add_idea, new_articles))
    archive.extend(new_articles)
    return statuses, added


def score(article):
    points = 3 if article["official"] else 0
    points += 3 if "rgpd" in article["topics"] else 0
    points += sum({"Alerte": 3, "Sanction": 4, "Jurisprudence": 4, "Doctrine": 4, "Texte": 3, "Fuite de données": 2}.get(n, 0) for n in article["natures"])
    return points + (1 if article["summary"] else 0)


def varied(items, count):
    """Évite qu'une même affaire, reprise par plusieurs médias, occupe toute la rubrique."""
    words = lambda a: {w for w in re.findall(r"\w{4,}", fold(a["title"]).lower())}
    picked, repeats = [], []
    for item in items:
        (repeats if any(len(words(item) & words(p)) >= 3 for p in picked) else picked).append(item)
    return (picked + repeats)[:count]


def write_newsletter(articles, updated):
    """Lettre des 7 derniers jours, en tableaux et styles en ligne pour les messageries."""
    since = NOW - dt.timedelta(days=7)
    week = [a for a in articles if parse_date(a["date"]) >= since]
    year, number, _ = NOW.isocalendar()
    subject = f"Vigie – semaine {number} : {len(week)} actualités"
    blocks, text = [], [subject, ""]
    for topic, label in TOPIC_LABELS.items():
        items = sorted((a for a in week if a["topics"][0] == topic), key=lambda a: (score(a), a["date"]), reverse=True)
        if not items:
            continue
        shown = varied(items, 6)
        rows = []
        text.append(label.upper())
        for a in shown:
            tags = " · ".join(a["natures"][:2])
            meta = " · ".join(x for x in [a["source"], tags] if x)
            rows.append(
                f'<tr><td style="padding:18px 0;border-top:1px solid #dfe3ee">'
                f'<a href="{html.escape(a["link"], quote=True)}" style="color:#1c2340;font-weight:600;font-size:17px;line-height:1.35;text-decoration:none">{html.escape(a["title"])}</a>'
                f'<div style="color:#5b6480;font-size:13px;padding-top:5px">{html.escape(meta)}</div>'
                + (f'<div style="color:#2a3150;font-size:15px;line-height:1.6;padding-top:8px">{html.escape(a["summary"])}</div>' if a["summary"] else "")
                + "</td></tr>"
            )
            text += [f"- {a['title']} ({a['source']})", f"  {a['link']}"]
        text.append("")
        more = f'<div style="color:#5b6480;font-size:12px;padding-top:6px">Et {len(items) - len(shown)} autres sur le site.</div>' if len(items) > len(shown) else ""
        blocks.append(
            f'<h2 style="margin:26px 0 6px;font-size:14px;letter-spacing:.04em;text-transform:uppercase;color:{TOPIC_COLORS[topic]}">{label} <span style="font-weight:400">({len(items)})</span></h2>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table>{more}'
        )
    if not blocks:
        blocks.append('<p style="color:#39415c">Aucune actualité retenue cette semaine.</p>')
    body = (
        f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(subject)}</title></head>'
        '<body style="margin:0;background:#ffffff"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:16px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;font-family:Georgia,\'Times New Roman\',serif"><tr><td style="background:#1c2340;color:#ffffff;padding:20px 24px">'
        f'<div style="font-size:24px;font-weight:700">Vigie</div><div style="font-size:13px;color:#c5cbe3;padding-top:3px">Semaine {number} · {len(week)} actualités pour les DPO : RGPD, numérique, santé et cyber</div>'
        f'</td></tr><tr><td style="padding:0 24px 24px">{"".join(blocks)}</td></tr></table></td></tr></table></body></html>'
    )
    folder = SITE / "newsletter"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "latest.html").write_text(body, encoding="utf-8")
    (ROOT / "newsletter.json").write_text(
        json.dumps({"subject": subject, "text": "\n".join(text), "week": f"{year}-S{number:02d}", "count": len(week)}, ensure_ascii=False), encoding="utf-8"
    )


def notification_brief(articles):
    """Contenu de la notification : les articles arrivés depuis la précédente, les plus marquants d'abord, sans IA."""
    since = NOW - dt.timedelta(hours=24)
    marker = ROOT / "last_push.txt"
    if marker.exists():
        since = max(since, parse_date(marker.read_text()))
    # "added" : une date de publication peut être antérieure à l'arrivée de l'article dans la veille
    recent = sorted((a for a in articles if parse_date(a.get("added", a["date"])) >= since), key=lambda a: (score(a), a["date"]), reverse=True)
    count = len(recent)
    if count:
        title = f"Vigie : {count} nouvelle{'s' if count > 1 else ''} actualité{'s' if count > 1 else ''}"
        body = "\n".join("• " + clean(a["title"], 62) for a in varied(recent, 3))
    else:
        title, body = "Vigie", "Pas de nouvelle actualité depuis la dernière notification."
    (ROOT / "brief.json").write_text(json.dumps({"title": title, "body": body, "count": count}, ensure_ascii=False), encoding="utf-8")


def write_feed(articles, updated):
    owner, _, repo = os.environ.get("GITHUB_REPOSITORY", "/").partition("/")
    home = f"https://{owner}.github.io/{repo}/" if owner else "https://github.io/"
    items = "".join(
        f"<item><title>{xml_escape(a['title'])}</title><link>{xml_escape(a['link'])}</link><guid isPermaLink=\"false\">{a['id']}</guid>"
        f"<pubDate>{email.utils.format_datetime(parse_date(a['date']))}</pubDate><description>{xml_escape(a['summary'])}</description></item>"
        for a in articles[:100]
    )
    (SITE / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Vigie</title>'
        f"<link>{home}</link><description>Veille RGPD, numérique, santé et cyber</description>{items}</channel></rss>",
        encoding="utf-8",
    )


def build(articles, statuses):
    updated = NOW.isoformat()
    payload = json.dumps(
        {"updated": updated, "articles": articles, "sources": statuses, "labels": TOPIC_LABELS, "vapid": os.environ.get("VAPID_PUBLIC_KEY", "")}, ensure_ascii=False, separators=(",", ":")
    ).replace("<", "\\u003c")
    page = (ROOT / "template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    register_sw = "<script>if('serviceWorker' in navigator)navigator.serviceWorker.register('sw.js').catch(function(){})</script>"
    (SITE / "index.html").write_text(PAGE_META + page + register_sw + "</body></html>", encoding="utf-8")
    (ROOT / "apercu.html").write_text(page, encoding="utf-8")  # même page, sans enveloppe, pour un aperçu partageable
    notification_brief(articles)
    write_newsletter(articles, updated)
    write_feed(articles, updated)


def main():
    config = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    archive = json.loads(ARCHIVE.read_text(encoding="utf-8")) if ARCHIVE.exists() else []
    if "--no-fetch" in sys.argv:
        statuses, added = (json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else []), 0
    else:
        statuses, added = collect(archive, config)
    cutoff = NOW - dt.timedelta(days=KEEP_DAYS)
    archive = sorted((a for a in archive if parse_date(a["date"]) >= cutoff), key=lambda a: a["date"], reverse=True)
    ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, indent=0), encoding="utf-8")
    STATUS.write_text(json.dumps(statuses, ensure_ascii=False, indent=0), encoding="utf-8")
    build(archive, statuses)
    failed = [s for s in statuses if not s["ok"]]
    print(f"{added} nouveaux, {len(archive)} en archive, {len(failed)} source(s) en échec sur {len(statuses)}")
    for s in failed:
        print(f"  ÉCHEC {s['name']} : {s['error']}")


if __name__ == "__main__":
    main()
