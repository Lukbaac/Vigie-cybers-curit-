#!/usr/bin/env python3
"""Envoie newsletter/latest.html par SMTP, une seule fois par semaine.

Variables : SMTP_HOST, SMTP_PORT (587 par défaut), SMTP_USER, SMTP_PASSWORD, NEWSLETTER_TO (adresses séparées par des virgules).
"""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKER = ROOT / "last_sent.txt"


def main():
    required = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "NEWSLETTER_TO"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print("Envoi ignoré, réglages manquants :", ", ".join(missing))
        return
    meta = json.loads((ROOT / "newsletter.json").read_text(encoding="utf-8"))
    if MARKER.exists() and MARKER.read_text().strip() == meta["week"]:
        print("Lettre déjà envoyée pour", meta["week"])
        return
    if not meta["count"]:
        print("Aucune actualité cette semaine, envoi ignoré")
        return
    recipients = [a.strip() for a in os.environ["NEWSLETTER_TO"].split(",") if a.strip()]
    message = EmailMessage()
    message["Subject"] = meta["subject"]
    message["From"] = f"Vigie <{os.environ['SMTP_USER']}>"
    message["To"] = message["From"]
    message.set_content(meta["text"])
    message.add_alternative((ROOT / "newsletter" / "latest.html").read_text(encoding="utf-8"), subtype="html")
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT") or 587), timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message, to_addrs=recipients)  # destinataires en copie cachée
    MARKER.write_text(meta["week"])
    print(f"Lettre {meta['week']} envoyée à {len(recipients)} destinataire(s)")


if __name__ == "__main__":
    main()
