# ChatGPT/Claude used for troubleshooting, suggestions and generating
import os
from datetime import datetime
from sqlalchemy import func
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from models import Product, StockMovement, Supplier
from models import Product, StockMovement, Supplier, PurchaseOrder
from email_service import send_email
# routes blueprint
bp = Blueprint("main", __name__)
# gets string values from forms
def get_str(name, default=""):
    return (request.form.get(name, default) or "").strip()
# gets numeric values from forms
def get_float(name, default=0.0):
    try:
        return float(request.form.get(name, default))
    except Exception:
        return default
# products list route with searching feature
@bp.route("/products")
def products():
    q = (request.args.get("q") or "").strip()
    query = Product.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Product.product_code.ilike(like)) | (Product.name.ilike(like))
        )
    items = query.order_by(Product.name.asc()).all()
    return render_template("products.html", items=items, q=q)
# creating new products route
@bp.route("/products/new", methods=["GET", "POST"])
def product_new():
    if request.method == "POST":
        supplier_id_raw = (request.form.get("supplier_id") or "").strip()
        supplier_id = int(supplier_id_raw) if supplier_id_raw else None
        p = Product(
            product_code=get_str("product_code"),
            name=get_str("name"),
            description=get_str("description"),
            current_stock=get_float("current_stock"),
            demand_per_day=get_float("demand_per_day"),
            lead_days=get_float("lead_days"),
            max_stock=get_float("max_stock"),
        )
        p.supplier_id = supplier_id
        # If lead_days left at 0 and supplier has a default lead days use supplier lead days from db - some may have dif
        if (p.lead_days or 0) == 0 and p.supplier_id:
            s = Supplier.query.get(p.supplier_id)
            if s and s.lead_days:
                p.lead_days = float(s.lead_days)
        if not p.product_code or not p.name:
            flash("Product Code and Name are required.", "danger")
            return redirect(url_for("main.product_new"))
        db.session.add(p)
        db.session.commit()
        flash("Product created.", "success")
        return redirect(url_for("main.products"))
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    return render_template("product_form.html", item=None, suppliers=suppliers)
# editing route
@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
def product_edit(pid):
    p = Product.query.get_or_404(pid)
    if request.method == "POST":
        supplier_id_raw = (request.form.get("supplier_id") or "").strip()
        p.supplier_id = int(supplier_id_raw) if supplier_id_raw else None
        p.product_code = get_str("product_code") or p.product_code
        p.name = get_str("name") or p.name
        p.description = get_str("description")
        p.current_stock = get_float("current_stock", p.current_stock)
        p.demand_per_day = get_float("demand_per_day", p.demand_per_day)
        p.lead_days = get_float("lead_days", p.lead_days)
        p.max_stock = get_float("max_stock", p.max_stock)
        # If lead_days left at 0 and supplier has a default, copy it across
        if (p.lead_days or 0) == 0 and p.supplier_id:
            s = Supplier.query.get(p.supplier_id)
            if s and s.lead_days:
                p.lead_days = float(s.lead_days)
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(url_for("main.products"))
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    return render_template("product_form.html", item=p, suppliers=suppliers)
# deletion route
@bp.route("/products/<int:pid>/delete", methods=["POST"])
def product_delete(pid):
    p = Product.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    flash("Product deleted.", "warning")
    return redirect(url_for("main.products"))
# addition of stock route
@bp.route("/products/<int:pid>/add_stock", methods=["POST"])
def product_add_stock(pid):
    p = Product.query.get_or_404(pid)
    qty = get_float("qty", 0.0)
    if qty <= 0:
        flash("Quantity must be greater than zero", "danger")
        return redirect(url_for("main.product_edit", pid=pid))
    p.current_stock = (p.current_stock or 0.0) + qty
    # Existing low-stock flag reset uses ROP
    rop = p.compute_rop()
    if p.current_stock >= rop and p.notified_low:
        p.notified_low = False
    # allows supplier reorder email again once stock is above threshold
    trigger_level = p.reorder_trigger_level()
    if p.current_stock >= trigger_level and p.notified_supplier_rop:
        p.notified_supplier_rop = False
    m = StockMovement(product_id=pid, movement_type="Delivery", qty_change=qty)
    db.session.add(m)
    db.session.commit()
    flash("Stock Updated", "success")
    return redirect(url_for("main.product_edit", pid=pid))
# issuing of stock route
@bp.route("/products/<int:pid>/issue_stock", methods=["POST"])
def product_issue_stock(pid):
    p = Product.query.get_or_404(pid)
    qty = get_float("qty", 0.0)
    location = get_str("location")
    if qty <= 0:
        flash("Quantity must be greater than zero.", "danger")
        return redirect(url_for("main.product_edit", pid=pid))
    if qty > (p.current_stock or 0.0):
        flash("Not enough stock to issue.", "danger")
        return redirect(url_for("main.product_edit", pid=pid))
    p.current_stock = float(p.current_stock or 0.0) - qty
    # Kanban/ROP - hybrid trigger warning
    trigger_level = p.reorder_trigger_level()
    if p.current_stock < trigger_level:
        label = "Kanban trigger" if p.is_kanban() else "ROP"
        flash(
            f"Warning: stock for {p.name} is below {label}. Current stock: {p.current_stock}.",
            "warning",
        )
    m = StockMovement(product_id=pid, movement_type="ISSUE", qty_change=-qty, location=location)
    db.session.add(m)
    db.session.commit()
    # Reorder email is handled by the polling script (check_stock_poll.py)
    # which runs via Windows Task Scheduler every 5 minutes.
    flash("Stock issued and updated.", "success")
    return redirect(url_for("main.product_edit", pid=pid))
# low stock route
@bp.route("/low-stock-dashboard")
def low_stock_dashboard():
    products = Product.query.order_by(Product.name.asc()).all()
    rows = []
    for p in products:
        current = float(p.current_stock or 0.0)
        trigger = p.reorder_trigger_level()
        threshold = trigger + (trigger * 0.125)
        if current <= threshold:
            rows.append({
                "product": p,
                "current": current,
                "rop": trigger,
                "threshold": threshold,
                "below_rop": current < trigger,
                "is_kanban": p.is_kanban(),
                "max_stock": float(p.max_stock or 0.0),
                "suggested_order": p.suggested_order_qty_display(),
            })
    return render_template("low_stock_dashboard.html", rows=rows)
# idle stock route
@bp.route("/idle-stock-dashboard")
def idle_stock_dashboard():
    IDLE_DAYS = 90
    manager_email = (os.getenv("MANAGER_EMAIL") or "").strip()
    email_enabled = bool(manager_email)
    rows = []
    products = Product.query.order_by(Product.name.asc()).all()
    for p in products:
        current = float(p.current_stock or 0.0)
        if current <= 0:
            continue
        last_move = (
            db.session.query(func.max(StockMovement.created_at))
            .filter(StockMovement.product_id == p.id)
            .scalar()
        )
        # (demo - all new products set up are instantly idle)
        if last_move is None:
            days_idle = IDLE_DAYS
        else:
            days_idle = (datetime.utcnow() - last_move).days
        if days_idle >= IDLE_DAYS:
            rows.append({
                "product": p,
                "current_stock": current,
                "last_move": last_move,
                "days_idle": days_idle,
                "email_sent": bool(p.notified_idle),
            })
            # Send email once per product so no spam
            if email_enabled and not p.notified_idle:
                try:
                    subject = f"Idle Stock Alert – {p.name} (No movement in {IDLE_DAYS} days)"
                    body = (
                        f"Idle Stock Notification\n\n"
                        f"Product: {p.name}\n"
                        f"Code: {p.product_code}\n"
                        f"Quantity in storage: {current:.2f}\n"
                        f"Days since last movement: {days_idle}\n\n"
                        f"Regards,\nInventory System"
                    )
                    send_email(to_email=manager_email, subject=subject, body=body)
                    p.notified_idle = True
                    db.session.commit()
                    flash(f"Idle stock email sent for {p.name}.", "success")
                except Exception as e:
                    db.session.rollback()
                    flash(f"Failed to send idle email for {p.name}: {e}", "danger")
    return render_template(
        "idle_stock_dashboard.html",
        rows=rows,
        idle_days=IDLE_DAYS,
    )
@bp.route("/products/<int:pid>/reset-idle-notification", methods=["POST"])
def reset_idle_notification(pid):
    p = Product.query.get_or_404(pid)
    p.notified_idle = False
    db.session.commit()
    flash("Idle notification reset.", "warning")
    return redirect(url_for("main.idle_stock_dashboard"))
