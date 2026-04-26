from app.bot import whatsapp_webhook
from fastapi import FastAPI, Depends, Request
from sqlalchemy.orm import Session
from app.database import engine, Base, SessionLocal
import app.models
from app.crud import add_stock, remove_stock, get_all_products, get_low_stock
from pydantic import BaseModel

app = FastAPI()

Base.metadata.create_all(bind=engine)

# --- DB Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Schemas ---
class StockRequest(BaseModel):
    name: str
    qty: int

# --- Routes ---
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
        {
            "id": p.id,
            "name": p.name,
            "quantity": p.quantity,
            "reorder_level": p.reorder_level
        }
        for p in items
    ]

@app.get("/lowstock")
def low_stock(db: Session = Depends(get_db)):
    items = get_low_stock(db)
    if not items:
        return {"message": "All stock levels are healthy"}
    return [
        {
            "name": p.name,
            "quantity": p.quantity,
            "reorder_level": p.reorder_level
        }
        for p in items
    ]
@app.post("/webhook")
async def webhook(request: Request):
    return await whatsapp_webhook(request)