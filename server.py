import json, os, re, urllib.error, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).parent
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "*")
BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appEGVy9MVBGYmPQT")
TABLE = os.getenv("AIRTABLE_TABLE", "Dépenses")
TOKEN = os.getenv("AIRTABLE_API_KEY", "")
LOCAL_EXPENSES = []
QWEN_KEY = os.getenv("QWEN_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen/qwen-2.5-72b-instruct")
QWEN_VISION_MODEL = os.getenv("QWEN_VISION_MODEL", "qwen/qwen2.5-vl-72b-instruct")
QWEN_BASE = os.getenv("QWEN_BASE_URL", "https://openrouter.ai/api/v1")
MAX_IMAGE_CHARS = 3_500_000
CATEGORIES = ("Courses", "Logement", "Transport", "Sorties", "Abonnements", "Santé", "Autres")
PAYERS = ("Quentin", "Partenaire")

SYSTEM_PROMPT = """Tu es le conseiller financier de Notitia, pour un couple.
Réponds en français, de façon claire, humaine et concise.
Tu n'es pas un conseiller agréé. Tu aides à comprendre les dépenses communes, jamais à investir, emprunter ou ouvrir un produit bancaire.
Règles:
- Utilise uniquement le contexte JSON et, le cas échéant, le ticket photo.
- Ne fabrique aucun revenu, aucune dépense, aucun solde.
- Distingue clairement les faits, les calculs et les suggestions.
- Si les données manquent, dis-le clairement en 4 à 8 phrases.
- N'explique pas ton raisonnement interne. Réponds uniquement au couple, jamais en anglais technique.
- Les suggestions de répartition sont à parts égales, sauf si le couple en a décidé autrement.
- Si une image de ticket est fournie, extrais seulement ce qui est lisible: enseigne, date, montant, catégorie probable.
- Ne crée jamais une dépense tout seul: propose-la, l'humain confirme.
- Ton utile: voir ensemble, comprendre ensemble, décider ensemble."""


def airtable_request(method="GET", path="", payload=None):
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
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Airtable {e.code}: {body}") from None


def normalize(fields, rid):
    return {
        "id": rid,
        "date": fields.get("Date", ""),
        "label": fields.get("Dépense", ""),
        "category": fields.get("Catégorie", "Autres"),
        "amount": float(fields.get("Montant (€)", 0) or 0),
        "payer": fields.get("Payé par", "Quentin"),
        "shared": bool(fields.get("Dépense commune", True)),
        "status": fields.get("Remboursement", "À équilibrer"),
        "note": fields.get("Note", ""),
    }


def get_expenses():
    if TOKEN and BASE_ID:
        data = airtable_request("GET", f"{BASE_ID}/{urllib.parse.quote(TABLE)}?pageSize=100") or {}
        return [normalize(r.get("fields", {}), r.get("id")) for r in data.get("records", [])]
    return LOCAL_EXPENSES


def create_expense(item):
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
        return normalize(data.get("fields", fields), data.get("id", ""))
    item["id"] = "local-" + str(len(LOCAL_EXPENSES) + 1)
    LOCAL_EXPENSES.insert(0, item)
    return item


def finance_context(expenses):
    shared = [x for x in expenses if x.get("shared", True)]
    total = sum(float(x.get("amount", 0) or 0) for x in shared)
    by_payer = {
        p: sum(float(x.get("amount", 0) or 0) for x in shared if x.get("payer") == p)
        for p in PAYERS
    }
    by_cat = {}
    for x in shared:
        cat = x.get("category", "Autres")
        by_cat[cat] = by_cat.get(cat, 0) + float(x.get("amount", 0) or 0)
    due = abs(by_payer["Quentin"] - by_payer["Partenaire"]) / 2
    recent = sorted(shared, key=lambda x: str(x.get("date", "")), reverse=True)[:12]
    return {
        "count": len(shared),
        "total": round(total, 2),
        "by_payer": {k: round(v, 2) for k, v in by_payer.items()},
        "by_category": {k: round(v, 2) for k, v in by_cat.items()},
        "balance_to_adjust": round(due, 2),
        "who_should_cover": (
            "Partenaire" if by_payer["Quentin"] > by_payer["Partenaire"]
            else "Quentin" if by_payer["Partenaire"] > by_payer["Quentin"]
            else None
        ),
        "share_model": "parts égales",
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
    cats = ctx["by_category"]
    pay = ctx["by_payer"]
    if not total:
        return "Aucune dépense réelle n'est encore enregistrée. Ajoutez un ticket ou une ligne pour que je puisse analyser la situation."
    if any(w in q for w in ("équilibr", "rembour", "doit", "doivent")):
        if ctx["balance_to_adjust"] < 0.01:
            return "Les contributions sont actuellement équilibrées sur les dépenses communes disponibles."
        who = ctx["who_should_cover"] or "le partenaire le moins avancé"
        return f"Pour une répartition à parts égales, {who} devrait prendre en charge environ {ctx['balance_to_adjust']:.2f} € sur les prochaines dépenses communes."
    if any(w in q for w in ("catégorie", "categorie", "poste", "où", "ou")) and cats:
        k, v = max(cats.items(), key=lambda item: item[1])
        return f"Le poste le plus élevé est {k}, avec {v:.2f} €, soit {round(v / total * 100) if total else 0} % du total commun."
    if any(w in q for w in ("résumé", "resume", "situation", "état", "etat", "conseil")):
        return (
            f"Résumé : {ctx['count']} dépenses communes, {total:.2f} € au total. "
            f"Quentin a payé {pay['Quentin']:.2f} € et Partenaire {pay['Partenaire']:.2f} €. "
            f"Écart à lisser : {ctx['balance_to_adjust']:.2f} €."
        )
    return "Je peux analyser les dépenses disponibles, lire un ticket photo et proposer une lecture. Essayez : « Fais-moi un résumé », « Qui doit équilibrer ? » ou envoyez une photo de ticket."


def sanitize_image(image):
    if not image or not isinstance(image, str):
        return None
    image = image.strip()
    if not image.startswith("data:image/"):
        return None
    if len(image) > MAX_IMAGE_CHARS:
        raise ValueError("Image trop lourde. Envoyez une photo plus légère.")
    if not re.match(r"^data:image/(jpeg|jpg|png|webp);base64,[A-Za-z0-9+/=\s]+$", image[:80] + image[-20:]):
        if ";base64," not in image:
            return None
    return image


def parse_suggestion(text):
    match = re.search(r"SUGGESTION_JSON\s*(\{.*?\})", text, re.S)
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
    payer = raw.get("payer") if raw.get("payer") in PAYERS else "Quentin"
    date = str(raw.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        date = ""
    return {
        "label": label,
        "amount": round(amount, 2),
        "date": date,
        "category": category,
        "payer": payer,
        "shared": True,
        "status": "À équilibrer",
        "note": str(raw.get("note") or "Ticket lu par l'assistant").strip()[:160],
        "confidence": raw.get("confidence") if raw.get("confidence") in ("high", "medium", "low") else "medium",
    }


def qwen_chat(messages, model, max_tokens=700):
    payload = {
        "model": model,
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
    return clean_answer(content)


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
    text = re.sub(r"\s*SUGGESTION_JSON\s*\{.*?\}", "", text, flags=re.S).strip()
    extracted = extract_french(text)
    if extracted:
        return extracted
    return text[:900].strip()


def assistant_answer(question, expenses, image=None):
    ctx = finance_context(expenses)
    user_text = (
        "Contexte financier calculé, à utiliser comme seule source de chiffres:\n"
        + json.dumps(ctx, ensure_ascii=False)
        + "\n\nQuestion: "
        + (question or "Analyse ce ticket et dis-moi ce qu'il faut en retenir.")
        + "\n\nSi tu lis un ticket, termine par une ligne du type:\n"
        + 'SUGGESTION_JSON {"label":"...","amount":12.5,"date":"2026-08-14","category":"Courses","payer":"Quentin","confidence":"medium","note":"..."}\n'
        + "Omets cette ligne s'il n'y a pas de ticket lisible."
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
            suggestion = parse_suggestion(answer)
            clean = re.sub(r"\s*SUGGESTION_JSON\s*\{.*?\}", "", answer, flags=re.S).strip()
            return clean, "qwen", suggestion, ctx
        except Exception as e:
            if image:
                return (
                    "Je n'ai pas pu lire cette image pour le moment. Vous pouvez saisir la dépense à la main, je l'analyserai ensuite.",
                    "rules",
                    None,
                    ctx,
                )
            fallback = deterministic_answer((question or "").lower(), ctx)
            return fallback + " (lecture Qwen indisponible)", "rules", None, ctx
    return deterministic_answer((question or "").lower(), ctx), "rules", None, ctx


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", PUBLIC_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        super().end_headers()

    def send_json(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 4_500_000:
            raise ValueError("Requête trop volumineuse")
        return json.loads(self.rfile.read(n) or b"{}")

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
                },
            )
        if path.startswith("/api/expenses"):
            try:
                return self.send_json(200, {"expenses": get_expenses()})
            except Exception as e:
                return self.send_json(502, {"error": "Airtable indisponible", "detail": str(e)})
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/assistant":
            try:
                body = self.read_json()
                question = str(body.get("question", "")).strip()
                image = sanitize_image(body.get("image"))
                if not question and not image:
                    return self.send_json(400, {"error": "Question ou image requise"})
                answer, engine, suggestion, ctx = assistant_answer(question, get_expenses(), image)
                return self.send_json(
                    200,
                    {"answer": answer, "engine": engine, "suggestion": suggestion, "facts": ctx},
                )
            except Exception as e:
                return self.send_json(400, {"error": "Question invalide", "detail": str(e)})
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
            if item.get("payer") not in PAYERS:
                item["payer"] = "Quentin"
            return self.send_json(201, {"expense": create_expense(item)})
        except Exception as e:
            return self.send_json(400, {"error": "Dépense invalide", "detail": str(e)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8787"))
    host = os.getenv("HOST", "0.0.0.0")
    mode = "Airtable" if TOKEN and BASE_ID else "local-empty"
    print(f"Notitia Finances: http://{host}:{port} ({mode})", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
