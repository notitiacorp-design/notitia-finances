# Notitia Finances

MVP de l’interface de suivi des dépenses du couple. L’interface fonctionne immédiatement en **mode aperçu** avec des données locales. Elle bascule sur Airtable quand les variables d’environnement sont présentes.

## Lancer

```bash
cd /home/openclaw/notitia-finances
PORT=8787 python3 server.py
```

Puis ouvrir http://127.0.0.1:8787

## Airtable

```bash
export AIRTABLE_API_KEY='[REDACTED]'
export AIRTABLE_BASE_ID='[BASE_ID]'
export AIRTABLE_TABLE='Dépenses Couple'
PORT=8787 python3 server.py
```

Le jeton ne doit jamais être placé dans `index.html` ni publié sur GitHub Pages. Le serveur Python sert d’adaptateur privé. La base Airtable séparée reste à créer ; la table créée par erreur dans Ménage Béziers Express n’est pas utilisée par défaut.
