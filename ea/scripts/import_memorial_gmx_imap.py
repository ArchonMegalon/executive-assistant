from __future__ import annotations

import argparse
import email
import imaplib
import mailbox
import shutil
import sys
import tempfile
from dataclasses import dataclass
from email.message import Message
from email.policy import default as default_email_policy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.container import build_container
from app.services.memorial_memory import ingest_memorial_mail_archive, memorial_memory_principal_id
from app.api.routes.public_memorials import _load_memorial, _load_private_profile


@dataclass
class ImapAttempt:
    host: str
    port: int
    ok: bool
    detail: str


def _decode_mailbox_name(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "ignore")
    return str(raw)


def _candidate_sent_mailboxes(lines: list[bytes]) -> list[str]:
    candidates: list[str] = []
    for raw_line in lines:
        line = _decode_mailbox_name(raw_line)
        upper = line.upper()
        if "\\SENT" in upper or "GESENDET" in upper or "SENT" in upper:
            if '"' in line:
                name = line.rsplit('"', 2)[1]
            else:
                parts = line.split(" ", 2)
                name = parts[-1] if parts else ""
            name = name.strip().strip('"')
            if name and name not in candidates:
                candidates.append(name)
    for fallback in ("Sent", "Sent Objects", "Gesendet", "INBOX.Sent", "INBOX.Gesendet"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _iter_folder_messages(imap_conn: imaplib.IMAP4_SSL, mailbox_name: str, limit: int) -> list[bytes]:
    status, _ = imap_conn.select(f'"{mailbox_name}"', readonly=True)
    if status != "OK":
        return []
    status, data = imap_conn.search(None, "ALL")
    if status != "OK" or not data or not data[0]:
        return []
    ids = [item for item in data[0].split() if item.strip()]
    if limit > 0:
        ids = ids[-limit:]
    messages: list[bytes] = []
    for msg_id in ids:
        fetch_status, payload = imap_conn.fetch(msg_id, "(RFC822)")
        if fetch_status != "OK" or not payload:
            continue
        for part in payload:
            if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
                messages.append(part[1])
                break
    return messages


def _write_eml_drop(raw_messages: list[bytes], output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for index, raw in enumerate(raw_messages, start=1):
        try:
            message: Message = email.message_from_bytes(raw, policy=default_email_policy)
            subject = str(message.get("Subject") or "").strip()[:80]
        except Exception:
            subject = ""
        safe_subject = "".join(ch for ch in subject if ch.isalnum() or ch in {"-", "_", " "}).strip().replace(" ", "_")
        filename = f"{index:05d}"
        if safe_subject:
            filename += f"_{safe_subject}"
        path = output_dir / f"{filename}.eml"
        path.write_bytes(raw)
        written += 1
    return written


def _write_mbox(raw_messages: list[bytes], output_path: Path) -> int:
    box = mailbox.mbox(str(output_path), create=True)
    box.lock()
    try:
        for raw in raw_messages:
            message: Message = email.message_from_bytes(raw, policy=default_email_policy)
            box.add(message)
        box.flush()
        return len(raw_messages)
    finally:
        try:
            box.unlock()
        except Exception:
            pass
        box.close()


def _try_imap_login(host: str, port: int, login_user: str, password: str) -> tuple[imaplib.IMAP4_SSL | None, ImapAttempt]:
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn._encoding = "utf-8"
        conn.login(login_user, password)
        return conn, ImapAttempt(host=host, port=port, ok=True, detail="login_ok")
    except Exception as exc:
        try:
            conn.logout()  # type: ignore[name-defined]
        except Exception:
            pass
        return None, ImapAttempt(host=host, port=port, ok=False, detail=repr(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Import GMX Sent mail into memorial memory.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--email", required=True)
    parser.add_argument("--login-user", default="")
    parser.add_argument("--password", required=True)
    parser.add_argument("--host", default="imap.gmx.net")
    parser.add_argument("--port", type=int, default=993)
    parser.add_argument("--fallback-host", action="append", default=["imap.gmx.com"])
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--mailbox", default="")
    parser.add_argument("--reviewer", default="gmx-imap-import")
    args = parser.parse_args()

    memorial = _load_memorial(args.slug)
    _load_private_profile(args.slug)
    principal_id = memorial_memory_principal_id(args.slug, memorial)
    container = build_container()

    attempts: list[ImapAttempt] = []
    conn = None
    login_user = args.login_user.strip() or args.email.strip()
    hosts = [args.host, *[item for item in args.fallback_host if str(item).strip() and str(item).strip() != args.host]]
    for host in hosts:
        conn, attempt = _try_imap_login(host, args.port, login_user, args.password)
        attempts.append(attempt)
        if conn is not None:
            break
    if conn is None:
        raise RuntimeError(
            "gmx_imap_auth_failed: "
            + "; ".join(f"{item.host}:{item.port} -> {item.detail}" for item in attempts)
            + " | likely_causes=pop3_imap_disabled_or_app_password_required"
        )
    try:
        mailbox_names: list[str]
        if args.mailbox.strip():
            mailbox_names = [args.mailbox.strip()]
        else:
            status, mailboxes = conn.list()
            if status != "OK":
                raise RuntimeError("imap_list_failed")
            mailbox_names = _candidate_sent_mailboxes(list(mailboxes or []))
        raw_messages: list[bytes] = []
        selected_mailbox = ""
        for mailbox_name in mailbox_names:
            raw_messages = _iter_folder_messages(conn, mailbox_name, args.limit)
            if raw_messages:
                selected_mailbox = mailbox_name
                break
        if not raw_messages:
            raise RuntimeError("no_sent_messages_found")
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    with tempfile.TemporaryDirectory(prefix="ea-memorial-gmx-sent-") as tmp_dir:
        drop_dir = Path(tmp_dir) / "eml"
        mbox_path = Path(tmp_dir) / "sent.mbox"
        written = _write_eml_drop(raw_messages, drop_dir)
        mbox_written = _write_mbox(raw_messages, mbox_path)
        if written <= 0:
            raise RuntimeError("no_eml_written")
        if mbox_written <= 0:
            raise RuntimeError("no_mbox_written")
        result = ingest_memorial_mail_archive(
            memory_runtime=container.memory_runtime,
            principal_id=principal_id,
            memorial_slug=args.slug,
            source_path=str(mbox_path),
            mailbox_format="mbox",
            reviewer=args.reviewer,
            source_label=f"GMX Sent IMAP {selected_mailbox or args.mailbox or 'sent'}",
            sensitivity="private",
            max_messages=max(1, args.limit),
        )
        archive_root = Path("/data/artifacts/memorial_mail_archive") / args.slug / "gmx_sent_snapshot"
        archive_root.mkdir(parents=True, exist_ok=True)
        for item in drop_dir.glob("*.eml"):
            shutil.copy2(item, archive_root / item.name)
        print({
            "selected_mailbox": selected_mailbox,
            "fetched_messages": len(raw_messages),
            "written_eml": written,
            "written_mbox": mbox_written,
            "import_result": result,
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
