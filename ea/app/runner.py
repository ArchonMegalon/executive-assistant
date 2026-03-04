import os
import uvicorn

def role() -> str:
    return (os.environ.get("EA_ROLE") or "monolith").strip().lower()

def main() -> None:
    r = role()
    print("==================================================")
    print(f"🚀 BOOTING EA OS IN ROLE: [ {r.upper()} ]")
    print("==================================================")
    
    if r == "api":
        uvicorn.run("app.main:app", host="0.0.0.0", port=8090, log_level="warning")
    elif r == "poller":
        from app.roles.poller import run_poller
        import asyncio; asyncio.run(run_poller())
    elif r == "worker":
        from app.roles.worker import run_worker
        import asyncio; asyncio.run(run_worker())
    elif r == "outbox":
        from app.roles.outbox import run_outbox
        import asyncio; asyncio.run(run_outbox())
    elif r == "monolith":
        uvicorn.run("app.main:app", host="0.0.0.0", port=8090, log_level="warning")
    else:
        raise ValueError(f"Unknown EA_ROLE: {r}")

if __name__ == "__main__":
    main()
