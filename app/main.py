import csv
import io
import os
from fastapi import FastAPI, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import engine, Base, SessionLocal
import app.models
from app.crud import add_stock, remove_stock, get_all_products, get_low_stock
from app.bot import whatsapp_webhook
from pydantic import BaseModel

app = FastAPI()
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class StockRequest(BaseModel):
    name: str
    qty: int

@app.get("/")
def read_root():
    return {"message": "Inventory bot backend is live"}

@app.post("/add")
def add(req: StockRequest, db: Session = Depends(get_db)):
    product = add_stock(db, req.name, req.qty)
    return {"name": product.name, "quantity": product.quantity}

@app.post("/remove")
def remove(req: StockRequest, db: Session = Depends(get_db)):
    product, error = remove_stock(db, req.name, req.qty)
    if error:
        return {"error": error}
    return {"name": product.name, "quantity": product.quantity}

@app.get("/products")
def products(db: Session = Depends(get_db)):
    items = get_all_products(db)
    return [
        {"id": p.id, "name": p.name, "quantity": p.quantity, "reorder_level": p.reorder_level, "category": p.category}
        for p in items
    ]

@app.get("/lowstock")
def low_stock(db: Session = Depends(get_db)):
    items = get_low_stock(db)
    if not items:
        return {"message": "All stock levels are healthy"}
    return [
        {"name": p.name, "quantity": p.quantity, "reorder_level": p.reorder_level, "category": p.category}
        for p in items
    ]

@app.get("/export")
def export_csv(db: Session = Depends(get_db)):
    items = get_all_products(db)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Category", "Quantity", "Reorder Level"])
    for p in items:
        writer.writerow([p.id, p.name, p.category or "Uncategorized", p.quantity, p.reorder_level])
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory.csv"}
    )

@app.post("/webhook")
async def webhook(request: Request):
    return await whatsapp_webhook(request)

@app.get("/migrate")
def migrate(db: Session = Depends(get_db)):
    try:
        db.execute(text("ALTER TABLE products ADD COLUMN category VARCHAR"))
        db.commit()
        return {"message": "Migration successful - category column added"}
    except Exception as e:
        return {"message": f"Already migrated or error: {str(e)}"}
