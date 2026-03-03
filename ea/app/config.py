import yaml, os, json

class TenantConfig(dict):
    def __getattr__(self, key): return self.get(key)
    def __setattr__(self, key, value): self[key] = value


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _default_openclaw_container() -> str:
    return os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "openclaw-gateway")


def _fallback_admin_tenant() -> TenantConfig:
    key = os.environ.get("EA_DEFAULT_ADMIN_KEY", "admin")
    label = os.environ.get("EA_DEFAULT_ADMIN_LABEL", "Operator")
    return TenantConfig({
        "key": key,
        "label": label,
        "openclaw_container": _default_openclaw_container(),
        "google_account": os.environ.get("EA_DEFAULT_ADMIN_EMAIL", ""),
        "family_openclaw_container": os.environ.get("EA_DEFAULT_FAMILY_OPENCLAW_CONTAINER", ""),
        "include_family": False,
    })


def _default_admin_from_tenants(tenants: dict) -> TenantConfig | None:
    preferred = str(os.environ.get("EA_DEFAULT_ADMIN_KEY", "")).strip()
    if preferred and preferred in tenants:
        return tenants[preferred]
    if "admin" in tenants:
        return tenants["admin"]
    if "default" in tenants:
        return tenants["default"]
    if tenants:
        first_key = sorted(tenants.keys())[0]
        return tenants.get(first_key)
    return None


def _dynamic_users_path() -> str:
    return os.environ.get("EA_DYNAMIC_USERS_PATH", "/attachments/dynamic_users.json")


def load_tenants():
    for p in ["/app/config.yaml", "/app/tenants.yaml", "config.yaml", "tenants.yaml", "/docker/EA/tenants.yaml"]:
        if os.path.exists(p):
            try:
                with open(p, "r") as f: data = yaml.safe_load(f) or {}
                tenants = {k: TenantConfig(v) for k, v in data.get("tenants", {}).items() if isinstance(v, dict)}
                for k, v in tenants.items(): v['key'] = k
                return tenants, data.get("telegram", {}), data.get("system", {})
            except: pass

    fallback = _fallback_admin_tenant()
    return {str(fallback.get("key") or "admin"): fallback}, {}, {}

def get_tenant(chat_id):
    tenants, tg_cfg, _ = load_tenants()

    if isinstance(tg_cfg, dict) and 'allowed_chats' in tg_cfg:
        for k, v in tg_cfg['allowed_chats'].items():
            if str(v) == str(chat_id):
                return tenants.get(k, _default_admin_from_tenants(tenants))
    for name, t in tenants.items():
        if str(t.get("telegram_chat_id", "")) == str(chat_id):
            return t

    dynamic_users_path = _dynamic_users_path()
    try:
        with open(dynamic_users_path, "r") as f:
            users = json.load(f)
            if str(chat_id) in users:
                u = users[str(chat_id)]
                if u.get("is_admin"):
                    t = _default_admin_from_tenants(tenants) or _fallback_admin_tenant()
                    t['telegram_chat_id'] = chat_id
                    t['google_account'] = u.get("email", t.get('google_account'))
                    env_default_openclaw = os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "").strip()
                    current_openclaw = str(t.get("openclaw_container", "") or "").strip()
                    if env_default_openclaw and (not current_openclaw or current_openclaw.endswith("-demo") or current_openclaw == "openclaw-gateway"):
                        t['openclaw_container'] = env_default_openclaw
                    return t
                return TenantConfig({
                    "key": f"user_{chat_id}",
                    "label": u.get("name", f"User {chat_id}"),
                    "telegram_chat_id": chat_id,
                    "google_account": u.get("email", ""),
                    "openclaw_container": _default_openclaw_container(),
                    "include_family": False
                })
    except: pass

    # Optional bootstrap mode: disabled by default for safety.
    if _env_bool("EA_ALLOW_BOOTSTRAP_ADMIN", False) and not os.path.exists(dynamic_users_path):
        os.makedirs(os.path.dirname(dynamic_users_path) or ".", exist_ok=True)
        bootstrap_name = os.environ.get("EA_BOOTSTRAP_ADMIN_NAME", "Bootstrap Admin")
        bootstrap_email = os.environ.get("EA_BOOTSTRAP_ADMIN_EMAIL", "")
        with open(dynamic_users_path, "w") as f:
            json.dump({str(chat_id): {"name": bootstrap_name, "email": bootstrap_email, "is_admin": True}}, f)
        t = _default_admin_from_tenants(tenants) or _fallback_admin_tenant()
        t['telegram_chat_id'] = chat_id
        if bootstrap_email:
            t['google_account'] = bootstrap_email
        return t

    return None

def get_admin_chat_id():
    tenants, tg_cfg, _ = load_tenants()
    if isinstance(tg_cfg, dict) and 'allowed_chats' in tg_cfg:
        for v in tg_cfg['allowed_chats'].values(): return str(v)
    try:
        with open(_dynamic_users_path(), "r") as f:
            for cid, u in json.load(f).items():
                if u.get("is_admin"): return str(cid)
    except: pass
    admin_t = _default_admin_from_tenants(tenants)
    if admin_t and admin_t.get('telegram_chat_id'):
        return str(admin_t['telegram_chat_id'])
    return None

def tenant_by_chat_id(chat_id):
    t = get_tenant(chat_id)
    return t.key if t else None
