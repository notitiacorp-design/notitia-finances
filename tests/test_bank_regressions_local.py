"""Regressions parseurs bancaires sur extraits locaux reels (CIC, Trade Republic, Revolut).

Les fichiers d'extraits restent HORS du depot (donnees bancaires reelles) ; ces tests
s'executent seulement s'ils existent sur la machine (sinon skips propres).
Agregats attendus (valides en prod, cf. historique projet) :
- CIC : 159 operations, 143 debits / 16 credits (2 206,61 EUR de credits)
- Trade Republic : 19 operations, 55,21 EUR entree / 302,60 EUR sortie
- Revolut : 64 operations, 4 credits (1 227,28 EUR)
"""
import os
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

FIXTURES = {
    "cic": ["/tmp/cic_layout.txt", "/tmp/cic_plain.txt"],
    "tr": ["/tmp/tr_layout.txt"],
    "revolut": ["/tmp/releve_layout.txt"],
}
ALL_PRESENT = all(Path(p).exists() for paths in FIXTURES.values() for p in paths[:1]) and Path(FIXTURES["cic"][0]).exists()


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def split_dirs(ops):
    return ([o for o in ops if o["direction"] == "debit"],
            [o for o in ops if o["direction"] == "credit"])


@unittest.skipUnless(ALL_PRESENT, "extraits bancaires locaux absents (non embarques dans le depot)")
class BankParserRegressions(unittest.TestCase):
    def test_cic_159_ops(self):
        ops = server._statement_ops_fallback(read(FIXTURES["cic"][0]), "2026-09")
        debits, credits = split_dirs(ops)
        self.assertEqual(len(ops), 159)
        self.assertEqual(len(debits), 143)
        self.assertEqual(len(credits), 16)
        self.assertEqual(round(sum(o["amount"] for o in credits), 2), 2206.61)

    def test_trade_republic_19_ops(self):
        ops = server._statement_ops_fallback(read(FIXTURES["tr"][0]), "2026-09")
        debits, credits = split_dirs(ops)
        self.assertEqual(len(ops), 19)
        self.assertEqual(len(debits), 17)
        self.assertEqual(len(credits), 2)
        self.assertEqual(round(sum(o["amount"] for o in credits), 2), 55.21)
        self.assertEqual(round(sum(o["amount"] for o in debits), 2), 302.60)

    def test_revolut_64_ops(self):
        ops = server._statement_ops_fallback(read(FIXTURES["revolut"][0]), "2026-09")
        debits, credits = split_dirs(ops)
        self.assertEqual(len(ops), 64)
        self.assertEqual(len(credits), 4)
        self.assertEqual(round(sum(o["amount"] for o in credits), 2), 1227.28)

    def test_analyze_statement_engines_offline(self):
        cic = server.analyze_statement(read(FIXTURES["cic"][0]), [], "2026-09")
        self.assertEqual(cic["engine"], "fallback")
        self.assertIn("ia_non_configuree", cic["warnings"])
        revolut = server.analyze_statement(read(FIXTURES["revolut"][0]), [], "2026-09")
        self.assertEqual(revolut["engine"], "revolut")
        self.assertEqual(revolut["summary"]["total"], 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
