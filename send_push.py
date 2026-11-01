#!/usr/bin/env python3
"""Envoie les notifications de 8 h et 18 h (Paris) aux iPhone abonnés.

Variables : VAPID_PRIVATE_KEY, PUSH_SUBSCRIPTIONS (un code d'abonnement par ligne), NOTIF_FORCE=1 pour envoyer tout de suite.
Dépendance : pywebpush, installée par le workflow.
"""
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
MARKER = ROOT / "last_push.txt"
PARIS = ZoneInfo("Europe/Paris")


def send_time(now, last, count):
    """Renvoie l'heure d'envoi, ou None s'il ne faut rien envoyer. Le workflow démarre vers H-15 pour absorber les retards de GitHub."""
    morning = now.hour < 13
    if last and last.date() == now.date() and (last.hour < 13) == morning:
        return None  # déjà envoyée
    if not morning and not count:
        return None  # le soir, rien de neuf : pas de notification
    target = now.replace(hour=8 if morning else 18, minute=0, second=0, microsecond=0)
    if now < target - dt.timedelta(minutes=30):
        return None  # heure d'hiver ou d'été : l'autre exécution enverra la notification
    return target


def main():
    key = os.environ.get("VAPID_PRIVATE_KEY")
    codes = [line.strip() for line in os.environ.get("PUSH_SUBSCRIPTIONS", "").splitlines() if line.strip()]
    if not key or not codes:
        print("Notification ignorée : clé ou abonnement manquant")
        return
    brief = json.loads((ROOT / "brief.json").read_text(encoding="utf-8"))
    if not os.environ.get("NOTIF_FORCE"):
        now = dt.datetime.now(PARIS)
        last = dt.datetime.fromisoformat(MARKER.read_text().strip()).astimezone(PARIS) if MARKER.exists() else None
        target = send_time(now, last, brief["count"])
        if target is None:
            print("Pas de notification à cette exécution")
            return
        if now < target:
            time.sleep((target - now).total_seconds())
    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": brief["title"], "body": brief["body"], "url": "./"}, ensure_ascii=False)
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "vigie")
    sent = 0
    for code in codes:
        try:
            webpush(
                subscription_info=json.loads(code),
                data=payload,
                vapid_private_key=key,
                vapid_claims={"sub": f"https://{owner.lower()}.github.io"},
                ttl=6 * 3600,
            )
            sent += 1
        except (WebPushException, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", "?")
            print(f"Échec d'un envoi (code {status}) : 404 ou 410 signifie qu'il faut réactiver les notifications sur l'iPhone")
    print(f"{sent} notification(s) envoyée(s) sur {len(codes)}")
    if not sent:
        sys.exit(1)
    MARKER.write_text(dt.datetime.now(PARIS).isoformat())


if __name__ == "__main__":
    main()
