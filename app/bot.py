import os
import re
import json
import urllib.request
from fastapi import Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from app.crud import add_stock, remove_stock, get_all_products, get_low_stock
from app.database import SessionLocal

API_KEY = os.getenv("ANTHROPIC_API_KEY")
BASE_URL = "https://web-production-e8e96.up.railway.app"


def parse_with_claude(msg: str):
    prompt = f"""You are an inventory bot parser. Extract the intent from this message.

Message: "{msg}"

Reply ONLY with a JSON object in this exact format, nothing else:
{{"action": "add" or "remove" or "stock" or "lowstock" or "export" or "multi", "product": "product name or null", "qty": number or null, "items": [{{"product": "name", "qty": number}}] or null}}

Rules:
- action is "add" if user wants to add/restock/received a single item
- action is "remove" if user wants to remove/sold/used/dispatched a single item
- action is "multi" if user mentions multiple products in one message - put them all in "items" array
- action is "stock" if user wants to see all inventory
- action is "lowstock" if user wants to see low stock items
- action is "export" if user wants to download/export/get the stock sheet or spreadsheet
- for "multi" action, also include whether it is "add" or "remove" as a separate key called "bulk_action"
- product and qty are null for multi, stock, lowstock and export actions
- qty must be a positive integer or null
- If you cannot determine the intent, return {{"action": null, "product": null, "qty": null, "items": null}}"""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            text = data["content"][0]["text"].strip()
            return json.loads(text)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}


def parse_keyword(msg: str) -> dict | None:
    msg = msg.strip().lower()

    if msg == "stock":
        return {"action": "stock", "product": None, "qty": None}

    if msg == "lowstock":
        return {"action": "lowstock", "product": None, "qty": None}

    if msg in ["export", "download", "send stock", "stock sheet", "spreadsheet"]:
        return {"action": "export", "product": None, "qty": None}

    multi_match = re.match(r"^(add|remove)\s+(.+)", msg)
    if multi_match and "," in msg:
        action = multi_match.group(1)
        items_raw = multi_match.group(2).split(",")
        items = []
        for item in items_raw:
            item = item.strip()
            m = re.match(r"^([a-zA-Z ]+?)\s+(\d+)$", item) or re.match(r"^(\d+)\s+([a-zA-Z ]+)$", item)
            if m:
                g = m.groups()
                if g[0].isdigit():
                    items.append({"product": g[1].strip(), "qty": int(g[0])})
                else:
                    items.append({"product": g[0].strip(), "qty": int(g[1])})
        if items:
            return {"action": "multi", "bulk_action": action, "items": items, "product": None, "qty": None}

    match = re.match(r"^(add|remove)\s+([a-zA-Z ]+?)\s+(\d+)$", msg)
    if match:
        return {
            "action": match.group(1),
            "product": match.group(2).strip(),
            "qty": int(match.group(3))
        }

    match = re.match(r"^(add|remove)\s+(\d+)\s+([a-zA-Z ]+)$", msg)
    if match:
        return {
            "action": match.group(1),
            "product": match.group(3).strip(),
            "qty": int(match.group(2))
        }

    return None


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
            low = []
            for p in products:
                status = "⚠️" if p.quantity <= p.reorder_level else "✅"
                lines.append(f"{status} {p.name}: {p.quantity} units")
                if p.quantity <= p.reorder_level:
                    low.append(p)
            if low:
                lines.append("\n🚨 *Low Stock Alert:*")
                for p in low:
                    lines.append(f"• *{p.name}* needs restocking — only {p.quantity} units left!")
            return "\n".join(lines)

        elif action == "lowstock":
            items = get_low_stock(db)
            if not items:
                return "✅ All stock levels are healthy."
            lines = ["⚠️ *Low Stock Alert:*"]
            for p in items:
                lines.append(f"- {p.name}: {p.quantity} units (reorder level: {p.reorder_level})")
            return "\n".join(lines)

        elif action == "export":
            return (
                "📊 *Download Stock Sheet*\n"
                "Click the link below to download your inventory as a CSV file:\n\n"
                f"{BASE_URL}/export\n\n"
                "_Opens directly in Excel or Google Sheets_ ✅"
            )

        elif action == "multi":
            bulk_action = parsed.get("bulk_action", "add")
            items = parsed.get("items", [])
            if not items:
                return "❌ Couldn't parse the products. Try: add rice 10, maize 20, sugar 5"

            lines = [f"{'✅ Added' if bulk_action == 'add' else '✅ Removed'} multiple items:\n"]
            warnings = []

            for item in items:
                name = item.get("product")
                q = item.get("qty")
                if not name or not q:
                    continue
                if bulk_action == "add":
                    p = add_stock(db, name, q)
                    lines.append(f"• *{p.name}*: {q} units added → {p.quantity} total")
                else:
                    p, error = remove_stock(db, name, q)
                    if error:
                        lines.append(f"• *{name}*: ❌ {error}")
                        continue
                    lines.append(f"• *{p.name}*: {q} units removed → {p.quantity} remaining")
                    if p.quantity <= p.reorder_level:
                        warnings.append(f"🚨 *{p.name}* is low: {p.quantity} units left!")

            if warnings:
                lines.append("\n" + "\n".join(warnings))

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


def handle_message(incoming_msg: str) -> str:
    parsed = parse_keyword(incoming_msg)

    if not parsed:
        parsed = parse_with_claude(incoming_msg)

    if parsed and parsed.get("action"):
        result = execute_command(parsed)
        if result:
            return result

    return (
        "🤖 *Inventory Bot Commands:*\n"
        "• `stock` — view all products\n"
        "• `lowstock` — check low stock items\n"
        "• `add <product> <qty>` — add stock\n"
        "• `remove <product> <qty>` — remove stock\n"
        "• `add rice 10, maize 20, sugar 5` — add multiple\n"
        "• `export` — download stock sheet\n\n"
        "Or just type naturally — e.g. _'we sold 5 bags of rice'_"
    )


async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg = form.get("Body", "")
    reply = handle_message(incoming_msg)

    resp = MessagingResponse()
    resp.message(reply)
    return PlainTextResponse(str(resp), media_type="application/xml")
