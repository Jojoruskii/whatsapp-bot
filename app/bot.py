from fastapi import Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from app.crud import add_stock, remove_stock, get_all_products, get_low_stock
from app.database import SessionLocal
import re
import json
import urllib.request


# --- Claude API parser ---
def parse_with_claude(msg: str) -> dict | None:
    prompt = f"""You are an inventory bot parser. Extract the intent from this message.

Message: "{msg}"

Reply ONLY with a JSON object in this exact format, nothing else:
{{"action": "add" or "remove" or "stock" or "lowstock", "product": "product name or null", "qty": number or null}}

Rules:
- action is "add" if user wants to add/restock/received items
- action is "remove" if user wants to remove/sold/used/dispatched items
- action is "stock" if user wants to see all inventory
- action is "lowstock" if user wants to see low stock items
- product and qty are null for stock and lowstock actions
- qty must be a positive integer or null
- If you cannot determine the intent, return {{"action": null, "product": null, "qty": null}}"""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            text = data["content"][0]["text"].strip()
            return json.loads(text)
    except Exception:
        return None


# --- Keyword parser ---
def parse_keyword(msg: str) -> dict | None:
    msg = msg.strip().lower()

    if msg == "stock":
        return {"action": "stock", "product": None, "qty": None}

    if msg == "lowstock":
        return {"action": "lowstock", "product": None, "qty": None}

    # match: add/remove <product> <number>
    match = re.match(r"^(add|remove)\s+([a-zA-Z ]+?)\s+(\d+)$", msg)
    if match:
        return {
            "action": match.group(1),
            "product": match.group(2).strip(),
            "qty": int(match.group(3))
        }

    # match: add/remove <number> <product>
    match = re.match(r"^(add|remove)\s+(\d+)\s+([a-zA-Z ]+)$", msg)
    if match:
        return {
            "action": match.group(1),
            "product": match.group(3).strip(),
            "qty": int(match.group(2))
        }

    return None


# --- Execute parsed command ---
def execute_command(parsed: dict) -> str:
    action = parsed.get("action")
    product = parsed.get("product")
    qty = parsed.get("qty")
    db = SessionLocal()

    try:
        if action == "stock":
            products = get_all_products(db)
            if not products:
                return "📦 No products in inventory yet."
            lines = ["📦 *Current Inventory:*"]
            for p in products:
                status = "⚠️" if p.quantity <= p.reorder_level else "✅"
                lines.append(f"{status} {p.name}: {p.quantity} units")
            return "\n".join(lines)

        elif action == "lowstock":
            items = get_low_stock(db)
            if not items:
                return "✅ All stock levels are healthy."
            lines = ["⚠️ *Low Stock Alert:*"]
            for p in items:
                lines.append(f"- {p.name}: {p.quantity} units (reorder level: {p.reorder_level})")
            return "\n".join(lines)

        elif action == "add":
            if not product or not qty:
                return "❌ I couldn't figure out what to add. Try: add rice 10"
            p = add_stock(db, product, qty)
            return f"✅ Added {qty} units of *{p.name}*.\nNew total: {p.quantity} units."

        elif action == "remove":
            if not product or not qty:
                return "❌ I couldn't figure out what to remove. Try: remove rice 5"
            p, error = remove_stock(db, product, qty)
            if error:
                return f"❌ {error}"
            reply = f"✅ Removed {qty} units of *{p.name}*.\nRemaining: {p.quantity} units."
            if p.quantity <= p.reorder_level:
                reply += (
                    f"\n\n🚨 *Low Stock Warning!*\n"
                    f"*{p.name}* is down to {p.quantity} units.\n"
                    f"Reorder level: {p.reorder_level} units. Please restock soon!"
                )
            return reply

        else:
            return None

    finally:
        db.close()


# --- Main handler ---
def handle_message(incoming_msg: str) -> str:
    # Step 1: try keyword parser
    parsed = parse_keyword(incoming_msg)

    # Step 2: fallback to Claude
    if not parsed:
        parsed = parse_with_claude(incoming_msg)

    # Step 3: execute or show help
    if parsed and parsed.get("action"):
        result = execute_command(parsed)
        if result:
            return result

    return (
        "🤖 *Inventory Bot Commands:*\n"
        "• `stock` — view all products\n"
        "• `lowstock` — check low stock items\n"
        "• `add <product> <qty>` — add stock\n"
        "• `remove <product> <qty>` — remove stock\n\n"
        "Or just type naturally — e.g. _'we sold 5 bags of rice'_"
    )


async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg = form.get("Body", "")
    reply = handle_message(incoming_msg)

    resp = MessagingResponse()
    resp.message(reply)
    return PlainTextResponse(str(resp), media_type="application/xml")
