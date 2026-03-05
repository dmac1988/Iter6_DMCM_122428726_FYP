"""
check_stock_poll.py  –  Automatic low-stock detection & reorder emails
----------------------------------------------------------------------
Runs as a standalone script via Windows Task Scheduler (every 5 minutes).
Mirrors the supplier reorder email logic in product_issue_stock() (views.py).

WINDOWS TASK SCHEDULER SETUP
1. Open Task Scheduler  →  Create Basic Task  →  name it "Stock Poll"
2. Trigger:  Daily  →  in Advanced settings set
   "Repeat task every: 5 minutes"  /  "for a duration of: Indefinitely"
3. Action:  Start a Program
     Program/script :  C:\\path\\to\\python.exe
     Add arguments  :  check_stock_poll.py
     Start in       :  C:\\path\\to\\Iter6_DMCM_122428726_FYP
4. Make sure .env and requirements.txt packages are available.

HOW DEDUPLICATION WORKS
- Email is sent only when  current_stock < trigger_level  AND
  notified_supplier_rop is False.
- product_add_stock() in views.py resets notified_supplier_rop to False
  once a delivery brings stock back above the trigger level.
- This means: stock drops → email sent → stock replenished → flag reset
  → stock drops again → new email with new PO number.

LOGGING
- Every run is logged to  poll_log.txt  in the project directory.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------------------
# Logging  –  set up FIRST so any later failure is captured in the log file.
# Uses a 1 MB rotating log so the file never grows unbounded.
# Also logs to stdout so Task Scheduler's "Last Run Result" is meaningful.
# ---------------------------------------------------------------------------
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_PATH = os.path.join(_PROJECT_DIR, "poll_log.txt")

log = logging.getLogger("stock_poll")
log.setLevel(logging.INFO)

_fmt = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# File handler  –  rotates at 1 MB, keeps 3 back-ups
_fh = RotatingFileHandler(_LOG_PATH, maxBytes=1_048_576, backupCount=3)
_fh.setFormatter(_fmt)
log.addHandler(_fh)

# Console handler  –  so output also appears in Task Scheduler history
_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)
log.addHandler(_ch)

log.info("--- Poll run started ---")

# ---------------------------------------------------------------------------
# Bootstrap  –  add project root to sys.path, then import Flask app & models.
# Wrapped in try/except so import errors appear in poll_log.txt.
# ---------------------------------------------------------------------------
sys.path.insert(0, _PROJECT_DIR)

try:
    from app import create_app, db          # noqa: E402
    from models import Product, PurchaseOrder  # noqa: E402
    from email_service import send_email    # noqa: E402
except Exception as exc:
    log.critical("Import failed: %s", exc, exc_info=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Core polling logic
# ---------------------------------------------------------------------------
def check_low_stock():
    """Scan every product; send a reorder email for each that is below its
    trigger level and has not already been notified."""

    app = create_app()
    with app.app_context():
        products = Product.query.all()
        reorder_needed = 0
        emails_sent = 0

        for p in products:
            trigger = p.reorder_trigger_level()
            stock = float(p.current_stock or 0.0)

            # Already notified for this low-stock period → skip
            if p.notified_supplier_rop:
                if stock < trigger:
                    log.info(
                        "SKIP (already notified)  %s  stock=%.2f  trigger=%.2f",
                        p.name, stock, trigger,
                    )
                continue

            # Stock is at or above trigger → nothing to do
            if stock >= trigger:
                continue

            # Below trigger but no supplier email on file → warn and skip
            if not p.supplier or not p.supplier.email:
                log.warning(
                    "LOW STOCK  %s (id=%d)  stock=%.2f  trigger=%.2f  "
                    "- no supplier email configured, skipping.",
                    p.name, p.id, stock, trigger,
                )
                continue

            reorder_needed += 1

            # ── Build PO and email (same logic as views.product_issue_stock) ──
            try:
                # Create PurchaseOrder row, then derive the PO number from its id
                po = PurchaseOrder(po_number="PENDING", product_id=p.id)
                db.session.add(po)
                db.session.flush()                       # assigns po.id
                po.po_number = f"PO{70000000 + po.id}"

                if p.is_kanban():
                    subject = (
                        f"Kanban Replenishment – {p.name} [{po.po_number}]"
                    )
                    trigger_label = "Kanban trigger level"
                else:
                    subject = (
                        f"Reorder Request – {p.name} (Below ROP) [{po.po_number}]"
                    )
                    trigger_label = "ROP"

                body = (
                    f"Hello {p.supplier.contact_name},\n\n"
                    f"Purchase Order Number: {po.po_number}\n\n"
                    f"{p.name} (Code: {p.product_code}) requires replacement.\n\n"
                    f"Current stock: {stock:.2f}\n"
                    f"{trigger_label}: {trigger:.2f}\n"
                    f"Max Order: {p.max_stock}.\n\n"
                    f"Please confirm receipt of this email and availability.\n\n"
                    f"Regards,\nInventory System"
                )

                send_email(to_email=p.supplier.email, subject=subject, body=body)

                p.notified_supplier_rop = True
                db.session.commit()
                emails_sent += 1

                log.info(
                    "REORDER EMAIL SENT  %s (id=%d)  %s  stock=%.2f  trigger=%.2f",
                    p.name, p.id, po.po_number, stock, trigger,
                )

            except Exception as exc:
                db.session.rollback()
                log.error(
                    "FAILED to email for %s (id=%d): %s",
                    p.name, p.id, exc, exc_info=True,
                )

        log.info(
            "--- Poll complete - %d product(s) below trigger, %d email(s) sent ---",
            reorder_needed, emails_sent,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        check_low_stock()
    except Exception as exc:
        log.critical("Unhandled error: %s", exc, exc_info=True)
        sys.exit(1)
