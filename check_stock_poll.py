"""
check_stock_poll.py
-------------------
Standalone polling script for automatic low-stock detection and reorder emails.
Mirrors the supplier email logic in product_issue_stock() (views.py), but runs
independently of any user action so it can be scheduled via Windows Task Scheduler.

WINDOWS TASK SCHEDULER SETUP
------------------------------
1. Open Task Scheduler → Create Basic Task
2. Trigger:   Daily → repeat every 1 minute (set "Repeat task every: 1 minute"
              in Advanced settings → indefinitely)
3. Action:    Start a Program
   Program:   C:\\path\\to\\python.exe
   Arguments: C:\\path\\to\\Iter6_DMCM_122428726_FYP\\check_stock_poll.py
   Start in:  C:\\path\\to\\Iter6_DMCM_122428726_FYP
4. Ensure the .env file is present in the project directory (same one Flask uses).
5. Ensure all packages from requirements.txt are installed in the Python environment.

DEDUPLICATION
-------------
The script relies on the existing notified_supplier_rop flag on each Product.
- Email is only sent if current_stock < trigger level AND notified_supplier_rop is False.
- notified_supplier_rop is reset to False automatically by the Flask app when a
  delivery brings stock back above the trigger level (product_add_stock in views.py).
  This means no duplicate emails are sent during a single low-stock period.

OUTPUT / LOGGING
----------------
A rolling log is written to poll_log.txt in the project directory.
Check this file to verify Task Scheduler runs are working correctly.
"""

import os
import sys
import logging

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poll_log.txt")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Bootstrap Flask app context ───────────────────────────────────────────────
# Insert project root so that app.py / models.py / email_service.py resolve correctly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from models import Product, PurchaseOrder
from email_service import send_email


def check_low_stock():
    app = create_app()
    with app.app_context():
        products = Product.query.all()
        checked = 0
        emailed = 0

        for p in products:
            trigger_level = p.reorder_trigger_level()
            current = float(p.current_stock or 0.0)

            # Stock is fine or reorder email already sent — nothing to do
            if current >= trigger_level or p.notified_supplier_rop:
                continue

            # Below trigger but no supplier email configured — log and skip
            if not p.supplier or not p.supplier.email:
                log.warning(
                    "LOW STOCK – %s (id=%d) is below trigger (%.2f) but has no supplier email.",
                    p.name, p.id, trigger_level,
                )
                continue

            checked += 1
            try:
                po_record = PurchaseOrder(po_number="PENDING", product_id=p.id)
                db.session.add(po_record)
                db.session.flush()
                po_number = f"PO{70000000 + po_record.id}"
                po_record.po_number = po_number

                if p.is_kanban():
                    subject = f"Kanban Replenishment – {p.name} [{po_number}]"
                    trigger_label = "Kanban trigger level"
                else:
                    subject = f"Reorder Request – {p.name} (Below ROP) [{po_number}]"
                    trigger_label = "ROP"

                body = (
                    f"Hello {p.supplier.contact_name},\n\n"
                    f"Purchase Order Number: {po_number}\n\n"
                    f"{p.name} (Code: {p.product_code}) requires replacement.\n\n"
                    f"Current stock: {current:.2f}\n"
                    f"{trigger_label}: {trigger_level:.2f}\n"
                    f"Max Order: {p.max_stock}.\n\n"
                    f"Please confirm receipt of this email and availability.\n\n"
                    f"Regards,\nInventory System"
                )

                send_email(to_email=p.supplier.email, subject=subject, body=body)
                p.notified_supplier_rop = True
                db.session.commit()
                emailed += 1
                log.info(
                    "Reorder email sent – %s (id=%d) | %s | stock=%.2f trigger=%.2f",
                    p.name, p.id, po_number, current, trigger_level,
                )

            except Exception as exc:
                db.session.rollback()
                log.error(
                    "Failed to send reorder email for %s (id=%d): %s",
                    p.name, p.id, exc,
                )

        log.info("Poll complete – %d product(s) needed reorder, %d email(s) sent.", checked, emailed)


if __name__ == "__main__":
    log.info("── Poll started ──")
    try:
        check_low_stock()
    except Exception as exc:
        log.critical("Unhandled error in poll: %s", exc, exc_info=True)
        sys.exit(1)
