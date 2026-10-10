"""Regressions v2.9 — durcissement backend (F1 auth, F4 anti-doublon transferts, F5 import idempotent).

Aucun secret : les hashes utilises sont derives a la volee ; les anciens hashes publics
ne sont ni lus ni reproduits. Mode local vide, aucun appel reseau ni donnee reelle.
Fixtures bancaires CIC/TR/Revolut : voir test_bank_regressions_local.py (parite inchangee).
"""
import json
import os
import re
import sys
import unittest
from pathlib import Path

os.environ["AIRTABLE_API_KEY"] = ""
os.environ["AIRTABLE_BASE_ID"] = ""
os.environ["QWEN_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
import server  # noqa: E402

server.TOKEN = ""
server.BASE_ID = ""
server.QWEN_KEY = ""


def row(rid, label="Test", amount=10.0, payer="Quentin", shared=True, category="Courses",
        note="", date="2026-10-05", **kw):
    base = {
        "id": rid, "date": date, "label": label, "category": category, "amount": amount,
        "payer": payer, "shared": shared, "status": "À équilibrer", "note": note,
        "is_budget": False, "is_shopping": False, "is_chat": False, "is_auth": False,
    }
    base.update(kw)
    return base


def auth_row(hashes):
    return row("authX", label="[Auth] codes d'accès", note="kind=auth\n" + json.dumps(hashes),
               is_auth=True, payer="Quentin", shared=False)


class AuthHardeningTests(unittest.TestCase):
    """F1 : plus aucun hash committe ; stockage Airtable fait foi ; rotation effective."""

    def setUp(self):
        server.LOCAL_EXPENSES.clear()
        server.LOCAL_BUDGETS.clear()
        server.LOCAL_SHOPPING.clear()
        server._AUTH_CACHE = None
        server._AUTH_FAILS.clear()

    def test_repo_has_no_hardcoded_auth_hash_and_default_denies(self):
        src = (REPO / "server.py").read_text(encoding="utf-8")
        # Aucun hash sha256 litteral ne traine dans les constantes d'auth du depot public.
        self.assertIsNone(re.search(r'APP_CODE_HASH\s*=\s*"[0-9a-f]{32,}"', src))
        self.assertIsNone(re.search(r'^\s*"(?:Quentin|Jessica)":\s*"[0-9a-f]{32,}",?$', src, re.M))
        # Le poivre de derivation ne doit PAS changer (sinon tous les codes stockes sautent).
        self.assertIn('APP_CODE_PEPPER = "duospend-v1"', src)
        # Etat par defaut du depot (filets vides) : tout code est refuse.
        old_codes, old_foyer = server.APP_CODES, server.APP_CODE_HASH
        try:
            server.APP_CODES = {"Quentin": "", "Jessica": ""}
            server.APP_CODE_HASH = ""
            server._AUTH_CACHE = None
            self.assertIsNone(server.user_for_code("482150"))
            self.assertIsNone(server.user_for_code("test-code-quentin"))
            self.assertFalse(server.app_code_ok("ancien-code-foyer"))
        finally:
            server.APP_CODES, server.APP_CODE_HASH = old_codes, old_foyer
            server._AUTH_CACHE = None

    def test_stored_pins_win_and_rotation_disables_fallback(self):
        old_codes, old_foyer = server.APP_CODES, server.APP_CODE_HASH
        try:
            server.APP_CODES = {"Quentin": server.code_digest("ancien-code-public"), "Jessica": ""}
            server.APP_CODE_HASH = ""
            server.LOCAL_EXPENSES.append(auth_row({"Quentin": server.code_digest("nouveau-pin-airtable")}))
            server._AUTH_CACHE = None
            # PIN stocke Airtable : accepte.
            self.assertEqual(server.user_for_code("nouveau-pin-airtable"), "Quentin")
            # Rotation effective : le filet (env) de Quentin est desactive par son hash stocke.
            self.assertIsNone(server.user_for_code("ancien-code-public"))
            # Le profil non stocke (Jessica) reste sur son filet.
            self.assertEqual(server.user_for_code("test-code-jessica"), None)
        finally:
            server.APP_CODES, server.APP_CODE_HASH = old_codes, old_foyer
            server._AUTH_CACHE = None

    def test_stored_foyer_disables_foyer_fallback(self):
        old_codes, old_foyer = server.APP_CODES, server.APP_CODE_HASH
        try:
            server.APP_CODES = {"Quentin": "", "Jessica": ""}
            server.APP_CODE_HASH = server.code_digest("ancien-foyer-public")
            server.LOCAL_EXPENSES.append(auth_row({"Foyer": server.code_digest("nouveau-foyer-airtable")}))
            server._AUTH_CACHE = None
            self.assertEqual(server.user_for_code("nouveau-foyer-airtable"), "Foyer")
            self.assertIsNone(server.user_for_code("ancien-foyer-public"))
        finally:
            server.APP_CODES, server.APP_CODE_HASH = old_codes, old_foyer
            server._AUTH_CACHE = None


class DuplicateDetectionTests(unittest.TestCase):
    """F4/F12 : transferts dedupliques par flux canonique ; debits par libelle (plus de 'meme jour')."""

    def setUp(self):
        server.LOCAL_EXPENSES.clear()
        server._AUTH_CACHE = None

    def test_two_legit_debits_same_day_same_amount_not_duplicated(self):
        stored = row("d1", label="Café du marché", amount=4.5, payer="Quentin",
                     category="Sorties", date="2026-10-05")
        # Même jour + même montant mais libellé different : PAS un doublon (faux positif corrige).
        op = {"date": "2026-10-05", "label": "Péage A13", "amount": 4.5,
              "direction": "debit", "category": "Transport"}
        self.assertIsNone(server._find_duplicate(op, [stored]))
        # Meme libelle a ±4 j : doublon.
        same = dict(op, label="Café du marché", date="2026-10-07", category="Sorties")
        match = server._find_duplicate(same, [stored])
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], "d1")
        # Au-dela de ±4 j : plus un doublon.
        far = dict(same, date="2026-10-10")
        self.assertIsNone(server._find_duplicate(far, [stored]))

    def test_transfer_duplicate_via_canonical_flow_two_accounts(self):
        stored = row("t1", label="Virement à Jessica", amount=600.0, payer="Quentin",
                     category="Transferts", date="2026-10-03")
        # Relu sur le compte de Jessica : « reçu de Quentin » == le virement émis par Quentin.
        incoming = {"date": "2026-10-04", "label": "Virement recu de Quentin", "amount": 600.0,
                    "direction": "transfert", "category": "Transferts"}
        match = server._find_duplicate(incoming, [stored], user="Jessica")
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], "t1")
        # Sens inverse (Jessica -> Quentin) : pas un doublon.
        reverse = dict(incoming, label="Virement à Quentin")
        self.assertIsNone(server._find_duplicate(reverse, [stored], user="Jessica"))
        # Montant different / hors fenetre : pas un doublon.
        self.assertIsNone(server._find_duplicate(dict(incoming, amount=601.0), [stored], user="Jessica"))
        self.assertIsNone(server._find_duplicate(dict(incoming, date="2026-10-20"), [stored], user="Jessica"))

    def test_transfer_never_matches_other_nature(self):
        transfer_row = row("t1", label="Virement à Jessica", amount=600.0, payer="Quentin",
                           category="Transferts", date="2026-10-03")
        plain_row = row("p1", label="Virement à Jessica", amount=600.0, payer="Quentin",
                        category="Autres", date="2026-10-03")
        debit_op = {"date": "2026-10-03", "label": "Virement à Jessica", "amount": 600.0,
                    "direction": "debit", "category": "Autres"}
        transfer_op = {"date": "2026-10-03", "label": "Virement à Jessica", "amount": 600.0,
                       "direction": "transfert", "category": "Transferts"}
        self.assertIsNone(server._find_duplicate(debit_op, [transfer_row]))
        self.assertIsNone(server._find_duplicate(transfer_op, [plain_row]))
        self.assertIsNotNone(server._find_duplicate(transfer_op, [transfer_row]))


class ImportIdempotenceTests(unittest.TestCase):
    """F5 : cles d'import deterministes, commit relancable, echec partiel honnete."""

    def setUp(self):
        server.LOCAL_EXPENSES.clear()
        server.LOCAL_BUDGETS.clear()
        server._AUTH_CACHE = None

    def test_import_keys_deterministic_and_source_id(self):
        text = "05/10/2026 CB CARREFOUR 12,34"
        a = server.analyze_statement(text, [], "2026-10", "releve.csv", user="Quentin")
        b = server.analyze_statement(text, [], "2026-10", "releve.csv", user="Quentin")
        self.assertEqual(a["source_id"], server._import_source_id("releve.csv", text))
        self.assertEqual(a["source_id"], b["source_id"])
        self.assertEqual([o["import_key"] for o in a["operations"]],
                         [o["import_key"] for o in b["operations"]])
        self.assertTrue(all(o["import_key"].startswith("imp-") for o in a["operations"]))
        # Un autre fichier -> une autre empreinte de source.
        c = server.analyze_statement(text, [], "2026-10", "autre.csv", user="Quentin")
        self.assertNotEqual(a["source_id"], c["source_id"])

    def test_repeat_commit_skips_registered_keys(self):
        k1 = "imp-" + "c" * 24
        k2 = "imp-" + "d" * 24
        item_a = {"date": "2026-10-06", "label": "Courses", "category": "Courses", "amount": 12.34,
                  "payer": "Quentin", "shared": True, "import_key": k1}
        item_b = {"date": "2026-10-06", "label": "Café", "category": "Sorties", "amount": 4.5,
                  "payer": "Quentin", "shared": True, "import_key": k2}
        created, skipped, warnings, partial = server.create_expenses_batch([item_a, item_b])
        self.assertEqual(len(created), 2)
        self.assertEqual(skipped, [])
        self.assertIsNone(partial)
        # Relance totale : rien de recree, cles exactes signalees.
        created2, skipped2, _, partial2 = server.create_expenses_batch([item_a, item_b])
        self.assertEqual(created2, [])
        self.assertEqual(sorted(skipped2), sorted([k1, k2]))
        self.assertIsNone(partial2)
        notes = [str(e.get("note")) for e in server.LOCAL_EXPENSES]
        self.assertEqual(sum(("imp_key=" + k1) in n for n in notes), 1)
        self.assertEqual(sum(("imp_key=" + k2) in n for n in notes), 1)
        # Cle repetee dans le MEME lot : une seule creation.
        k3 = "imp-" + "e" * 24
        same = [dict(item_a, import_key=k3, label="Lot doublon A"),
                dict(item_a, import_key=k3, label="Lot doublon B")]
        created3, skipped3, _, _ = server.create_expenses_batch(same)
        self.assertEqual(len(created3), 1)
        self.assertEqual(skipped3, [k3])
        # Ancien payload sans cle : accepte (pas d'idempotence, compatibilite).
        created4, skipped4, _, _ = server.create_expenses_batch([
            {"date": "2026-10-09", "label": "Sans cle", "category": "Courses", "amount": 3.0,
             "payer": "Quentin", "shared": True}])
        self.assertEqual(len(created4), 1)
        self.assertEqual(skipped4, [])
        # Cle au format invalide : ignoree, aucun marqueur ecrit.
        created5, _, _, _ = server.create_expenses_batch([
            dict(item_b, import_key="invalide !!", label="Cle invalide")])
        self.assertEqual(len(created5), 1)
        self.assertFalse(any("imp_key=invalide" in n for n in [str(e.get("note")) for e in server.LOCAL_EXPENSES]))

    def test_commit_partial_failure_reports_partial_error(self):
        old_token, old_base, old_req = server.TOKEN, server.BASE_ID, server.airtable_request
        calls = {"post": 0}

        def fake_airtable(method="GET", path="", payload=None, timeout=20):
            if method == "GET":
                return {"records": []}
            calls["post"] += 1
            if calls["post"] == 2:
                raise RuntimeError("panne simulee")
            return {"records": [
                {"id": "rec-%d-%d" % (calls["post"], i), "fields": rec["fields"]}
                for i, rec in enumerate(payload.get("records", []))
            ]}

        try:
            server.TOKEN, server.BASE_ID = "test-token", "appTEST"
            server.airtable_request = fake_airtable
            items = [{"date": "2026-10-05", "label": "Lot %d" % i, "category": "Courses", "amount": 1.0,
                      "payer": "Quentin", "shared": True, "import_key": "imp-partiel-%02d%s" % (i, "z" * 12)}
                     for i in range(15)]
            created, skipped, warnings, partial = server.create_expenses_batch(items)
            self.assertEqual(len(created), 10)   # 1er lot conserve
            self.assertEqual(skipped, [])
            self.assertIsNotNone(partial)        # echec partiel annonce honnetement
            self.assertIn("10", partial)
            self.assertIn("RuntimeError", partial)
        finally:
            server.TOKEN, server.BASE_ID, server.airtable_request = old_token, old_base, old_req

    def test_commit_total_failure_reports_partial_error(self):
        old_token, old_base, old_req = server.TOKEN, server.BASE_ID, server.airtable_request

        def fake_airtable(method="GET", path="", payload=None, timeout=20):
            if method == "GET":
                return {"records": []}
            raise RuntimeError("panne simulee")

        try:
            server.TOKEN, server.BASE_ID = "test-token", "appTEST"
            server.airtable_request = fake_airtable
            items = [{"date": "2026-10-05", "label": "Lot", "category": "Courses", "amount": 1.0,
                      "payer": "Quentin", "shared": True, "import_key": "imp-" + "f" * 24}]
            created, skipped, warnings, partial = server.create_expenses_batch(items)
            self.assertEqual(created, [])
            self.assertIsNotNone(partial)
            self.assertIn("0 opération", partial)
        finally:
            server.TOKEN, server.BASE_ID, server.airtable_request = old_token, old_base, old_req

    def test_reanalyze_same_file_dedups_and_recommit_is_noop(self):
        text = "\n".join([
            "05/10/2026 CB CARREFOUR 12,34",
            "06/10/2026 Virement à Jessica 600,00",
        ])
        res = server.analyze_statement(text, [], "2026-10", "releve-x.csv", user="Quentin")
        ops = res["operations"]
        self.assertEqual(len(ops), 2)
        items = [{"date": o["date"], "label": o["label"], "category": o["category"], "amount": o["amount"],
                  "payer": "Quentin", "shared": True, "import_key": o["import_key"]} for o in ops]
        created, skipped, _, partial = server.create_expenses_batch(items)
        self.assertEqual(len(created), 2)
        self.assertEqual(skipped, [])
        self.assertIsNone(partial)
        # Re-analyse du meme fichier : cles stables, debit ET transfert marques deja pointes.
        res2 = server.analyze_statement(text, server.get_expenses(), "2026-10", "releve-x.csv", user="Quentin")
        ops2 = res2["operations"]
        self.assertEqual([o["import_key"] for o in ops2], [o["import_key"] for o in ops])
        self.assertTrue(all(o["duplicate"] for o in ops2))
        self.assertEqual(res2["summary"]["duplicates"], 1)
        self.assertEqual(res2["summary"]["transfer_duplicates"], 1)
        # Re-commit : aucune creation, les deux cles sont ignorees.
        items2 = [{"date": o["date"], "label": o["label"], "category": o["category"], "amount": o["amount"],
                   "payer": "Quentin", "shared": True, "import_key": o["import_key"]} for o in ops2]
        created2, skipped2, _, partial2 = server.create_expenses_batch(items2)
        self.assertEqual(created2, [])
        self.assertEqual(sorted(skipped2), sorted(o["import_key"] for o in ops))
        self.assertIsNone(partial2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
