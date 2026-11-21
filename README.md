# Publio Studio

Publication automatique de vidéos sur TikTok, 100 % gratuite (GitHub Pages + GitHub Actions).

## Comment ça marche

1. **Connexion** : sur https://abdelhakkabar.github.io/publio/app.html → « Se connecter avec TikTok ». La page suivante affiche un code : lancer le workflow **Connecter TikTok** (onglet Actions) en collant ce code. Les jetons sont enregistrés chiffrés dans `data/tokens.enc`.
2. **Programmer** : ajouter des entrées dans `queue/schedule.json` :

```json
[
  {
    "time": "2026-10-20T08:00:00+02:00",
    "video": "https://lien-public-vers/la-video.mp4",
    "caption": "Pico et Plume 🦔🐦 #histoire #enfants",
    "privacy": "PUBLIC_TO_EVERYONE",
    "mode": "direct"
  }
]
```

- `video` : lien public vers le MP4, ou chemin d'un fichier du dépôt.
- `privacy` : `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `FOLLOWER_OF_CREATOR` ou `SELF_ONLY`. **Tant que l'app n'est pas validée par TikTok, seul `SELF_ONLY` (privé) fonctionne.**
- `mode` : `direct` (publication directe) ou `draft` (brouillon dans la boîte de réception TikTok).

3. **Publication** : le workflow **Publier les vidéos** tourne toutes les 15 minutes et publie ce qui est à l'heure (3 max par passage). Le statut est écrit dans `queue/schedule.json` et `data/history.json`.

## Secrets à créer (Settings → Secrets and variables → Actions)

| Nom | Valeur |
|---|---|
| `TIKTOK_CLIENT_KEY` | Client key de l'app (portail TikTok for Developers) |
| `TIKTOK_CLIENT_SECRET` | Client secret de l'app |
| `PUBLIO_KEY` | Une longue phrase secrète inventée (sert à chiffrer les jetons) |

Variable optionnelle : `PUBLIO_PRIVACY` (confidentialité par défaut, `SELF_ONLY` si absente).
