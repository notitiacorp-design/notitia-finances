import base64, difflib, io, json, os, re, urllib.error, urllib.parse, urllib.request
from datetime import date
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).parent
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "*")
BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appEGVy9MVBGYmPQT")
TABLE = os.getenv("AIRTABLE_TABLE", "Dépenses")
BUDGET_TABLE = os.getenv("AIRTABLE_BUDGET_TABLE", "Budgets")
TOKEN = os.getenv("AIRTABLE_API_KEY", "")
LOCAL_EXPENSES = []
LOCAL_BUDGETS = []
LOCAL_SHOPPING = []
SHOPPING_TABLE = os.getenv("AIRTABLE_SHOPPING_TABLE", "Shopping")
QWEN_KEY = os.getenv("QWEN_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "google/gemini-2.5-flash")
QWEN_VISION_MODEL = os.getenv("QWEN_VISION_MODEL", "qwen/qwen2.5-vl-72b-instruct")
QWEN_BASE = os.getenv("QWEN_BASE_URL", "https://openrouter.ai/api/v1")
MAX_IMAGE_CHARS = 3_500_000
MAX_DOC_CHARS = 4_000_000
CATEGORIES = ("Courses", "Logement", "Transport", "Sorties", "Abonnements", "Santé", "Autres")
PAYERS = ("Quentin", "Jessica")
BUDGET_MARK = "kind=budget"

SYSTEM_PROMPT = """Tu es l'assistant et observateur financier bienveillant du foyer de Quentin et Jessica (application Duopaye / Notitia).
Réponds en français, simplement, avec un ton complice, chaleureux et constructif.
Tu n'es pas un comptable rigide ni un contrôleur fiscal : le but n'est pas d'imposer un 50/50 strict ou d'exiger des remboursements au centime près, mais d'offrir une vision limpide, sereine et partagée des dépenses communes.
Règles:
- Utilise uniquement le contexte JSON et, le cas échéant, l'image jointe.
- Ne fabrique aucun revenu, dépense, solde ou budget fictif.
- Un budget à 0 signifie « pas encore fixé », jamais un plafond réel.
- Distingue faits, calculs et suggestions.
- Quand tu parles de la répartition, présente-la comme un point de repère informatif (« pour information, l'écart actuel est de... ») et non comme une dette impérative à solder immédiatement.
- Si une image est fournie (ticket, e-ticket, capture), extrais seulement le lisible.
- Ne crée ni dépense ni budget tout seul: propose, l'humain confirme.
- Si on te demande d'ajuster un budget, propose le nouveau montant et attends la confirmation.
- Réponds à Quentin et Jessica, jamais en anglais technique, sans exposer ton raisonnement interne."""


def current_month():
    return date.today().strftime("%Y-%m")


def airtable_request(method="GET", path="", payload=None, timeout=20):
    if not TOKEN or not BASE_ID:
        return None
    url = "https://api.airtable.com/v0/" + path
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        err = RuntimeError(f"Airtable {e.code}: {body}")
        err.code = e.code
        raise err from None


def display_payer(value):
    raw = str(value or "Quentin").strip()
    if raw.lower() in ("partenaire", "partner", "jessica"):
        return "Jessica"
    if raw in PAYERS:
        return raw
    return "Quentin"


def normalize_expense(fields, rid):
    note = str(fields.get("Note", "") or "")
    label = str(fields.get("Dépense", "") or "")
    return {
        "id": rid,
        "date": fields.get("Date", ""),
        "label": label,
        "category": fields.get("Catégorie", "Autres") if fields.get("Catégorie") in CATEGORIES else "Autres",
        "amount": float(fields.get("Montant (€)", 0) or 0),
        "payer": display_payer(fields.get("Payé par", "Quentin")),
        "shared": bool(fields.get("Dépense commune", True)),
        "status": fields.get("Remboursement", "À équilibrer"),
        "note": note,
        "is_budget": note.startswith(BUDGET_MARK) or label.startswith("[Budget]"),
        "is_shopping": note.startswith(SHOPPING_MARK) or label.startswith("[Shopping]"),
    }


def list_table(table):
    if not TOKEN or not BASE_ID:
        return None
    records, offset = [], None
    while True:
        qs = "pageSize=100"
        if offset:
            qs += "&offset=" + urllib.parse.quote(offset)
        data = airtable_request("GET", f"{BASE_ID}/{urllib.parse.quote(table)}?{qs}") or {}
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return records


def get_all_records():
    if TOKEN and BASE_ID:
        return [normalize_expense(r.get("fields", {}), r.get("id")) for r in (list_table(TABLE) or [])]
    return list(LOCAL_EXPENSES)


def get_expenses():
    return [x for x in get_all_records() if not x.get("is_budget") and not x.get("is_shopping")]

def delete_expense(record_id):
    if TOKEN and BASE_ID:
        try:
            airtable_request("DELETE", f"{BASE_ID}/{urllib.parse.quote(TABLE)}/{record_id}")
            return True
        except Exception:
            return False
    global LOCAL_EXPENSES
    LOCAL_EXPENSES = [x for x in LOCAL_EXPENSES if x.get("id") != record_id]
    return True

def update_expense(record_id, item):
    item = dict(item)
    item["payer"] = display_payer(item.get("payer"))
    fields = {
        "Dépense": item["label"],
        "Date": item["date"],
        "Catégorie": item["category"],
        "Montant (€)": float(item["amount"]),
        "Payé par": item["payer"],
    }
    if "shared" in item:
        fields["Dépense commune"] = bool(item.pop("shared"))
    if item.get("status"):
        fields["Remboursement"] = item["status"]
    if item.get("note"):
        fields["Note"] = item["note"]
    if TOKEN and BASE_ID:
        data = airtable_request(
            "PATCH",
            f"{BASE_ID}/{urllib.parse.quote(TABLE)}/{record_id}",
            {"fields": fields, "typecast": True},
        )
        return normalize_expense(data.get("fields", fields), data.get("id", record_id))
    for x in LOCAL_EXPENSES:
        if x.get("id") == record_id:
            x.update(item)
            return x
    raise ValueError("Dépense introuvable")

def clear_all_expenses():
    deleted = 0
    if TOKEN and BASE_ID:
        records = list_table(TABLE) or []
        for r in records:
            norm = normalize_expense(r.get("fields", {}), r.get("id"))
            if not norm.get("is_budget") and not norm.get("is_shopping"):
                try:
                    airtable_request("DELETE", f"{BASE_ID}/{urllib.parse.quote(TABLE)}/{r['id']}")
                    deleted += 1
                except Exception:
                    pass
    global LOCAL_EXPENSES
    LOCAL_EXPENSES = []
    return deleted

def get_shopping():
    if TOKEN and BASE_ID:
        try:
            records = list_table(SHOPPING_TABLE) or []
            return [
                {
                    "id": r["id"],
                    "item": r.get("fields", {}).get("Article", ""),
                    "category": r.get("fields", {}).get("Catégorie", "Courses"),
                    "checked": bool(r.get("fields", {}).get("Acheté", False)),
                    "season_tip": r.get("fields", {}).get("Conseil Saison", ""),
                }
                for r in records
                if r.get("fields", {}).get("Article")
            ]
        except RuntimeError as e:
            if getattr(e, "code", None) in (404, 403):
                return shopping_from_expense_records()
            raise
        except Exception:
            return shopping_from_expense_records()
    return list(LOCAL_SHOPPING)


def add_shopping_item(item, category="Courses"):
    item = str(item or "").strip()[:100]
    if not item:
        raise ValueError("Article vide")
    if TOKEN and BASE_ID:
        try:
            fields = {"Article": item, "Catégorie": category, "Acheté": False}
            data = airtable_request("POST", f"{BASE_ID}/{urllib.parse.quote(SHOPPING_TABLE)}", {"fields": fields, "typecast": True})
            if data and isinstance(data, dict):
                return {
                    "id": data.get("id", ""),
                    "item": item,
                    "category": category,
                    "checked": False,
                    "season_tip": "",
                }
        except RuntimeError as e:
            if getattr(e, "code", None) in (404, 403):
                # Fallback on main table
                fields = {
                    "Dépense": f"[Shopping] {item}",
                    "Date": date.today().strftime("%Y-%m-%d"),
                    "Catégorie": category if category in CATEGORIES else "Courses",
                    "Montant (€)": 0,
                    "Payé par": "Quentin",
                    "Dépense commune": False,
                    "Remboursement": "À acheter",
                    "Note": SHOPPING_MARK,
                }
                data = airtable_request("POST", f"{BASE_ID}/{urllib.parse.quote(TABLE)}", {"fields": fields, "typecast": True}) or {}
                return {
                    "id": data.get("id", ""),
                    "item": item,
                    "category": category,
                    "checked": False,
                    "season_tip": "",
                }
            raise
        except Exception:
            pass
    row = {"id": f"shop-{len(LOCAL_SHOPPING)+1}", "item": item, "category": category, "checked": False, "season_tip": ""}
    LOCAL_SHOPPING.append(row)
    return row


def toggle_shopping_item(item_id, checked=None):
    if TOKEN and BASE_ID:
        try:
            current = airtable_request("GET", f"{BASE_ID}/{urllib.parse.quote(SHOPPING_TABLE)}/{item_id}")
            if current and isinstance(current, dict):
                cur_val = bool(current.get("fields", {}).get("Acheté", False))
                new_val = not cur_val if checked is None else bool(checked)
                airtable_request("PATCH", f"{BASE_ID}/{urllib.parse.quote(SHOPPING_TABLE)}/{item_id}", {"fields": {"Acheté": new_val}})
                return new_val
        except RuntimeError as e:
            if getattr(e, "code", None) in (404, 403):
                # Fallback on main table
                current = airtable_request("GET", f"{BASE_ID}/{urllib.parse.quote(TABLE)}/{item_id}")
                if current and isinstance(current, dict):
                    fields = current.get("fields", {})
                    note = str(fields.get("Note", "") or "")
                    cur_val = "checked=true" in note or fields.get("Remboursement") == "Acheté"
                    new_val = not cur_val if checked is None else bool(checked)
                    new_note = f"{SHOPPING_MARK} checked={'true' if new_val else 'false'}"
                    new_status = "Acheté" if new_val else "À acheter"
                    airtable_request("PATCH", f"{BASE_ID}/{urllib.parse.quote(TABLE)}/{item_id}", {"fields": {"Note": new_note, "Remboursement": new_status}})
                    return new_val
            raise
        except Exception:
            pass
    for x in LOCAL_SHOPPING:
        if x["id"] == item_id:
            x["checked"] = not x["checked"] if checked is None else bool(checked)
            return x["checked"]
    return False


def delete_shopping_item(item_id):
    if TOKEN and BASE_ID:
        try:
            airtable_request("DELETE", f"{BASE_ID}/{urllib.parse.quote(SHOPPING_TABLE)}/{item_id}")
            return True
        except RuntimeError as e:
            if getattr(e, "code", None) in (404, 403):
                try:
                    airtable_request("DELETE", f"{BASE_ID}/{urllib.parse.quote(TABLE)}/{item_id}")
                    return True
                except Exception:
                    pass
            raise
        except Exception:
            pass
    global LOCAL_SHOPPING
    LOCAL_SHOPPING = [x for x in LOCAL_SHOPPING if x["id"] != item_id]
    return True


def analyze_shopping_with_ai(items_list, month_str=None, history_expenses=None):
    month_str = month_str or current_month()
    history_expenses = history_expenses or []
    
    recent_labels = [e.get("label", "") for e in history_expenses[-30:] if e.get("category") == "Courses"]
    
    prompt = (
        f"Mois : {month_str} (France).\n"
        f"Articles listés par Quentin & Jessica : {json.dumps(items_list, ensure_ascii=False) if items_list else '[]'}\n"
        f"Derniers achats : {json.dumps(recent_labels[:10], ensure_ascii=False)}\n\n"
        f"Profil nutritionnel : STRICTEMENT PRIMAL / ANIMAL-BASED (viandes grasses, abats/foie, poissons sauvages, œufs plein air, beurre cru/ghee, moelle, fromages lait cru, miel brut, fruits de saison bien mûrs. Pas de légumes sauf rares accompagnements, pas de graines/soja/huiles végétales).\n\n"
        f"Rédige ta réponse en respectant OBLIGATOIREMENT ces 4 sections avec leurs titres :\n\n"
        f"🥩 **1. Idées Menu Primal & Animal-Based (2 pers.)**\n"
        f"(2 à 3 propositions de repas denses, savoureux et rapides)\n\n"
        f"💶 **2. Estimation du Panier**\n"
        f"(Fourchette de prix estimée en € + conseil d'achat en volume/boucherie)\n\n"
        f"🏷️ **3. Optimisation Anti-Inflation & Bons Morceaux**\n"
        f"(Morceaux animaux ultra-nutritifs économiques et fruits de saison du mois)\n\n"
        f"🥫 **4. Pense-Bête Placard & Récurrences**\n"
        f"(2-3 indispensables primaux à vérifier)\n\n"
        f"Sois percutant, concis et motivant."
    )
    if QWEN_KEY:
        try:
            answer = qwen_chat(
                [
                    {"role": "system", "content": "Tu es le copilote nutritionnel Primal Animal-Based du foyer Quentin & Jessica. Réponds toujours en français structuré avec les 4 rubriques demandées."},
                    {"role": "user", "content": prompt}
                ],
                QWEN_MODEL
            )
            if answer and len(answer.strip()) > 30:
                return answer.strip()
        except Exception:
            pass
    return (
        f"🥩 **1. Menu Primal Hebdo** : Steaks hachés 15% & œufs au plat au beurre cru, Foie de veau saisi & tranches de pêches rôties au miel brut, Pavé de saumon ou sardines grillées.\n\n"
        f"💶 **2. Estimation du Panier** : ~45 € à 65 € selon le boucher/marché (pensez aux caissettes ou colis de viande pour réduire le prix au kilo).\n\n"
        f"🏷️ **3. Optimisation Anti-Inflation** : Foie de bœuf/veau (le super-aliment le moins cher du rayon), paleron/plat de côtes mijoté à la moelle, beurre de baratte au lait cru en motte.\n\n"
        f"🥫 **4. Pense-Bête Placard** : Sel de Guérande non raffiné, Beurre cru / Ghee, Œufs plein air (par 30), Miel brut non chauffé."
    )


def create_expense(item):
    item = dict(item)
    item["payer"] = display_payer(item.get("payer"))
    if TOKEN and BASE_ID:
        fields = {
            "Dépense": item["label"],
            "Date": item["date"],
            "Catégorie": item["category"],
            "Montant (€)": item["amount"],
            "Payé par": item["payer"],
            "Dépense commune": item.get("shared", True),
            "Remboursement": item.get("status", "À équilibrer"),
            "Note": item.get("note", ""),
        }
        data = airtable_request(
            "POST",
            f"{BASE_ID}/{urllib.parse.quote(TABLE)}",
            {"fields": fields, "typecast": True},
        )
        return normalize_expense(data.get("fields", fields), data.get("id", ""))
    item["id"] = "local-" + str(len(LOCAL_EXPENSES) + 1)
    item["is_budget"] = False
    item["is_shopping"] = False
    LOCAL_EXPENSES.insert(0, item)
    return item


def default_budgets(month):
    return [{"id": "", "category": cat, "month": month, "amount": 0.0} for cat in CATEGORIES]


SHOPPING_MARK = "kind=shopping"

def shopping_from_expense_records():
    found = []
    for row in get_all_records():
        note = str(row.get("note") or "")
        label = str(row.get("label") or "")
        if note.startswith(SHOPPING_MARK) or label.startswith("[Shopping]"):
            is_checked = "checked=true" in note or row.get("status") == "Acheté"
            item_name = label.replace("[Shopping]", "").strip() or "Article"
            found.append({
                "id": row.get("id"),
                "item": item_name,
                "category": row.get("category", "Courses"),
                "checked": is_checked,
                "season_tip": ""
            })
    return found
def budgets_from_expense_records(month):
    found = {}
    for row in get_all_records():
        if not row.get("is_budget"):
            continue
        row_month = str(row.get("date") or "")[:7]
        if row_month != month:
            continue
        found[row["category"]] = {
            "id": row["id"],
            "category": row["category"],
            "month": month,
            "amount": float(row.get("amount") or 0),
        }
    out = []
    for cat in CATEGORIES:
        out.append(found.get(cat, {"id": "", "category": cat, "month": month, "amount": 0.0}))
    return out


def get_budgets(month=None):
    month = month or current_month()
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise ValueError("Mois invalide")
    if TOKEN and BASE_ID:
        try:
            recs = list_table(BUDGET_TABLE) or []
            found = {}
            for rec in recs:
                fields = rec.get("fields", {})
                cat = fields.get("Catégorie")
                rec_month = str(fields.get("Mois") or "")[:7]
                if cat in CATEGORIES and rec_month == month:
                    found[cat] = {
                        "id": rec.get("id", ""),
                        "category": cat,
                        "month": month,
                        "amount": float(fields.get("Montant (€)", 0) or 0),
                    }
            return [
                found.get(cat, {"id": "", "category": cat, "month": month, "amount": 0.0})
                for cat in CATEGORIES
            ]
        except RuntimeError as e:
            if getattr(e, "code", None) not in (404, 403):
                raise
            return budgets_from_expense_records(month)
    local = [b for b in LOCAL_BUDGETS if b.get("month") == month]
    found = {b["category"]: b for b in local}
    return [found.get(cat, {"id": "", "category": cat, "month": month, "amount": 0.0}) for cat in CATEGORIES]


def upsert_budget(category, amount, month=None):
    month = month or current_month()
    if category not in CATEGORIES:
        raise ValueError("Catégorie inconnue")
    amount = round(float(amount), 2)
    if amount < 0:
        raise ValueError("Budget invalide")
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise ValueError("Mois invalide")
    if TOKEN and BASE_ID:
        try:
            recs = list_table(BUDGET_TABLE) or []
            existing = None
            for rec in recs:
                fields = rec.get("fields", {})
                if fields.get("Catégorie") == category and str(fields.get("Mois") or "")[:7] == month:
                    existing = rec
                    break
            payload = {"fields": {"Catégorie": category, "Mois": month, "Montant (€)": amount}, "typecast": True}
            if existing:
                data = airtable_request(
                    "PATCH",
                    f"{BASE_ID}/{urllib.parse.quote(BUDGET_TABLE)}/{existing['id']}",
                    payload,
                )
            else:
                data = airtable_request("POST", f"{BASE_ID}/{urllib.parse.quote(BUDGET_TABLE)}", payload)
            fields = data.get("fields", payload["fields"])
            return {
                "id": data.get("id", ""),
                "category": category,
                "month": month,
                "amount": float(fields.get("Montant (€)", amount) or amount),
            }
        except RuntimeError as e:
            if getattr(e, "code", None) not in (404, 403):
                raise
            current = {b["category"]: b for b in budgets_from_expense_records(month)}
            row = current.get(category) or {}
            fields = {
                "Dépense": f"[Budget] {category}",
                "Date": month + "-01",
                "Catégorie": category,
                "Montant (€)": amount,
                "Payé par": "Quentin",
                "Dépense commune": False,
                "Remboursement": "Budget",
                "Note": BUDGET_MARK,
            }
            if row.get("id"):
                data = airtable_request(
                    "PATCH",
                    f"{BASE_ID}/{urllib.parse.quote(TABLE)}/{row['id']}",
                    {"fields": fields, "typecast": True},
                )
            else:
                data = airtable_request(
                    "POST",
                    f"{BASE_ID}/{urllib.parse.quote(TABLE)}",
                    {"fields": fields, "typecast": True},
                )
            return {
                "id": data.get("id", ""),
                "category": category,
                "month": month,
                "amount": amount,
            }
    existing = next((b for b in LOCAL_BUDGETS if b["category"] == category and b["month"] == month), None)
    if existing:
        existing["amount"] = amount
        return existing
    item = {"id": "budget-" + str(len(LOCAL_BUDGETS) + 1), "category": category, "month": month, "amount": amount}
    LOCAL_BUDGETS.append(item)
    return item


def month_expenses(expenses, month):
    return [x for x in expenses if str(x.get("date") or "").startswith(month)]


def envelope_view(expenses, budgets, month):
    spent = {cat: 0.0 for cat in CATEGORIES}
    for row in month_expenses(expenses, month):
        if row.get("shared", True):
            spent[row.get("category", "Autres")] = spent.get(row.get("category", "Autres"), 0.0) + float(row.get("amount") or 0)
    envelopes = []
    for b in budgets:
        cap = float(b.get("amount") or 0)
        use = round(spent.get(b["category"], 0.0), 2)
        envelopes.append({
            "category": b["category"],
            "budget": cap,
            "spent": use,
            "remaining": None if cap <= 0 else round(cap - use, 2),
            "ratio": None if cap <= 0 else round(use / cap, 3),
            "status": "unset" if cap <= 0 else ("over" if use > cap else "ok"),
        })
    return envelopes


def finance_context(expenses, month=None):
    month = month or current_month()
    budgets = get_budgets(month)
    scoped = month_expenses(expenses, month)
    shared = [x for x in scoped if x.get("shared", True)]
    total = sum(float(x.get("amount", 0) or 0) for x in shared)
    by_payer = {
        p: sum(float(x.get("amount", 0) or 0) for x in shared if x.get("payer") == p)
        for p in PAYERS
    }
    by_cat = {}
    for x in shared:
        cat = x.get("category", "Autres")
        by_cat[cat] = by_cat.get(cat, 0) + float(x.get("amount", 0) or 0)
    due = abs(by_payer["Quentin"] - by_payer["Jessica"]) / 2
    recent = sorted(shared, key=lambda x: str(x.get("date", "")), reverse=True)[:12]
    envelopes = envelope_view(expenses, budgets, month)
    return {
        "month": month,
        "people": list(PAYERS),
        "count": len(shared),
        "total": round(total, 2),
        "by_payer": {k: round(v, 2) for k, v in by_payer.items()},
        "by_category": {k: round(v, 2) for k, v in by_cat.items()},
        "balance_to_adjust": round(due, 2),
        "who_should_cover": (
            "Jessica" if by_payer["Quentin"] > by_payer["Jessica"]
            else "Quentin" if by_payer["Jessica"] > by_payer["Quentin"]
            else None
        ),
        "share_model": "parts égales",
        "envelopes": envelopes,
        "recent_expenses": [
            {
                "date": x.get("date", ""),
                "label": x.get("label", ""),
                "category": x.get("category", ""),
                "amount": x.get("amount", 0),
                "payer": x.get("payer", ""),
            }
            for x in recent
        ],
    }


def deterministic_answer(q, ctx):
    total = ctx["total"]
    pay = ctx["by_payer"]
    if "budget" in q or "enveloppe" in q or "repère" in q or "repere" in q:
        unset = [e["category"] for e in ctx["envelopes"] if e["status"] == "unset"]
        over = [e for e in ctx["envelopes"] if e["status"] == "over"]
        if unset and not any(e["budget"] > 0 for e in ctx["envelopes"]):
            return "Aucun budget n'est encore fixé pour ce mois. Dites-moi un plafond par catégorie, je vous le proposerai à confirmer."
        if over:
            bits = ", ".join(f"{e['category']} ({e['spent']:.2f} € sur {e['budget']:.2f} €)" for e in over)
            return f"Au-delà du budget : {bits}."
        return "Les enveloppes fixées tiennent pour le moment."
    if not total:
        return "Aucune dépense n'est encore enregistrée ce mois-ci pour Quentin et Jessica."
    if any(w in q for w in ("équilibr", "rembour", "doit", "doivent", "répart", "repart")):
        if ctx["balance_to_adjust"] < 0.01:
            return "Les contributions de Quentin et Jessica sont parfaitement alignées ce mois-ci."
        higher = "Quentin" if pay["Quentin"] > pay["Jessica"] else "Jessica"
        lower = "Jessica" if higher == "Quentin" else "Quentin"
        return f"Sur ce mois, {higher} a avancé {pay[higher]:.2f} € et {lower} {pay[lower]:.2f} € (écart d'environ {ctx['balance_to_adjust']:.2f} € pour information, sans obligation d'équilibrer)."
    if any(w in q for w in ("résumé", "resume", "situation", "état", "etat", "point")):
        return (
            f"Point d'étape en {ctx['month']} : {ctx['count']} dépenses communes pour un total de {total:.2f} €. "
            f"Quentin a avancé {pay['Quentin']:.2f} € et Jessica {pay['Jessica']:.2f} €."
        )
    return "Je peux analyser les dépenses, lire un ticket ou faire le point sur vos enveloppes du mois."


def sanitize_image(image):
    if not image or not isinstance(image, str):
        return None
    image = image.strip()
    if not image.startswith("data:image/"):
        return None
    if len(image) > MAX_IMAGE_CHARS:
        raise ValueError("Image trop lourde. Envoyez une photo plus légère.")
    if ";base64," not in image:
        return None
    return image


def parse_json_blob(text, key):
    match = re.search(re.escape(key) + r"\s*(\{.*?\})", text, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None


def parse_suggestion(text):
    raw = parse_json_blob(text, "SUGGESTION_JSON")
    if not raw:
        match = re.search(r"(\{\s*\"(?:label|amount|merchant)\"\s*:.*?\})", text, re.S)
        if not match:
            return None
        try:
            raw = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    try:
        amount = float(str(raw.get("amount", "")).replace(",", ".").replace("€", "").strip())
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    label = str(raw.get("label") or raw.get("merchant") or "").strip()[:80]
    if not label:
        return None
    category = raw.get("category") if raw.get("category") in CATEGORIES else "Autres"
    payer = display_payer(raw.get("payer"))
    day = str(raw.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        day = ""
    return {
        "label": label,
        "amount": round(amount, 2),
        "date": day,
        "category": category,
        "payer": payer,
        "shared": True,
        "status": "À équilibrer",
        "note": str(raw.get("note") or "Ticket lu par l'assistant").strip()[:160],
        "confidence": raw.get("confidence") if raw.get("confidence") in ("high", "medium", "low") else "medium",
    }


def parse_budget_suggestion(text, month):
    raw = parse_json_blob(text, "BUDGET_JSON")
    if not raw:
        return None
    category = raw.get("category")
    if category not in CATEGORIES:
        return None
    try:
        amount = float(str(raw.get("amount", "")).replace(",", ".").replace("€", "").strip())
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    rec_month = str(raw.get("month") or month)[:7]
    if not re.match(r"^\d{4}-\d{2}$", rec_month):
        rec_month = month
    return {
        "category": category,
        "amount": round(amount, 2),
        "month": rec_month,
        "reason": str(raw.get("reason") or "").strip()[:180],
    }


def parse_fr_amount(value):
    """« 1 234,56 EUR » / « -12.30 » -> float arrondi (ou None)."""
    raw = str(value or "").replace("\u20ac", "").replace("EUR", "").replace(" ", "").replace("\u00a0", "").strip()
    if not raw:
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return round(float(match.group(0)), 2)
    except ValueError:
        return None


def sanitize_document(doc):
    if not doc or not isinstance(doc, dict):
        return None
    name = re.sub(r"[^\w.\- ()]", "_", str(doc.get("name") or "releve"))[:120]
    data = str(doc.get("data") or "")
    if ";base64," not in data:
        return None
    if len(data) > MAX_DOC_CHARS:
        raise ValueError("Fichier trop lourd (3 Mo max). Utilisez le CSV de la banque.")
    return {"name": name or "releve", "data": data}


def extract_document_text(doc):
    """(texte, kind) depuis un document data-URL : PDF (pypdf) ou CSV/TXT."""
    name = str(doc.get("name") or "").lower()
    try:
        blob = base64.b64decode(doc["data"].split(";base64,", 1)[1], validate=False)
    except Exception:
        raise ValueError("Fichier illisible (encodage inattendu).")
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except Exception:
            raise ValueError("Lecture PDF indisponible pour le moment. Envoyez plutot le CSV de la banque.")
        try:
            reader = PdfReader(io.BytesIO(blob))
            pages = [(page.extract_text() or "") for page in reader.pages[:15]]
        except Exception:
            raise ValueError("Impossible d'ouvrir ce PDF (protege ?). Essayez le CSV de la banque.")
        text = "\n".join(pages)
        if len(text.strip()) < 40:
            raise ValueError("Ce PDF est un scan sans texte. Envoyez une photo du releve ou le CSV.")
        return text, "pdf"
    if name.endswith((".csv", ".txt", ".tsv")):
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return blob.decode(enc), "csv"
            except UnicodeDecodeError:
                continue
        raise ValueError("Encodage du fichier non reconnu. Exportez le releve en CSV UTF-8.")
    raise ValueError("Format non pris en charge : joignez un PDF ou un CSV de releve.")


def parse_json_array(text, key):
    match = re.search(re.escape(key) + r"\s*(\[.*\])", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _iso_days_apart(a, b):
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except Exception:
        return None


def _label_similarity(a, b):
    left = re.sub(r"[^a-z0-9]", "", str(a or "").lower())
    right = re.sub(r"[^a-z0-9]", "", str(b or "").lower())
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _normalize_statement_op(raw, month):
    if not isinstance(raw, dict):
        return None
    amount = parse_fr_amount(raw.get("amount"))
    if amount is None or amount <= 0:
        return None
    label = str(raw.get("label") or raw.get("merchant") or "").strip()[:90]
    if not label:
        return None
    day = str(raw.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        match = re.match(r"^(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?$", day)
        if not match:
            return None
        dd, mm, yy = match.group(1), match.group(2), match.group(3)
        year = str(month)[:4] if not yy else (yy if len(yy) == 4 else "20" + yy)
        day = "%s-%02d-%02d" % (year, int(mm), int(dd))
    direction = "debit" if str(raw.get("direction") or "debit").lower().startswith("deb") else "credit"
    category = raw.get("category") if raw.get("category") in CATEGORIES else "Autres"
    confidence = raw.get("confidence") if raw.get("confidence") in ("high", "medium", "low") else "medium"
    question = str(raw.get("question") or "").strip()[:140]
    if direction == "debit" and category == "Autres" and not question:
        question = "À quoi correspond « %s » ?" % label[:40]
    return {
        "date": day,
        "label": label,
        "amount": round(amount, 2),
        "direction": direction,
        "category": category,
        "confidence": confidence,
        "question": question,
        "duplicate": False,
    }


def _statement_ops_fallback(text):
    """Parseur sans IA : lignes date + libelle + montant, facon releve FR."""
    out = []
    date_re = re.compile(r"\b(\d{2})[/.\-](\d{2})(?:[/.\-](\d{2,4}))?\b")
    amount_re = re.compile(r"(-?\s?\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{2}))\s*(?:\u20ac|EUR)?\s*$")
    credit_words = ("virement recu", "virement re\u00e7u", "salaire", "remboursement", "avoir", "depot", "d\u00e9p\u00f4t", "versement")
    debit_words = ("d\u00e9bit", "debit", "prlv", "pr\u00e9l\u00e8vement", "prelevement", "achat", "retrait", "cb ", "carte")
    for raw_line in (text or "").splitlines():
        line = re.sub(r"[;|]\s*", " ", raw_line).strip()
        if len(line) < 10:
            continue
        m_date = date_re.search(line)
        m_amount = amount_re.search(line)
        if not m_date or not m_amount:
            continue
        amount = parse_fr_amount(m_amount.group(1))
        if amount is None or amount == 0:
            continue
        negated = "-" in m_amount.group(1)
        body = re.sub(r"\s{2,}", " ", line[m_date.end():m_amount.start()].strip(" .:-|+;,"))[:90]
        if not body:
            continue
        low = body.lower()
        if low.startswith(("solde", "ancien solde", "nouveau solde", "total", "sous-total", "cumul")):
            continue
        if any(w in low for w in credit_words) and not negated:
            direction = "credit"
        elif negated or any(w in low for w in debit_words):
            direction = "debit"
        else:
            direction = "credit"
        yy = m_date.group(3)
        year = yy if (yy and len(yy) == 4) else ("20" + yy if yy else str(date.today().year))
        out.append({
            "date": "%s-%s-%s" % (year, m_date.group(2), m_date.group(1)),
            "label": body,
            "amount": abs(amount),
            "direction": direction,
            "category": "Autres",
            "confidence": "low",
            "question": "",
        })
    return out


def _statement_ops_with_ai(text, month, hint=""):
    prompt = (
        "Voici le texte d'un releve de compte bancaire francais. Extrais TOUTES les operations, sans en inventer.\n"
        "Reponds STRICTEMENT avec un tableau JSON prefixe par IMPORT_JSON:\n"
        'IMPORT_JSON [{"date":"AAAA-MM-JJ","label":"libelle lisible","amount":12.34,"direction":"debit|credit","category":"Courses","confidence":"high|medium|low","question":""}]\n'
        "- category doit etre une de : " + ", ".join(CATEGORIES) + ".\n"
        "- Si l'annee manque, prends " + str(month)[:4] + ". Montants toujours positifs, en euros.\n"
        "- Si un libelle est cryptique (PRLV SEPA sans nom, CB 4532, XXXX), mets category \"Autres\", confidence \"low\" et une question courte : a quoi correspond cette depense ?\n"
        "- Ignore soldes, totaux, pagination, interets techniques. Si rien d'exploitable : IMPORT_JSON []\n"
    )
    if hint:
        prompt += "Consigne de l'utilisateur : " + str(hint)[:300] + "\n"
    prompt += "\nTEXTE DU RELEVE:\n" + str(text)[:55000]
    answer = qwen_chat(
        [
            {"role": "system", "content": "Tu extrais des operations bancaires et tu reponds uniquement avec IMPORT_JSON."},
            {"role": "user", "content": prompt},
        ],
        QWEN_MODEL,
        max_tokens=1800,
    )
    return parse_json_array(answer, "IMPORT_JSON")


def _find_duplicate(op, expenses):
    for row in expenses or []:
        try:
            if abs(float(row.get("amount") or 0) - float(op["amount"])) > 0.011:
                continue
        except (TypeError, ValueError):
            continue
        days = _iso_days_apart(row.get("date"), op.get("date"))
        if days is not None and days > 4:
            continue
        same_day = str(row.get("date") or "")[:10] == op.get("date")
        if _label_similarity(row.get("label"), op.get("label")) >= 0.45 or same_day:
            return row
    return None


def analyze_statement(text, expenses, month, filename="", hint=""):
    raw_ops, engine = None, "rules"
    if QWEN_KEY:
        try:
            raw_ops = _statement_ops_with_ai(text, month, hint)
            if raw_ops is not None:
                engine = "qwen"
        except Exception:
            raw_ops = None
    if raw_ops is None:
        raw_ops = _statement_ops_fallback(text)
    operations = []
    for raw in raw_ops or []:
        norm = _normalize_statement_op(raw, month)
        if norm:
            operations.append(norm)
    for op in operations:
        if op["direction"] == "debit":
            match = _find_duplicate(op, expenses)
            if match:
                op["duplicate"] = True
                op["matched"] = {"id": match.get("id"), "label": match.get("label"), "date": match.get("date")}
    debits = [o for o in operations if o["direction"] == "debit"]
    credits = [o for o in operations if o["direction"] != "debit"]
    fresh = [o for o in debits if not o.get("duplicate")]
    return {
        "engine": engine,
        "file": filename,
        "month": month,
        "operations": operations,
        "summary": {
            "total": len(operations),
            "debits": len(debits),
            "credits": len(credits),
            "duplicates": len(debits) - len(fresh),
            "to_import": len(fresh),
            "amount": round(sum(o["amount"] for o in fresh), 2),
            "questions": sum(1 for o in debits if o.get("question")),
        },
    }


def create_expenses_batch(items):
    created = []
    if TOKEN and BASE_ID:
        records = []
        for item in items:
            records.append({"fields": {
                "Dépense": item["label"],
                "Date": item["date"],
                "Catégorie": item["category"],
                "Montant (€)": float(item["amount"]),
                "Payé par": display_payer(item.get("payer")),
                "Dépense commune": bool(item.get("shared", True)),
                "Remboursement": item.get("status", "À équilibrer"),
                "Note": item.get("note", ""),
            }})
        for i in range(0, len(records), 10):
            data = airtable_request(
                "POST",
                f"{BASE_ID}/{urllib.parse.quote(TABLE)}",
                {"records": records[i:i+10], "typecast": True},
            )
            for rec in (data or {}).get("records", []):
                created.append(normalize_expense(rec.get("fields", {}), rec.get("id", "")))
        return created
    for item in items:
        created.append(create_expense(item))
    return created


def qwen_chat(messages, model, max_tokens=900):
    # If the env has the legacy slow qwen model, use google/gemini-2.5-flash for ultra fast and clean answers
    actual_model = "google/gemini-2.5-flash" if ("qwen" in model and "vl" not in model) else model
    payload = {
        "model": actual_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        QWEN_BASE.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": "Bearer " + QWEN_KEY,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://notitia-finances.vercel.app",
            "X-Title": "Notitia Finance",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read())
    msg = data["choices"][0]["message"]
    content = msg.get("content")
    if isinstance(content, list):
        content = " ".join(str(part.get("text", part) if isinstance(part, dict) else part) for part in content)
    content = (content or "").strip()
    if not content:
        content = extract_french(str(msg.get("reasoning") or ""))
    if not content:
        raise RuntimeError("Réponse Qwen vide")
    return content


def extract_french(text):
    draft = re.search(
        r"(?:Draft Response|Mental Refinement|Réponse(?: finale)?)[^\n]*:\s*(.+?)(?:\n\s*\d+\.|\n\s*\*\*|$)",
        text,
        re.S | re.I,
    )
    source = draft.group(1) if draft else text
    sentences = re.findall(r"[^.!?\n]*[àâçéèêëîïôùûüœÀÂÇÉÈÊËÎÏÔÙÛÜŒ][^.!?\n]*[.!?]", source)
    useful = [s.strip() for s in sentences if len(s.strip()) > 20]
    if useful:
        return " ".join(useful[:6])
    return ""


def clean_answer(text):
    text = re.sub(r"\s*(SUGGESTION_JSON|BUDGET_JSON)\s*\{.*?\}", "", text, flags=re.S).strip()
    return text.strip()


def assistant_answer(question, expenses, image=None, month=None):
    month = month or current_month()
    ctx = finance_context(expenses, month)
    user_text = (
        "Contexte du foyer, seule source de chiffres:\n"
        + json.dumps(ctx, ensure_ascii=False)
        + "\n\nQuestion: "
        + (question or "Analyse ce justificatif et dis-moi ce qu'il faut en retenir.")
        + "\nSi une image est jointe, termine par:\n"
        + 'SUGGESTION_JSON {"label":"...","amount":12.5,"date":"2026-08-14","category":"Courses","payer":"Quentin","confidence":"medium","note":"..."}\n'
        + "Si tu proposes un ajustement de budget, ajoute:\n"
        + 'BUDGET_JSON {"category":"Courses","amount":180,"month":"'
        + month
        + '","reason":"..."}\n'
        + "N'applique rien toi-même."
    )
    if QWEN_KEY:
        try:
            content = [{"type": "text", "text": user_text}]
            model = QWEN_MODEL
            if image:
                content.append({"type": "image_url", "image_url": {"url": image}})
                model = QWEN_VISION_MODEL
            answer = qwen_chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content if image else user_text},
                ],
                model,
            )
            return (
                clean_answer(answer),
                "qwen",
                parse_suggestion(answer),
                parse_budget_suggestion(answer, month),
                ctx,
            )
        except Exception:
            if image:
                return (
                    "Je n'ai pas pu lire cette image pour le moment. Vous pouvez saisir la dépense à la main.",
                    "rules",
                    None,
                    None,
                    ctx,
                )
            return deterministic_answer((question or "").lower(), ctx), "rules", None, None, ctx
    return deterministic_answer((question or "").lower(), ctx), "rules", None, None, ctx


APP_CODE_PEPPER = "duospend-v1"
# Un code par personne : sha256(pepper|code en minuscules). Rotation via duospend_code_set.py.
APP_CODES = {
    "Quentin": "71f8d5186ce501af616ba82497b8a453b6e7d23707154fc9677efd67798fb658",
    "Jessica": "3547b4447d0fcdc07d7878cf78c711dbf1232fad1e2e60e2a3436985ed9bf976",
}
# Code foyer historique : accès réduit, dépenses communes uniquement (pas de mode perso).
APP_CODE_HASH = "25136f449fe4d380e451c5e05c9cea2f055c98e023511f80531f5931b662e155"
USERS = tuple(APP_CODES)
_AUTH_FAILS = {}


def code_digest(raw):
    import hashlib
    return hashlib.sha256((APP_CODE_PEPPER + "|" + str(raw).strip().lower()).encode()).hexdigest()


def user_for_code(raw):
    """Identifie qui se connecte : 'Quentin', 'Jessica', 'Foyer' (code collectif) ou None."""
    import hmac
    if not raw:
        return None
    digest = code_digest(raw)
    for user, hashed in APP_CODES.items():
        if hashed and hmac.compare_digest(digest, hashed):
            return user
    if APP_CODE_HASH and hmac.compare_digest(digest, APP_CODE_HASH):
        return "Foyer"
    return None


def app_code_ok(raw):
    return user_for_code(raw) is not None


def visible_expenses(expenses, user):
    """Ce que l'utilisateur voit : les dépenses communes + les siennes, jamais celles de l'autre."""
    if user in USERS:
        return [e for e in expenses if e.get("shared", True) or e.get("payer") == user]
    return [e for e in expenses if e.get("shared", True)]


def shared_only(expenses):
    return [e for e in expenses if e.get("shared", True)]


def auth_fail_register(ip):
    import time
    now = time.time()
    cnt, first = _AUTH_FAILS.get(ip, (0, now))
    if now - first > 900:
        cnt, first = 0, now
    _AUTH_FAILS[ip] = (cnt + 1, first)


def auth_blocked(ip):
    import time
    rec = _AUTH_FAILS.get(ip)
    if not rec:
        return False
    cnt, first = rec
    if time.time() - first > 900:
        _AUTH_FAILS.pop(ip, None)
        return False
    return cnt >= 12


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".json": "application/json",
        ".png": "image/png",
        ".svg": "image/svg+xml",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)
        self.app_user = None

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", PUBLIC_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-App-Code")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        super().end_headers()

    def send_json(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Robots-Tag", "noindex")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 4_500_000:
            raise ValueError("Requête trop volumineuse")
        return json.loads(self.rfile.read(n) or b"{}")

    def query(self):
        if "?" not in self.path:
            return {}
        return dict(urllib.parse.parse_qsl(self.path.split("?", 1)[1]))

    def client_ip(self):
        fwd = self.headers.get("x-forwarded-for") or ""
        return (fwd.split(",")[0].strip() or (self.client_address[0] if self.client_address else "?"))

    def require_code(self):
        ip = self.client_ip()
        if auth_blocked(ip):
            self.send_json(429, {"error": "Trop de tentatives, réessayez plus tard", "code_required": True})
            return False
        user = user_for_code(self.headers.get("X-App-Code"))
        if user:
            self.app_user = user
            _AUTH_FAILS.pop(ip, None)
            return True
        auth_fail_register(ip)
        self.send_json(401, {"error": "Code d'accès requis", "code_required": True})
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            return self.send_json(
                200,
                {
                    "ok": True,
                    "mode": "airtable" if TOKEN and BASE_ID else "local-empty",
                    "baseConfigured": bool(TOKEN and BASE_ID),
                    "assistant": "qwen" if QWEN_KEY else "rules",
                    "vision": bool(QWEN_KEY),
                    "people": list(PAYERS),
                },
            )
        if path.startswith("/api/") and not self.require_code():
            return
        if path in ("/api/state", "/api/expenses", "/api/budgets", "/api/shopping"):
            try:
                month = self.query().get("month") or current_month()
                expenses = visible_expenses(get_expenses(), self.app_user)
                budgets = get_budgets(month)
                shopping = get_shopping()
                ctx = finance_context(shared_only(expenses), month)
                if path == "/api/expenses":
                    return self.send_json(200, {"expenses": expenses, "user": self.app_user})
                if path == "/api/budgets":
                    return self.send_json(200, {"month": month, "budgets": budgets, "envelopes": ctx["envelopes"]})
                if path == "/api/shopping":
                    return self.send_json(200, {"shopping": shopping})
                return self.send_json(
                    200,
                    {"month": month, "user": self.app_user, "users": list(USERS), "expenses": expenses, "budgets": budgets, "envelopes": ctx["envelopes"], "shopping": shopping, "facts": ctx},
                )
            except Exception as e:
                return self.send_json(502, {"error": "Données indisponibles", "detail": str(e)})
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/") and not self.require_code():
            return
        if path == "/api/assistant":
            try:
                body = self.read_json()
                question = str(body.get("question", "")).strip()
                image = sanitize_image(body.get("image"))
                month = str(body.get("month") or current_month())[:7]
                if not question and not image:
                    return self.send_json(400, {"error": "Question ou image requise"})
                answer, engine, suggestion, budget, ctx = assistant_answer(question, visible_expenses(get_expenses(), self.app_user), image, month)
                return self.send_json(
                    200,
                    {
                        "answer": answer,
                        "engine": engine,
                        "suggestion": suggestion,
                        "budget": budget,
                        "facts": ctx,
                    },
                )
            except Exception as e:
                return self.send_json(400, {"error": "Question invalide", "detail": str(e)})
        if path == "/api/import/analyze":
            try:
                body = self.read_json()
                doc = sanitize_document(body.get("document"))
                if not doc:
                    return self.send_json(400, {"error": "Fichier requis (PDF ou CSV)."})
                month = str(body.get("month") or current_month())[:7]
                if not re.match(r"^\d{4}-\d{2}$", month):
                    month = current_month()
                hint = str(body.get("question") or "").strip()
                text, kind = extract_document_text(doc)
                result = analyze_statement(text, visible_expenses(get_expenses(), self.app_user), month, doc["name"], hint)
                result["kind"] = kind
                return self.send_json(200, result)
            except Exception as e:
                return self.send_json(400, {"error": str(e) or "Analyse du releve impossible"})
        if path == "/api/import/commit":
            try:
                body = self.read_json()
                items = body.get("items")
                if not isinstance(items, list) or not items:
                    return self.send_json(400, {"error": "Aucune operation a importer"})
                clean = []
                for raw in items[:120]:
                    if not isinstance(raw, dict):
                        raise ValueError("Operation invalide")
                    for key in ("date", "label", "category", "amount"):
                        if key not in raw:
                            raise ValueError("Champ manquant: " + key)
                    amount = float(raw["amount"])
                    if amount <= 0:
                        raise ValueError("Montant invalide")
                    day = str(raw["date"])[:10]
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
                        raise ValueError("Date invalide: " + day)
                    clean.append({
                        "date": day,
                        "label": str(raw["label"]).strip()[:120],
                        "category": raw["category"] if raw["category"] in CATEGORIES else "Autres",
                        "amount": round(amount, 2),
                        "payer": display_payer(raw.get("payer") or (self.app_user if self.app_user in USERS else "Quentin")),
                        "shared": bool(raw.get("shared", True)),
                        "status": str(raw.get("status") or "À équilibrer")[:40],
                        "note": str(raw.get("note") or "")[:240],
                    })
                created = create_expenses_batch(clean)
                return self.send_json(201, {"created": created, "count": len(created), "expenses": get_expenses()})
            except Exception as e:
                return self.send_json(400, {"error": "Import impossible", "detail": str(e)})
        if path == "/api/budgets":
            try:
                body = self.read_json()
                item = upsert_budget(body.get("category"), body.get("amount"), body.get("month"))
                month = item["month"]
                expenses = get_expenses()
                budgets = get_budgets(month)
                return self.send_json(
                    200,
                    {"budget": item, "budgets": budgets, "envelopes": envelope_view(expenses, budgets, month)},
                )
            except Exception as e:
                return self.send_json(400, {"error": "Budget invalide", "detail": str(e)})
        if path == "/api/shopping/analyze":
            try:
                body = self.read_json()
                items = body.get("items") or [x.get("item") for x in get_shopping()]
                month = str(body.get("month") or current_month())[:7]
                analysis = analyze_shopping_with_ai(items, month, get_expenses())
                return self.send_json(200, {"analysis": analysis, "month": month})
            except Exception as e:
                return self.send_json(400, {"error": "Analyse impossible", "detail": str(e)})
        if path == "/api/shopping":
            try:
                body = self.read_json()
                action = body.get("action", "add")
                if action == "add":
                    item = add_shopping_item(body.get("item"), body.get("category", "Courses"))
                    return self.send_json(201, {"item": item, "shopping": get_shopping()})
                if action == "toggle":
                    toggle_shopping_item(body.get("id"), body.get("checked"))
                    return self.send_json(200, {"shopping": get_shopping()})
                if action == "delete":
                    delete_shopping_item(body.get("id"))
                    return self.send_json(200, {"shopping": get_shopping()})
                return self.send_json(400, {"error": "Action inconnue"})
            except Exception as e:
                return self.send_json(400, {"error": "Opération shopping impossible", "detail": str(e)})
        if path == "/api/expenses/clear":
            try:
                count = clear_all_expenses()
                return self.send_json(200, {"ok": True, "deleted": count, "expenses": get_expenses()})
            except Exception as e:
                return self.send_json(500, {"error": "Erreur suppression", "detail": str(e)})
        if path == "/api/expenses/delete":
            try:
                body = self.read_json()
                rid = body.get("id")
                if not rid:
                    return self.send_json(400, {"error": "ID manquant"})
                delete_expense(rid)
                return self.send_json(200, {"ok": True, "expenses": get_expenses()})
            except Exception as e:
                return self.send_json(500, {"error": "Erreur suppression", "detail": str(e)})
        if path == "/api/expenses/update":
            try:
                body = self.read_json()
                rid = body.get("id")
                if not rid:
                    return self.send_json(400, {"error": "ID manquant"})
                update_expense(rid, body)
                return self.send_json(200, {"ok": True, "expenses": get_expenses()})
            except Exception as e:
                return self.send_json(500, {"error": "Erreur mise à jour", "detail": str(e)})
        if path != "/api/expenses":
            return self.send_json(404, {"error": "Not found"})
        try:
            item = self.read_json()
            for key in ("date", "label", "category", "amount", "payer"):
                if key not in item:
                    raise ValueError(f"Champ manquant: {key}")
            item["amount"] = float(item["amount"])
            if item["amount"] <= 0:
                raise ValueError("Montant invalide")
            item.setdefault("shared", True)
            item.setdefault("status", "À équilibrer")
            item.setdefault("note", "")
            if item.get("category") not in CATEGORIES:
                item["category"] = "Autres"
            item["payer"] = display_payer(item.get("payer"))
            return self.send_json(201, {"expense": create_expense(item)})
        except Exception as e:
            return self.send_json(400, {"error": "Dépense invalide", "detail": str(e)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8787"))
    host = os.getenv("HOST", "0.0.0.0")
    mode = "Airtable" if TOKEN and BASE_ID else "local-empty"
    print(f"Notitia Finances: http://{host}:{port} ({mode})", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
