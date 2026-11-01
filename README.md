# Vigie

Veille pour les DPO (délégués à la protection des données) : RGPD, droit du numérique, droit de la santé et cybersécurité : un site installable sur téléphone, mis à jour trois fois par jour, et une lettre envoyée par e-mail chaque lundi matin.

## Mise en ligne (15 minutes, gratuit)

1. Créez un compte sur [github.com](https://github.com) puis un dépôt **public** nommé `vigie`. Il ne contient que des titres d'articles et des liens : aucune adresse e-mail ni mot de passe.
2. Sur la page du dépôt, choisissez **uploading an existing file** et déposez tout le contenu de ce dossier, sauf `.claude`. Vérifiez que `.github/workflows/veille.yml` est bien présent, car le Finder masque ce dossier (Cmd+Maj+. pour l'afficher). S'il manque, créez-le avec **Add file > Create new file**.
3. Dans **Settings > Pages**, réglez **Source** sur **GitHub Actions**.
4. Dans **Actions > Mise à jour de la veille**, cliquez sur **Run workflow**.

Le site est ensuite à l'adresse `https://VOTRE-NOM.github.io/vigie/`. Sur iPhone : Safari, Partager, **Sur l'écran d'accueil**.

## Activer la lettre par e-mail

Avec Gmail : activez la validation en deux étapes, créez un [mot de passe d'application](https://myaccount.google.com/apppasswords), puis ajoutez ces secrets dans **Settings > Secrets and variables > Actions** :

| Secret | Valeur |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | votre adresse Gmail |
| `SMTP_PASSWORD` | le mot de passe d'application |
| `NEWSLETTER_TO` | l'adresse de votre sœur (plusieurs possibles, séparées par des virgules) |

Pour tester : **Run workflow** en cochant **Envoyer la lettre maintenant**.

## Installer l'application et les notifications de 8 h et 18 h (iPhone)

Il faut iOS 16.4 ou plus récent. Tout reste gratuit.

1. Sur l'ordinateur, une seule fois, lancez la commande ci-dessous et ajoutez les deux valeurs affichées en secrets GitHub, `VAPID_PUBLIC_KEY` et `VAPID_PRIVATE_KEY`. Ne les enregistrez pas dans un fichier du projet.

   ```bash
   python3 cles_notifications.py
   ```

2. Dans **Actions**, lancez **Run workflow** pour publier le site avec ces clés.
3. Sur l'iPhone, ouvrez le site dans Safari, puis Partager et **Sur l'écran d'accueil**. Ouvrez Vigie depuis la nouvelle icône.
4. Touchez **Activer les notifications de 8 h et 18 h** et autorisez. Copiez le code affiché et transmettez-le.
5. Ajoutez ce code dans le secret `PUSH_SUBSCRIPTIONS` (pour plusieurs iPhone, un code par ligne).
6. Pour tester : **Run workflow** en cochant **Envoyer la notification maintenant**.

GitHub peut parfois retarder de quelques minutes le déclenchement des notifications. Celle de 18 h ne part que s'il y a du nouveau depuis le matin. Le secret `PUSH_SUBSCRIPTIONS` doit être mis à jour si la notification cesse d'arriver après une réinstallation de l'application.

## Ajuster la veille

Le site ne garde que les 7 derniers jours : les articles plus anciens sont supprimés automatiquement. Il est entièrement gratuit et n'utilise pas d'IA : le texte sous chaque titre reprend les premières phrases de l'article. Tout se règle dans `sources.json` : ajout d'un flux, mots-clés par rubrique, catégories (Sanction, Jurisprudence…). Un flux en panne n'empêche pas les autres et son nom s'affiche en bas du site.

## Tester sur l'ordinateur

```bash
python3 veille.py
```

La page générée est `site/index.html`.
