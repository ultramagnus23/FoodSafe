"""
FoodSafe India — Alert Notification Service (email only)

Intended to run as part of the nightly aggregation job, after
models/disease_burden.py and models/codex_benchmark.py have refreshed
exposure_alerts. For each active alert:

  1. Find subscriptions matching (district_id, commodity_id, contaminant_id)
     — NULL on a subscription field means "any" — where the alert's
     severity meets or exceeds the subscription's severity_threshold and
     the alert_type is in the subscription's alert_types.
  2. Skip subscriptions already notified for this alert within 7 days.
  3. Send an email via Resend (https://resend.com) if RESEND_API_KEY is
     set; otherwise log and skip — this is a legitimate "not configured"
     state, not an error, same honest-stub pattern used elsewhere in this
     codebase (e.g. USFDA scraper limits, Codex benchmark data gaps).
  4. Update last_notified_at.

WhatsApp is intentionally out of scope for this pass.

Uses only the standard library (urllib) for the Resend HTTP call so this
doesn't need a new dependency in requirements-api.txt — this module isn't
imported by api.main, it's a standalone batch job like models/aggregate.py.

Run:  python -m models.notifications
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("foodsafe.models.notifications")

RESEND_API_URL = "https://api.resend.com/emails"
RENOTIFY_COOLDOWN_DAYS = 7
FROM_ADDRESS = os.environ.get("ALERTS_FROM_EMAIL", "alerts@foodsafe.in")

SEVERITY_RANK = {"moderate": 0, "high": 1, "critical": 2}

EMAIL_TEMPLATE = """\
FoodSafe Alert — {district_name}, {state}

{commodity_name} contamination update:

Contaminant: {contaminant_name}
Level: {mean_ppb} PPB
FSSAI limit: {fssai_limit_ppb} PPB
Codex Alimentarius limit: {codex_limit_ppb} PPB
Based on {n_samples} enforcement records.

View full report: https://foodsafe.in/district/{district_id}

Statistical estimate. Not a product verdict. Not medical advice.
Manage your alert subscriptions: https://foodsafe.in/account/alerts
"""


class NotificationService:
    def __init__(self, conn=None):
        self._conn = conn
        self._owns_conn = conn is None
        self._resend_key = os.environ.get("RESEND_API_KEY")
        if not self._resend_key:
            logger.warning(
                "RESEND_API_KEY not set — notifications will be computed but not sent. "
                "Set it in .env / Render env vars to enable email delivery."
            )

    def _get_conn(self):
        if self._conn is None:
            from pipeline.config import pg_connect
            self._conn = pg_connect()
        return self._conn

    def _send_email(self, to_email: str, subject: str, body: str) -> bool:
        if not self._resend_key:
            logger.info("[DRY RUN] Would email %s: %s", to_email, subject)
            return False
        payload = json.dumps({
            "from": FROM_ADDRESS,
            "to": [to_email],
            "subject": subject,
            "text": body,
        }).encode()
        req = urllib.request.Request(
            RESEND_API_URL, data=payload, method="POST",
            headers={"Authorization": f"Bearer {self._resend_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as e:
            logger.error("Resend API error %s: %s", e.code, e.read().decode(errors="replace"))
            return False
        except Exception:
            logger.exception("Failed to send notification email to %s", to_email)
            return False

    def run_pending_notifications(self) -> dict:
        import psycopg2.extras

        conn = self._get_conn()
        cutoff = datetime.now(timezone.utc) - timedelta(days=RENOTIFY_COOLDOWN_DAYS)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ea.id AS alert_id, ea.district_id, ea.commodity_id, ea.contaminant_id,
                       ea.alert_type, ea.severity, ea.mean_exposure_ppb, ea.codex_limit_ppb,
                       ea.fssai_limit_ppb, ea.n_samples,
                       d.name_canonical AS district_name, d.state,
                       c.name_canonical AS commodity_name, cnt.name_canonical AS contaminant_name
                FROM exposure_alerts ea
                JOIN districts d ON d.id = ea.district_id
                JOIN commodities c ON c.id = ea.commodity_id
                JOIN contaminants cnt ON cnt.id = ea.contaminant_id
                WHERE ea.active = TRUE
                """
            )
            alerts = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT s.id, s.user_id, s.district_id, s.commodity_id, s.contaminant_id,
                       s.alert_types, s.severity_threshold, s.last_notified_at, u.email
                FROM alert_subscriptions s
                JOIN users u ON u.id = s.user_id
                WHERE s.active = TRUE
                """
            )
            subs = [dict(r) for r in cur.fetchall()]

        sent = 0
        skipped_not_configured = 0
        skipped_cooldown = 0

        with conn.cursor() as cur:
            for alert in alerts:
                for sub in subs:
                    if sub["district_id"] is not None and sub["district_id"] != alert["district_id"]:
                        continue
                    if sub["commodity_id"] is not None and sub["commodity_id"] != alert["commodity_id"]:
                        continue
                    if sub["contaminant_id"] is not None and sub["contaminant_id"] != alert["contaminant_id"]:
                        continue
                    if alert["alert_type"] not in (sub["alert_types"] or []):
                        continue
                    if SEVERITY_RANK.get(alert["severity"], 0) < SEVERITY_RANK.get(sub["severity_threshold"], 0):
                        continue
                    if sub["last_notified_at"] and sub["last_notified_at"] >= cutoff:
                        skipped_cooldown += 1
                        continue

                    body = EMAIL_TEMPLATE.format(
                        district_name=alert["district_name"], state=alert["state"],
                        commodity_name=alert["commodity_name"], contaminant_name=alert["contaminant_name"],
                        mean_ppb=alert["mean_exposure_ppb"], fssai_limit_ppb=alert["fssai_limit_ppb"],
                        codex_limit_ppb=alert["codex_limit_ppb"], n_samples=alert["n_samples"],
                        district_id=alert["district_id"],
                    )
                    subject = f"FoodSafe Alert: {alert['commodity_name']} in {alert['district_name']}"
                    ok = self._send_email(sub["email"], subject, body)
                    if ok:
                        sent += 1
                    elif not self._resend_key:
                        skipped_not_configured += 1

                    cur.execute(
                        "UPDATE alert_subscriptions SET last_notified_at = NOW() WHERE id = %s",
                        (sub["id"],),
                    )
        conn.commit()

        summary = {
            "alerts_checked": len(alerts),
            "subscriptions_checked": len(subs),
            "sent": sent,
            "skipped_not_configured": skipped_not_configured,
            "skipped_cooldown": skipped_cooldown,
        }
        logger.info("Notification run complete: %s", summary)
        return summary

    def close(self):
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    service = NotificationService()
    try:
        summary = service.run_pending_notifications()
    finally:
        service.close()
    print("\n=== NOTIFICATION SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
