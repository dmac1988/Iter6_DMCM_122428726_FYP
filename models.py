# ChatGPT/Claude used for troubleshooting, suggestions and generating
from app import db
from datetime import datetime
# storing suppliers and products
class Supplier(db.Model):
    __tablename__ = "supplier"
    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    contact_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(320), nullable=False)
    lead_days = db.Column(db.Integer, nullable=False, default=0)
class Product(db.Model):
    __tablename__ = "product"
    id = db.Column(db.BigInteger, primary_key=True)
    product_code = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    # attributes for calculating ROP
    current_stock = db.Column(db.Float, default=0.0)
    demand_per_day = db.Column(db.Float, default=0.0)
    lead_days = db.Column(db.Float, default=0.0)
    max_stock = db.Column(db.Float, default=0.0)
    notified_idle = db.Column(db.Boolean, default=False)
    notified_low = db.Column(db.Boolean, default=False)
    # supplier link + reorder notification flag
    supplier_id = db.Column(db.BigInteger, db.ForeignKey("supplier.id"))
    supplier = db.relationship("Supplier", backref=db.backref("products", lazy=True))
    notified_supplier_rop = db.Column(db.Boolean, default=False)
    # KANBAN re ordering(PJD)
    def is_kanban(self):
        return self.supplier is not None and self.supplier.name == "PJD Safety Supplies"
    def reorder_trigger_level(self):
        if self.is_kanban():
            max_level = float(self.max_stock or 0.0)
            return (max_level / 2.0) if max_level > 0 else 0.0
        return float(self.compute_rop())
    # ROP + ordering
    # ROP = demand_per_day * lead_days * 2.5  (includes safety stock)
    def compute_rop(self):
        d = float(self.demand_per_day or 0.0)
        L = float(self.lead_days or 0.0)
        return round(d * L * 2.5, 2)
    def suggested_order_qty(self):
        current = float(self.current_stock or 0.0)
        max_level = float(self.max_stock or 0.0)
        if max_level <= 0:
            return 0.0
        qty = max_level - current
        return round(qty if qty > 0 else 0.0, 2)
    def suggested_order_qty_display(self):
        current = float(self.current_stock or 0.0)
        max_level = float(self.max_stock or 0.0)
        if max_level <= 0:
            return 0.0
        if self.is_kanban():
            return round(max_level / 2.0, 2)
        qty = max_level - current
        return round(qty if qty > 0 else 0.0, 2)

# Consolidated PO per supplier - generated at 3 PM daily
class PurchaseOrder(db.Model):
    __tablename__ = "purchase_order"

    id = db.Column(db.BigInteger, primary_key=True)
    po_number = db.Column(db.String(20), unique=True, nullable=False)
    supplier_id = db.Column(db.BigInteger, db.ForeignKey("supplier.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    supplier = db.relationship("Supplier", backref=db.backref("purchase_orders", lazy=True))
    items = db.relationship("PurchaseOrderItem", backref="po", lazy=True)


# Line items within a consolidated PO
class PurchaseOrderItem(db.Model):
    __tablename__ = "purchase_order_item"

    id = db.Column(db.BigInteger, primary_key=True)
    po_id = db.Column(db.BigInteger, db.ForeignKey("purchase_order.id"), nullable=False)
    product_id = db.Column(db.BigInteger, db.ForeignKey("product.id"), nullable=False)
    current_stock = db.Column(db.Float, nullable=False)
    trigger_level = db.Column(db.Float, nullable=False)
    suggested_qty = db.Column(db.Float, nullable=False)

    product = db.relationship("Product", backref=db.backref("po_items", lazy=True))


# Tracks products that crossed below their trigger level and are awaiting the daily 3 PM PO run
class PendingReorder(db.Model):
    __tablename__ = "pending_reorder"

    id = db.Column(db.BigInteger, primary_key=True)
    product_id = db.Column(db.BigInteger, db.ForeignKey("product.id"), nullable=False)
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed = db.Column(db.Boolean, default=False, nullable=False)

    product = db.relationship("Product", backref=db.backref("pending_reorders", lazy=True))


# imperative for idle db
class StockMovement(db.Model):
    __tablename__ = "stock_movement"
    id = db.Column(db.BigInteger, primary_key=True)
    product_id = db.Column(db.BigInteger, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    movement_type = db.Column(db.String(16), nullable=False)
    qty_change = db.Column(db.Float, nullable=False)
    location = db.Column(db.String(160))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    product = db.relationship(
        "Product",
        backref=db.backref("movements", lazy="dynamic", cascade="all, delete-orphan")
    )