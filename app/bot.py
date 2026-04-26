from fastapi import Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from app.crud import add_stock, remove_stock, get_all_products, get_low_stock
from app.database import SessionLocal
import os

# --- Load credentials ---
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

def send_alert(to: str, message: str):
    """Proactively send a WhatsApp message via Twilio."""
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    client.messages.create(
        from_=TWILIO_NUMBER,
        to=f"whatsapp:{to}",
        body=message
    )

def handle_message(incoming_msg: str, sender: str) -> str:
    msg = incoming_msg.strip().lower()
    db = SessionLocal()

    try:
        if msg == "stock":
            products = get_all_products(db)
            if not products:
                return "📦 No products in inventory yet."
            lines = ["📦 *Current Inventory:*"]
            for p in products:
                status = "⚠️" if p.quantity <= p.reorder_level else "✅"
                lines.append(f"{status} {p.name}: {p.quantity} units")
            return "\n".join(lines)

        elif msg == "lowstock":
            items = get_low_stock(db)
            if not items:
                return "✅ All stock levels are healthy."
            lines = ["⚠️ *Low Stock Alert:*"]
            for p in items:
                lines.append(f"- {p.name}: {p.quantity} units (reorder level: {p.reorder_level})")
            return "\n".join(lines)

        elif msg.startswith("add "):
            parts = msg.split()
            if len(parts) != 3 or not parts[2].isdigit():
                return "❌ Format: add <product> <quantity>\nExample: add rice 10"
            name, qty = parts[1], int(parts[2])
            product = add_stock(db, name, qty)
            return f"✅ Added {qty} units of *{product.name}*.\nNew total: {product.quantity} units."

        elif msg.startswith("remove "):
            parts = msg.split()
            if len(parts) != 3 or not parts[2].isdigit():
                return "❌ Format: remove <product> <quantity>\nExample: remove rice 3"
            name, qty = parts[1], int(parts[2])
            product, error = remove_stock(db, name, qty)
            if error:
                return f"❌ {error}"

            reply = f"✅ Removed {qty} units of *{product.name}*.\nRemaining: {product.quantity} units."

            # --- Proactive low stock alert ---
            if product.quantity <= product.reorder_level:
                alert = (
                    f"🚨 *Low Stock Alert!*\n"
                    f"*{product.name}* is down to {product.quantity} units.\n"
                    f"Reorder level is {product.reorder_level} units. Please restock soon."
                )
                send_alert(sender, alert)

            return reply

        else:
            return (
                "🤖 *Inventory Bot Commands:*\n"
                "• `stock` — view all products\n"
                "• `lowstock` — check low stock items\n"
                "• `add <product> <qty>` — add stock\n"
                "• `remove <product> <qty>` — remove stock"
            )

    finally:
        db.close()


async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg = form.get("Body", "")
    sender = form.get("From", "").replace("whatsapp:", "")  # extract phone number
    reply = handle_message(incoming_msg, sender)

    resp = MessagingResponse()
    resp.message(reply)
    return PlainTextResponse(str(resp), media_type="application/xml")