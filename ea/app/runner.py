import os
import runpy

def role() -> str:
    return (os.environ.get("EA_ROLE") or "monolith").strip().lower()

def main() -> None:
    r = role()
    print("==================================================")
    print(f"🚀 BOOTING EA OS IN ROLE: [ {r.upper()} ]")
    print("==================================================")
    
    if r == "api":
        from app.roles.api import run_api
        import asyncio; asyncio.run(run_api())
    elif r == "poller":
        from app.roles.poller import run_poller
        import asyncio; asyncio.run(run_poller())
    elif r == "worker":
        from app.roles.worker import run_worker
        import asyncio; asyncio.run(run_worker())
    elif r == "outbox":
        from app.roles.outbox import run_outbox
        import asyncio; asyncio.run(run_outbox())
    else:
        # V1.5 Monolith Bridge (Runs your original code seamlessly)
        try:
            runpy.run_module("app.main", run_name="__main__")
        except ImportError:
            runpy.run_module("app.poll_listener", run_name="__main__")

if __name__ == "__main__":
    main()
