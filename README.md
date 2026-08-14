# Notitia Finances

Suivi des dépenses du couple, avec un conseiller Qwen côté serveur.

- Frontend public : saisie, totaux, équilibre, questions, lecture de tickets.
- Backend privé : Airtable + Qwen. Aucune clé n’est exposée dans le navigateur.

## Lancer en local

```bash
cd /home/openclaw/notitia-finances
PORT=8787 python3 server.py
```

## Variables d’environnement

```bash
AIRTABLE_API_KEY=
AIRTABLE_BASE_ID=appEGVy9MVBGYmPQT
AIRTABLE_TABLE=Dépenses
OPENROUTER_API_KEY=
QWEN_MODEL=qwen/qwen3.7-flash
QWEN_VISION_MODEL=qwen/qwen2.5-vl-32b-instruct
QWEN_BASE_URL=https://openrouter.ai/api/v1
PUBLIC_ORIGIN=https://notitia-finances.vercel.app
```

Le jeton Airtable ne doit jamais être placé dans `index.html` ni publié sur GitHub Pages.

## Production

https://notitia-finances.vercel.app
