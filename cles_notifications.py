#!/usr/bin/env python3
"""Crée les deux clés des notifications. À lancer une seule fois sur l'ordinateur, sans rien enregistrer dans le projet."""
import base64
import subprocess


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


pem = subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout"], capture_output=True, check=True).stdout
der = subprocess.run(["openssl", "ec", "-outform", "DER"], input=pem, capture_output=True, check=True).stdout
# Structure DER d'une clé EC P-256 : la clé privée (32 octets) suit l'en-tête, la clé publique (65 octets) termine le fichier.
print("VAPID_PUBLIC_KEY =", b64(der[-65:]))
print("VAPID_PRIVATE_KEY =", b64(der[7:39]))
