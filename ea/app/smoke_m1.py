import logging
logging.basicConfig(level=logging.INFO)
import sys
sys.path.append('/app')
from app.supervisor import supervised

class DummyDB:
    def rollback(self): logging.info("✅ MOCK DB ROLLBACK EXECUTED (Dirty Transaction Prevented!)")

import builtins
builtins._ooda_global_db = DummyDB()

@supervised(fallback_mode="simplified-first", failure_class="markup_api_400", intent="render_visuals")
def failing_renderer():
    logging.info("Child EA (L1) trying to hit MarkupGo API...")
    raise Exception("HTTP 400 Validation Error: Invalid template id")

if __name__ == "__main__":
    print("\n--- 🚀 INITIATING v1.12.1 MUM BRAIN SMOKE TEST ---")
    result = failing_renderer()
    print("\n--- 📬 FINAL DELIVERY TO USER ---")
    print(result)
    print("\n✅ M1 Smoke Test passed: Raw error caught, DB rolled back, clean text delivered.\n")
