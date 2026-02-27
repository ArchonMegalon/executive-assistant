import yaml, os
from app.settings import EA_TENANTS_YAML

TENANT_BY_CHAT_ID = {}
_loaded = False

def load_tenants():
    global TENANT_BY_CHAT_ID, _loaded
    try:
        if os.path.exists(EA_TENANTS_YAML):
            with open(EA_TENANTS_YAML, 'r') as f:
                data = yaml.safe_load(f)
                if data:
                    for t_name, t_data in data.items():
                        chat_ids = t_data.get('telegram', {}).get('allow_chat_ids', [])
                        for cid in chat_ids:
                            TENANT_BY_CHAT_ID[int(cid)] = t_name
        _loaded = True
    except Exception as e:
        print(f"⚠️ Tenants load failed: {e}")

def resolve_tenant(chat_id: int) -> str:
    if not _loaded: load_tenants()
    return TENANT_BY_CHAT_ID.get(int(chat_id))
