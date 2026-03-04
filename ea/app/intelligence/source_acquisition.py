from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from app.calendar_store import list_events_range
from app.gog import docker_exec, gog_cli


@dataclass
class SourceAcquisitionResult:
    mails: list[dict]
    calendar_events: list[dict]
    accounts: list[str]
    diagnostics: list[str]


def _safe_extract_array(text: str) -> list:
    try:
        clean = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
        start = -1
        for i, c in enumerate(clean):
            if c in "[{":
                start = i
                break
        if start >= 0:
            obj = json.loads(clean[start:])
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                for key in ("items", "messages", "events", "result", "data"):
                    val = obj.get(key)
                    if isinstance(val, list):
                        return val
    except Exception:
        pass
    try:
        m = re.search(r"\[[\s\S]*\]", text or "")
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return []


async def _safe_gog(container: str, cmd: list[str], account: str, timeout: float = 20.0) -> str:
    try:
        return await asyncio.wait_for(gog_cli(container, cmd, account), timeout=timeout)
    except asyncio.TimeoutError:
        await docker_exec(container, ["pkill", "-f", "gog"], user="root", timeout_s=8.0)
        short = " ".join(cmd[:3])
        raise TimeoutError(f"CLI hung on command: {short}")


async def _emit_status(
    cb: Callable[[str], Awaitable[None]] | None,
    msg: str,
) -> None:
    if cb is None:
        return
    try:
        await cb(msg)
    except Exception:
        pass


async def collect_briefing_sources(
    *,
    openclaw_container: str,
    primary_account: str,
    tenant_key: str,
    status_cb: Callable[[str], Awaitable[None]] | None = None,
) -> SourceAcquisitionResult:
    diag_logs: list[str] = []

    await _emit_status(status_cb, "Discovering Authorized Google Accounts...")
    try:
        raw_auths = await _safe_gog(openclaw_container, ["auth", "list"], "", timeout=10.0)
        accounts = list(set(re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", raw_auths)))
        if not accounts:
            accounts = [primary_account] if primary_account else [""]
        diag_logs.append(f"🔑 Accounts: {', '.join([a.split('@')[0] for a in accounts if a])}")
    except Exception as e:
        accounts = [primary_account] if primary_account else [""]
        diag_logs.append(f"⚠️ Auth List Err: {str(e)[:50]}")

    await _emit_status(status_cb, "Fetching & Python Filtering Emails...")
    clean_mails: list[dict] = []
    junk_kws = [
        "eff",
        "andrew lock",
        "stack overflow",
        "dodo",
        "appsumo",
        "dyson",
        "facebook",
        "linkedin",
        "bestsecret",
        "mediamarkt",
        "voyage",
        "babysits",
        "stacksocial",
        "digital trends",
        "the futurist",
        "newsletter",
        "spiceworks",
        "ikea",
        "paypal",
        "gog.com",
        "steam",
        "humble bundle",
        "indie gala",
        "promotions",
        "penny",
        "chummer",
        "samsung",
        "mtg",
        "omi ai",
        "omi",
        "akupara",
        "cinecenter",
        "beta",
        "early access",
        "n8n",
        "versandinformation",
        "danke für",
        "we got your full",
        "out for delivery",
        "ihre bestellung bei",
        "paket kommt",
        "order confirmed",
        "wird zugestellt",
        "hardloop",
        "bergzeit",
        "betzold",
        "immmo",
        "zalando",
        "klarna",
        "amazon",
        "lieferando",
    ]
    keep_kws = ["nicht zugestellt", "wartet auf abholung", "fehlgeschlagen", "abholbereit", "action required"]
    for account in accounts:
        try:
            raw_mails = await _safe_gog(
                openclaw_container,
                ["gmail", "messages", "search", "newer_than:1d", "--max", "40", "--json"],
                account,
                timeout=20.0,
            )
            mails = _safe_extract_array(raw_mails)
            for mail in mails:
                raw_val = json.dumps(mail, ensure_ascii=False).lower()
                if any(kw in raw_val for kw in keep_kws):
                    mail["_account"] = account
                    clean_mails.append(mail)
                    continue
                if any(kw in raw_val for kw in junk_kws):
                    continue
                mail["_account"] = account
                clean_mails.append(mail)
        except Exception as e:
            label = account.split("@")[0] if account else "def"
            diag_logs.append(f"⚠️ Mails ({label}) Err: {str(e)[:30]}")

    deduped: list[dict] = []
    seen_subj: set[str] = set()
    for mail in clean_mails:
        subj = str(mail.get("subject", "")).lower().strip()[:80]
        if subj in seen_subj:
            continue
        seen_subj.add(subj)
        deduped.append(mail)
    clean_mails = deduped

    await _emit_status(status_cb, "Fetching Calendar Events (Rewinding to Midnight)...")
    clean_cal: list[dict] = []
    processed_events: set[str] = set()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

    target_cals: list[tuple[str, str, str]] = []
    for account in accounts:
        target_cals.append((account, "primary", "primary"))
        target_cals.append((account, "Executive Assistant", "EA Shared"))

    for account, cid, cname in target_cals:
        label = account.split("@")[0] if account else "def"
        try:
            flags_to_try = [["--timeMin", today_start], ["--time-min", today_start], ["--start", today_start], []]
            events: list[dict] = []
            cmd_variants = [
                ["calendar", "events", "--max", "50", "--json", "--calendar", cid],
                ["calendar", "events", "list", "--max", "50", "--json", "--calendar", cid],
                ["calendar", "events", "--calendar", cid, "--max", "50", "--json"],
                ["calendar", "events", "--max", "50", "--json"],
            ]
            last_err = None
            for base_cmd in cmd_variants:
                for flags in flags_to_try:
                    cmd = base_cmd + flags
                    try:
                        raw_cal = await _safe_gog(openclaw_container, cmd, account, timeout=12.0)
                        events = _safe_extract_array(raw_cal)
                        if events:
                            break
                    except Exception as e:
                        last_err = e
                        continue
                if events:
                    break
            if not events:
                if last_err is not None:
                    diag_logs.append(f"ℹ️ Cal '{cname}' ({label}): 0 events (last err: {str(last_err)[:60]})")
                else:
                    diag_logs.append(f"ℹ️ Cal '{cname}' ({label}): 0 events.")
                continue
            added = 0
            for ev in events:
                dt_str = ""
                end_val = ev.get("end", {})
                if isinstance(end_val, dict):
                    dt_str = str(end_val.get("dateTime") or end_val.get("date") or "")
                elif isinstance(end_val, str):
                    dt_str = end_val
                if dt_str:
                    dt_str = dt_str.replace("Z", "+00:00")
                    if " " in dt_str and "+" not in dt_str:
                        dt_str = dt_str.replace(" ", "T") + "+01:00"
                    try:
                        end_ts = datetime.fromisoformat(dt_str)
                        if end_ts.tzinfo is None:
                            end_ts = end_ts.replace(tzinfo=timezone.utc)
                        if end_ts <= now - timedelta(days=7):
                            continue
                        ev_title = str(ev.get("summary") or ev.get("title") or "")
                        dedupe_key = f"{ev_title}_{dt_str}"
                        if dedupe_key in processed_events:
                            continue
                        processed_events.add(dedupe_key)
                        ev["_calendar"] = cname
                        clean_cal.append(ev)
                        added += 1
                    except Exception:
                        clean_cal.append(ev)
                        added += 1
                else:
                    clean_cal.append(ev)
                    added += 1
            diag_logs.append(f"✅ Cal '{cname}' ({label}): kept {added} events.")
        except Exception as e:
            err = str(e).lower()
            if "not found" not in err and "404" not in err:
                diag_logs.append(f"⚠️ Cal '{cname}' ({label}) Err: {str(e)[:30]}")

    if not clean_cal:
        try:
            now_utc = datetime.now(timezone.utc)
            end_utc = now_utc + timedelta(days=2)
            local_rows = list_events_range(tenant_key, now_utc - timedelta(hours=12), end_utc) or []
            for row in local_rows:
                clean_cal.append(
                    {
                        "summary": str(row.get("title") or ""),
                        "title": str(row.get("title") or ""),
                        "start": {"dateTime": str(row.get("start_ts") or "")},
                        "end": {"dateTime": str(row.get("end_ts") or "")},
                        "_calendar": "EA Local",
                    }
                )
            if local_rows:
                diag_logs.append(f"✅ Local calendar fallback ({tenant_key}): {len(local_rows)} events.")
        except Exception as e:
            diag_logs.append(f"⚠️ Local calendar fallback error: {str(e)[:40]}")

    return SourceAcquisitionResult(
        mails=clean_mails,
        calendar_events=clean_cal,
        accounts=accounts,
        diagnostics=diag_logs,
    )
