import json, os, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).parent
BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appEGVy9MVBGYmPQT")
TABLE = os.getenv("AIRTABLE_TABLE", "Dépenses")
TOKEN = os.getenv("AIRTABLE_API_KEY", "")
# API key is intentionally read only from the process environment, never shipped to the client.

DEMO = [
 {"id":"demo-1","date":"2026-08-14","label":"Courses semaine","category":"Courses","amount":86.40,"payer":"Quentin","shared":True,"status":"À équilibrer","note":""},
 {"id":"demo-2","date":"2026-08-12","label":"Internet","category":"Abonnements","amount":29.99,"payer":"Partenaire","shared":True,"status":"À équilibrer","note":""},
 {"id":"demo-3","date":"2026-08-08","label":"Restaurant","category":"Sorties","amount":54.00,"payer":"Quentin","shared":True,"status":"Réglé","note":""},
]

def airtable_request(method="GET", path="", payload=None):
    if not TOKEN or not BASE_ID: return None
    url = "https://api.airtable.com/v0/" + path
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=12) as r: return json.loads(r.read())

def normalize(fields, rid):
    return {"id":rid,"date":fields.get("Date",""),"label":fields.get("Dépense", ""),"category":fields.get("Catégorie", "Autres"),"amount":float(fields.get("Montant (€)",0) or 0),"payer":fields.get("Payé par","Quentin"),"shared":bool(fields.get("Dépense commune",True)),"status":fields.get("Remboursement","À équilibrer"),"note":fields.get("Note","")}

def get_expenses():
    if TOKEN and BASE_ID:
        data=airtable_request("GET", f"{BASE_ID}/{urllib.parse.quote(TABLE)}?pageSize=100") or {}
        return [normalize(r.get("fields",{}),r.get("id")) for r in data.get("records",[])]
    return DEMO

def create_expense(item):
    if TOKEN and BASE_ID:
        fields={"Dépense":item["label"],"Date":item["date"],"Catégorie":item["category"],"Montant (€)":item["amount"],"Payé par":item["payer"],"Dépense commune":item["shared"],"Remboursement":item["status"],"Note":item.get("note","")}
        data=airtable_request("POST", f"{BASE_ID}/{urllib.parse.quote(TABLE)}", {"fields":fields})
        return normalize(data.get("fields",fields),data.get("id",""))
    item["id"]="local-"+str(len(DEMO)+1); DEMO.insert(0,item); return item

def finance_context(expenses):
    shared=[x for x in expenses if x.get("shared",True)]
    total=sum(float(x.get("amount",0) or 0) for x in shared)
    by_payer={p:sum(float(x.get("amount",0) or 0) for x in shared if x.get("payer")==p) for p in ("Quentin","Partenaire")}
    by_cat={}
    for x in shared: by_cat[x.get("category","Autres")]=by_cat.get(x.get("category","Autres"),0)+float(x.get("amount",0) or 0)
    due=abs(by_payer["Quentin"]-by_payer["Partenaire"])/2
    return {"count":len(shared),"total":round(total,2),"by_payer":{k:round(v,2) for k,v in by_payer.items()},"by_category":{k:round(v,2) for k,v in by_cat.items()},"balance_to_adjust":round(due,2)}

def assistant_answer(question, expenses):
    ctx=finance_context(expenses); q=question.lower(); total=ctx["total"]; cats=ctx["by_category"]; pay=ctx["by_payer"]
    if any(w in q for w in ("combien", "total", "dépensé", "depense")) and any(w in q for w in ("course", "sortie", "logement", "transport", "abonnement", "santé")):
        found=next((v for k,v in cats.items() if k.lower() in q),None)
        if found is not None: return f"La catégorie demandée représente {found:.2f} €. Sur les données disponibles, le total commun est de {total:.2f} €."
    if any(w in q for w in ("équilibr", "rembour", "doit", "doivent")):
        if ctx["balance_to_adjust"]<0.01: return "Les contributions sont actuellement équilibrées sur les dépenses communes disponibles."
        who="Partenaire" if pay["Quentin"]>pay["Partenaire"] else "Quentin"
        return f"Pour une répartition à parts égales, {who} devrait prendre en charge environ {ctx['balance_to_adjust']:.2f} € sur les prochaines dépenses communes."
    if any(w in q for w in ("catégorie", "categorie", "poste", "où", "ou")) and cats:
        k,v=max(cats.items(),key=lambda item:item[1]); return f"Le poste le plus élevé est {k}, avec {v:.2f} €, soit {round(v/total*100) if total else 0} % du total commun."
    if any(w in q for w in ("résumé", "resume", "situation", "état", "etat")):
        return f"Résumé : {ctx['count']} dépenses communes, {total:.2f} € au total. Quentin a payé {pay['Quentin']:.2f} € et Partenaire {pay['Partenaire']:.2f} €. Écart à lisser : {ctx['balance_to_adjust']:.2f} €."
    return "Je peux analyser les dépenses disponibles. Essayez : « Quel est le total ? », « Qui doit équilibrer ? », « Quelle catégorie coûte le plus ? » ou « Fais-moi un résumé »."

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT),**kwargs)
    def send_json(self,status,obj):
        raw=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path=="/api/health": return self.send_json(200,{"ok":True,"mode":"airtable" if TOKEN and BASE_ID else "demo","baseConfigured":bool(BASE_ID)})
        if self.path.startswith("/api/expenses"):
            try: return self.send_json(200,{"expenses":get_expenses()})
            except Exception as e: return self.send_json(502,{"error":"Airtable indisponible","detail":str(e)})
        return super().do_GET()
    def do_POST(self):
        if self.path=="/api/assistant":
            try:
                n=int(self.headers.get("Content-Length",0)); body=json.loads(self.rfile.read(n)); question=str(body.get("question","")).strip()
                if not question: return self.send_json(400,{"error":"Question vide"})
                return self.send_json(200,{"answer":assistant_answer(question,get_expenses()),"engine":"finance-rules-v1"})
            except Exception as e: return self.send_json(400,{"error":"Question invalide","detail":str(e)})
        if self.path!="/api/expenses": return self.send_json(404,{"error":"Not found"})
        try:
            n=int(self.headers.get("Content-Length",0)); item=json.loads(self.rfile.read(n));
            for key in ("date","label","category","amount","payer"): assert key in item
            item["amount"]=float(item["amount"]); item.setdefault("shared",True); item.setdefault("status","À équilibrer")
            return self.send_json(201,{"expense":create_expense(item)})
        except Exception as e: return self.send_json(400,{"error":"Dépense invalide","detail":str(e)})

if __name__=="__main__":
    port=int(os.getenv("PORT","8787")); print(f"Notitia Finances: http://127.0.0.1:{port} ({'Airtable' if TOKEN and BASE_ID else 'demo'})",flush=True); ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
