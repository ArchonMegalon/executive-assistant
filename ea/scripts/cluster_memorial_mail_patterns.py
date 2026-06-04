#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg

TEXT_SQL = "lower(coalesce(fact_json->>'body_text','') || ' ' || coalesce(fact_json->>'subject','') || ' ' || coalesce(summary,''))"
DEFAULT_REPORT = Path('/docker/EA/memorial_data/private_memorial_profiles/manfred/mail_cluster_report.json')


@dataclass
class ClusterDef:
    key: str
    label: str
    axis: str
    summary_template: str
    keywords: tuple[str, ...]


CLUSTERS: tuple[ClusterDef, ...] = (
    ClusterDef(
        key='family_susanne_coordination',
        label='Susanna/Susi als knappe Alltags- und Mittraegerin',
        axis='episodic',
        summary_template='Mails mit Susanna-/Susi-Bezug wirken eher wie knappe Abstimmung, Mittragen und Alltagskoordination als wie ausformulierte Emotionalität.',
        keywords=('susanne', 'susi', 'susanna', 'stellungnahmen susanna und manfred hoza'),
    ),
    ClusterDef(
        key='family_children_noah',
        label='Kinder und Noah werden praktisch und fürsorglich gerahmt',
        axis='episodic',
        summary_template='Bei Kindern und Noah erscheinen Fürsorge, Termine, Hinweise und Verlässlichkeit stärker als gefühlige Ausschmückung.',
        keywords=(' noah', 'kind', 'kinder', 'geburtstagswünsche', 'geburtstagswuensche'),
    ),
    ClusterDef(
        key='family_operational_updates',
        label='Familie als praktische Koordination',
        axis='episodic',
        summary_template='Familienmails sind oft praktische Lageberichte, Reise- oder Ablaufabsprachen und knappe Danksagungen statt langer Intimität.',
        keywords=('lieber tibor', 'elisabeth', 'noah', 'eva', 'stefan', 'gertraud', 'famil', 'geburtstag', 'grüße', 'gruesse'),
    ),
    ClusterDef(
        key='offers_invoices_price_scrutiny',
        label='Angebote, Rechnungen, Preise werden seziert',
        axis='stylistic',
        summary_template='Bei Angeboten und Rechnungen prüft er Zahlen, Aufgliederungen, Farbnummern, Plausibilität und formale Abweichungen sehr genau.',
        keywords=('angebot', 'rechnung', 'preis', 'aufglieder', 'farbnummer', 'mitgliedsbeitrag', 'übermittlung des angebots', 'uebermittlung des angebots'),
    ),
    ClusterDef(
        key='travel_and_confirmation_management',
        label='Reisen und Bestätigungen werden administrativ behandelt',
        axis='stylistic',
        summary_template='Reise- und Verwaltungsfälle formuliert er als Statusklärung: was bestätigt ist, was fehlt, was umgebucht wurde und was schriftlich nachzureichen ist.',
        keywords=('reise', 'flug', 'rückflug', 'rueckflug', 'umbuch', 'bestätig', 'bestaetig', 'schriftliche mitteilung', 'gestrichen'),
    ),
    ClusterDef(
        key='medical_institutional_commentary',
        label='Gesundheit wird institutionell und risikobezogen gerahmt',
        axis='episodic',
        summary_template='Bei Krankenhaus, Ärzten und Behandlung spricht er eher über Risiken, Verfahren und institutionelle Bewertung als über eigene Verletzlichkeit.',
        keywords=('krankenhaus', 'arzt', 'ärzt', 'behandlung', 'aufnahme', 'gesund', 'impf', 'blutgruppe', 'nebenwirkungen'),
    ),
    ClusterDef(
        key='legal_political_forwarding_archive',
        label='Links, Verfahren und politische Materialien werden archiviert und weitergereicht',
        axis='legal',
        summary_template='Ein großer Teil der Mails dient dem Weiterleiten, Archivieren und Fallaufbau: Links, Verfahren, politische Hinweise und juristische Kontexte werden gesammelt und verteilt.',
        keywords=('zur information', 'fw:', 'wg:', 'weitergeleitet', 'revision', 'verhandlung', 'juridikum', 'mobbing', 'bundesverwaltungsgericht', 'parlament'),
    ),
    ClusterDef(
        key='channel_control_and_capacity',
        label='Er kontrolliert den Kommunikationskanal selbst',
        axis='stylistic',
        summary_template='Er besteht auf dem richtigen Kanal, der richtigen Adresse und funktionsfähiger Zustellung; selbst Postfachkapazität wird sofort zum geordneten Vorgang.',
        keywords=('gmx-anschrift', 'gmx-anschrift', 'speicherkapazität', 'speicherkapazitaet', 'andere e-mail-anschrift', 'nicht an meine gmx-anschrift', 'kapazität', 'kapazitaet'),
    ),
    ClusterDef(
        key='extended_family_travel_updates',
        label='Erweiterte Familie erhält Reise- und Lageupdates',
        axis='episodic',
        summary_template='An erweiterte Familie gehen häufig sachliche Reise-, Rückflug- und Lageupdates mit knapper Einordnung statt emotionaler Dramatisierung.',
        keywords=('liebe eva', 'lieber stefan', 'liebe gertraud', 'rückflug', 'rueckflug', 'peking', 'tokyo', 'fuerteventura', 'flug'),
    ),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())


def classify(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for cluster in CLUSTERS:
        if any(keyword in lowered for keyword in cluster.keywords):
            hits.append(cluster.key)
    return hits or ['unclassified']


def fetch_rows(conn: psycopg.Connection, principal_id: str) -> list[dict[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select
              item_id,
              coalesce(summary, ''),
              coalesce(fact_json->>'subject', ''),
              coalesce(fact_json->>'body_text', ''),
              coalesce(fact_json->>'body_excerpt', ''),
              coalesce(fact_json->>'from', ''),
              coalesce(fact_json->>'date', '')
            from memory_items
            where principal_id=%s and category='memorial_mail_message'
            order by created_at desc
            """,
            (principal_id,),
        )
        rows = []
        for item_id, summary, subject, body_text, body_excerpt, sender, date in cur.fetchall():
            rows.append({
                'item_id': item_id,
                'summary': summary,
                'subject': subject,
                'body_text': body_text,
                'body_excerpt': body_excerpt,
                'from': sender,
                'date': date,
            })
        return rows


def build_report(rows: list[dict[str, str]]) -> dict[str, object]:
    counter: Counter[str] = Counter()
    examples: dict[str, list[dict[str, str]]] = {c.key: [] for c in CLUSTERS}
    examples['unclassified'] = []
    for row in rows:
        text = normalize(' '.join([row['summary'], row['subject'], row['body_text']]))
        keys = classify(text)
        for key in keys:
            counter[key] += 1
            if len(examples[key]) < 4:
                examples[key].append({
                    'subject': normalize(row['subject'])[:180],
                    'excerpt': normalize(row['body_excerpt'])[:240],
                    'date': row['date'],
                })
    cluster_payloads = []
    for cluster in CLUSTERS:
        cluster_payloads.append({
            'key': cluster.key,
            'label': cluster.label,
            'memory_axis': cluster.axis,
            'count': counter.get(cluster.key, 0),
            'summary': cluster.summary_template,
            'examples': examples[cluster.key],
        })
    if counter.get('unclassified'):
        cluster_payloads.append({
            'key': 'unclassified',
            'label': 'Nicht klassifiziert',
            'memory_axis': 'general',
            'count': counter['unclassified'],
            'summary': 'Mails ohne klaren Themen-Treffer in den derzeitigen Clustern.',
            'examples': examples['unclassified'],
        })
    return {
        'principal_id': 'memorial:manfred',
        'generated_at': now_iso(),
        'mail_count': len(rows),
        'clusters': cluster_payloads,
    }


def upsert_cluster_memory_items(conn: psycopg.Connection, principal_id: str, report: dict[str, object]) -> int:
    ts = now_iso()
    with conn.cursor() as cur:
        cur.execute(
            "delete from memory_items where principal_id=%s and category='memorial_mail_cluster_summary'",
            (principal_id,),
        )
        inserted = 0
        for cluster in report['clusters']:
            if int(cluster.get('count') or 0) <= 0:
                continue
            summary = f"{cluster['label']}: {cluster['summary']} ({cluster['count']} Mails)"
            fact_json = {
                'memory_kind': 'mail_cluster_summary',
                'memory_axis': cluster['memory_axis'],
                'cluster_key': cluster['key'],
                'cluster_label': cluster['label'],
                'mail_count': cluster['count'],
                'summary': cluster['summary'],
                'examples': cluster['examples'],
            }
            provenance_json = {
                'source': 'memorial_mail_cluster_report',
                'generated_at': report['generated_at'],
            }
            cur.execute(
                """
                insert into memory_items
                (item_id, principal_id, category, summary, fact_json, provenance_json,
                 confidence, sensitivity, sharing_policy, last_verified_at, reviewer,
                 created_at, updated_at)
                values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()), principal_id, 'memorial_mail_cluster_summary', summary,
                    json.dumps(fact_json, ensure_ascii=False), json.dumps(provenance_json, ensure_ascii=False),
                    0.82, 'internal', 'private', ts, 'codex', ts, ts,
                ),
            )
            inserted += 1
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--principal-id', default='memorial:manfred')
    parser.add_argument('--report-path', default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    conn = psycopg.connect(os.environ['DATABASE_URL'])
    rows = fetch_rows(conn, args.principal_id)
    report = build_report(rows)
    inserted = upsert_cluster_memory_items(conn, args.principal_id, report)
    conn.commit()
    path = Path(args.report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'mail_count': len(rows), 'cluster_memories_written': inserted, 'report_path': str(path)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
