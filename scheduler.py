# ChatGPT/Claude used for troubleshooting, suggestions and generating
from app import db
from models import PendingReorder, PurchaseOrder, PurchaseOrderItem
from email_service import send_email


def consolidate_pending_reorders(app):
    """
    Groups all unprocessed PendingReorder entries by supplier and generates
    one consolidated PurchaseOrder per supplier. Called at 3 PM daily by APScheduler,
    or manually via /run-consolidation.
    Returns a list of (message, flash_category) tuples.
    """
    messages = []

    with app.app_context():
        pending_items = PendingReorder.query.filter_by(processed=False).all()

        if not pending_items:
            messages.append(("No pending reorders to consolidate.", "info"))
            return messages

        # Group by supplier, skipping products with no supplier/email
        by_supplier = {}
        for pr in pending_items:
            p = pr.product
            if not p.supplier or not p.supplier.email:
                continue
            sid = p.supplier_id
            if sid not in by_supplier:
                by_supplier[sid] = {"supplier": p.supplier, "pending": []}
            by_supplier[sid]["pending"].append(pr)

        for sid, data in by_supplier.items():
            supplier = data["supplier"]
            pending_group = data["pending"]

            # Create the consolidated PO record
            po_record = PurchaseOrder(po_number="PENDING", supplier_id=sid)
            db.session.add(po_record)
            db.session.flush()
            po_number = f"PO{70000000 + po_record.id}"
            po_record.po_number = po_number

            # Build line items and email body rows
            email_lines = []
            for pr in pending_group:
                p = pr.product
                trigger_level = p.reorder_trigger_level()
                suggested_qty = p.suggested_order_qty_display()
                label = "Kanban trigger" if p.is_kanban() else "ROP"

                poi = PurchaseOrderItem(
                    po_id=po_record.id,
                    product_id=p.id,
                    current_stock=float(p.current_stock or 0.0),
                    trigger_level=trigger_level,
                    suggested_qty=suggested_qty,
                )
                db.session.add(poi)
                pr.processed = True

                email_lines.append(
                    f"  - {p.name} (Code: {p.product_code})\n"
                    f"    Current Stock: {float(p.current_stock or 0.0):.2f} | "
                    f"{label}: {trigger_level:.2f} | "
                    f"Suggested Order Qty: {suggested_qty:.2f}"
                )

            item_count = len(email_lines)
            subject = (
                f"Consolidated Reorder Request [{po_number}] "
                f"– {item_count} item{'s' if item_count != 1 else ''}"
            )
            body = (
                f"Hello {supplier.contact_name},\n\n"
                f"Purchase Order Number: {po_number}\n\n"
                f"The following {item_count} item{'s' if item_count != 1 else ''} "
                f"require{'s' if item_count == 1 else ''} replenishment:\n\n"
                + "\n\n".join(email_lines)
                + "\n\nPlease confirm receipt of this order and confirm availability.\n\n"
                "Regards,\nInventory System"
            )

            try:
                send_email(to_email=supplier.email, subject=subject, body=body)
                db.session.commit()
                messages.append((
                    f"Consolidated PO {po_number} sent to {supplier.name} "
                    f"({item_count} item{'s' if item_count != 1 else ''}).",
                    "success",
                ))
            except Exception as e:
                db.session.rollback()
                messages.append((
                    f"PO for {supplier.name} failed to send: {e}",
                    "danger",
                ))

    return messages
