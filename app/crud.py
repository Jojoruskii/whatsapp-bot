from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Product

def get_product(db: Session, name: str):
    return db.query(Product).filter(
        func.lower(Product.name) == name.strip().lower()
    ).first()

def add_stock(db: Session, name: str, qty: int, category: str = None):
    product = get_product(db, name)
    if product:
        product.quantity += qty
        if category:
            product.category = category
    else:
        product = Product(name=name.strip().lower(), quantity=qty, category=category or "Uncategorized")
        db.add(product)
    db.commit()
    db.refresh(product)
    return product

def remove_stock(db: Session, name: str, qty: int):
    product = get_product(db, name)
    if not product:
        return None, "Product not found"
    if product.quantity < qty:
        return None, f"Insufficient stock. Only {product.quantity} units available"
    product.quantity -= qty
    db.commit()
    db.refresh(product)
    return product, None

def delete_product(db: Session, name: str):
    product = get_product(db, name)
    if not product:
        return False, "Product not found"
    db.delete(product)
    db.commit()
    return True, None

def reset_inventory(db: Session):
    count = db.query(Product).count()
    db.query(Product).delete()
    db.commit()
    return count

def clear_stock(db: Session):
    products = db.query(Product).all()
    for p in products:
        p.quantity = 0
    db.commit()
    return len(products)

def set_category(db: Session, name: str, category: str):
    product = get_product(db, name)
    if not product:
        return None, "Product not found"
    product.category = category.strip().title()
    db.commit()
    db.refresh(product)
    return product, None

def get_all_products(db: Session):
    return db.query(Product).order_by(Product.category, func.lower(Product.name)).all()

def get_low_stock(db: Session):
    return db.query(Product).filter(
        Product.quantity <= Product.reorder_level
    ).order_by(Product.category, func.lower(Product.name)).all()

def set_reorder_level(db: Session, name: str, level: int):
    product = get_product(db, name)
    if not product:
        return None, "Product not found"
    product.reorder_level = level
    db.commit()
    db.refresh(product)
    return product, None
