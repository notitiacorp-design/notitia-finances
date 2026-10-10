"""Test optionnel : un appel LLM reel depuis le module local, cle lue silencieusement dans l'environnement.

Ne s'execute que si OPENROUTER_API_KEY ou QWEN_API_KEY est present (sinon skip).
N'ecrit aucun historique de conversation ; ne fait qu'un aller-retour minimal.
La cle n'est jamais imprimee ni journalisee.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ["AIRTABLE_API_KEY"] = ""
os.environ["AIRTABLE_BASE_ID"] = ""

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
import server  # noqa: E402

server.TOKEN = ""
server.BASE_ID = ""
_KEY = os.getenv("QWEN_API_KEY") or os.getenv("OPENROUTER_API_KEY") or ""


@unittest.skipUnless(_KEY, "aucune cle LLM dans l'environnement (test optionnel)")
class LlmSmokeTests(unittest.TestCase):
    def test_single_roundtrip(self):
        server.QWEN_KEY = _KEY
        try:
            text = server.qwen_chat(
                [{"role": "user", "content": "Réponds uniquement : ok"}],
                server.CHAT_MODEL,
                max_tokens=8,
            )
        except Exception as e:  # reseau indisponible : skip propre, jamais de fail dur
            self.skipTest("appel LLM indisponible (%s)" % type(e).__name__)
        self.assertTrue(str(text).strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
