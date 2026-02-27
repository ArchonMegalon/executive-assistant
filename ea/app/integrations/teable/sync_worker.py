import asyncio, os, json, httpx

TEABLE_TOKEN = os.environ.get("TEABLE_TOKEN")
TEABLE_BASE_ID = os.environ.get("TEABLE_BASE_ID")
BASE_URL = "https://app.teable.io/api"

async def run_teable_sync():
    print("==================================================", flush=True)
    print("🗃️ EA OS TEABLE SYNC: ONLINE (Watching Memory)", flush=True)
    print("==================================================", flush=True)
    
    if not TEABLE_TOKEN or not TEABLE_BASE_ID:
        print("⚠️ TEABLE_TOKEN or BASE_ID missing. Syncer offline.", flush=True)
        while True: await asyncio.sleep(3600)

    headers = {"Authorization": f"Bearer {TEABLE_TOKEN}", "Content-Type": "application/json"}
    brain_path = "/attachments/brain.json"
    state_path = "/attachments/teable_sync_state.json"
    
    while True:
        try:
            if os.path.exists(brain_path):
                with open(brain_path, "r") as f:
                    brain = json.load(f)
                
                state = []
                if os.path.exists(state_path):
                    with open(state_path, "r") as f:
                        state = json.load(f)
                        
                async with httpx.AsyncClient(timeout=15.0) as client:
                    # 1. Fetch tables dynamically
                    res = await client.get(f"{BASE_URL}/base/{TEABLE_BASE_ID}/table", headers=headers)
                    if res.status_code == 200:
                        tables = res.json()
                        # Find the Memory table
                        memory_table = next((t for t in tables if t["name"].lower() == "memory"), None)
                        if memory_table:
                            table_id = memory_table["id"]
                            # 2. Push new facts
                            for concept, fact in brain.items():
                                if concept not in state:
                                    print(f"🗃️ Syncing new memory to cloud: [{concept}]", flush=True)
                                    payload = {"records": [{"fields": {"Concept": concept, "Core Fact": fact}}]}
                                    push_res = await client.post(f"{BASE_URL}/table/{table_id}/record", json=payload, headers=headers)
                                    if push_res.status_code in (200, 201):
                                        state.append(concept)
                                        with open(state_path, "w") as f:
                                            json.dump(state, f)
                                        await asyncio.sleep(1) # Rate limit protection
                                    else:
                                        print(f"⚠️ Teable push failed: {push_res.text}", flush=True)
        except Exception as e:
            print(f"🚨 TEABLE ERROR: {e}", flush=True)
        
        await asyncio.sleep(15) # Check every 15 seconds

if __name__ == "__main__":
    asyncio.run(run_teable_sync())
