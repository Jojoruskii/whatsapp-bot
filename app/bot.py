import os
import re
import json
import urllib.request
from datetime import datetime
from fastapi import Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from app.crud import add_stock, remove_stock, get_all_products, get_low_stock, set_reorder_level, delete_product, reset_inventory, clear_stock, set_category
from app.database import SessionLocal
from app.categorizer import guess_category

API_KEY = os.getenv("ANTHROPIC_API_KEY")
BASE_URL = "https://web-production-e8e96.up.railway.app"

CATEGORY_EMOJIS = {
    "grains": "🌾", "dairy": "🥛", "cleaning": "🧴", "beverages": "🥤",
    "snacks": "🍿", "produce": "🥬", "meat": "🥩", "bakery": "🍞",
    "frozen": "🧊", "household": "🏠", "personal care": "🪥",
    "condiments": "🧂", "uncategorized": "📦",
}

def get_category_emoji(category: str) -> str:
    return CATEGORY_EMOJIS.get(category.lower(), "📦")

def build_progress_bar(current: int, reorder_level: int) -> tuple:
    max_qty = reorder_level * 4 if reorder_level > 0 else max(current, 1)
    pct = min(100, int((current / max_qty) * 100))
    filled = round(pct / 10)
    bar = "▓" * filled + "░" * (10 - filled)
    if pct > 50:
        indicator, status = "🟢", "✅"
    elif pct > 20:
        indicator, status = "🟡", "⚠️"
    else:
        indicator, status = "🔴", "🚨"
    return indicator, bar, pct, status

def parse_with_claude(msg: str):
    prompt = f"""You are an inventory bot parser. Extract the intent from this message.

Message: "{msg}"

Reply ONLY with a JSON object in this exact format, nothing else:
{{"action": "add" or "remove" or "stock" or "lowstock" or "export" or "multi" or "setlevel" or "delete" or "reset" or "clearstock" or "setcategory" or "menu", "product": "product name or null", "qty": number or null, "level": number or null, "category": "category name or null", "items": [{{"product": "name", "qty": number}}] or null}}

Rules:
- action is "add" if user wants to add/restock/received a single item
- action is "remove" if user wants to remove/sold/used/dispatched a single item
- action is "multi" if user mentions multiple products in one message
- action is "stock" if user wants to see all inventory
- action is "lowstock" if user wants to see low stock items
- action is "export" if user wants to download/export the stock sheet
- action is "setlevel" if user wants to set the reorder level for a product
- action is "delete" if user wants to delete a single product
- action is "reset" if user wants to wipe the entire inventory
- action is "clearstock" if user wants to zero all quantities
- action is "setcategory" if user wants to change the category of a product
- action is "menu" if user wants help or a list of features
- for "multi" action, include "bulk_action" as "add" or "remove"
- for "setlevel" action, put the threshold in "level"
- for "setcategory" action, put the category name in "category"
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

    if msg in ["stock", "inventory", "show stock"]:
        return {"action": "stock", "product": None, "qty": None}
    if msg == "lowstock":
        return {"action": "lowstock", "product": None, "qty": None}
    if msg in ["export", "download", "send stock", "stock sheet", "spreadsheet"]:
        return {"action": "export", "product": None, "qty": None}
    if msg in ["menu", "help", "commands", "features", "hi", "hello", "start"]:
        return {"action": "menu", "product": None, "qty": None}
    if msg in ["reset", "reset inventory", "wipe inventory", "delete all"]:
        return {"action": "reset", "product": None, "qty": None}
    if msg in ["clearstock", "clear stock", "zero stock", "reset stock"]:
        return {"action": "clearstock", "product": None, "qty": None}

    match = re.match(r"^delete\s+([a-zA-Z ]+)$", msg)
    if match:
        return {"action": "delete", "product": match.group(1).strip(), "qty": None}

    match = re.match(r"^setlevel\s+([a-zA-Z ]+?)\s+(\d+)$", msg)
    if match:
        return {"action": "setlevel", "product": match.group(1).strip(), "level": int(match.group(2)), "qty": None}

    match = re.match(r"^setcategory\s+([a-zA-Z ]+?)\s+(grains|dairy|cleaning|beverages|snacks|produce|meat|bakery|frozen|household|personal care|condiments|uncategorized)$", msg)
    if match:
        return {"action": "setcategory", "product": match.group(1).strip(), "category": match.group(2).strip().title(), "qty": None}

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
        return {"action": match.group(1), "product": match.group(2).strip(), "qty": int(match.group(3))}

    match = re.match(r"^(add|remove)\s+(\d+)\s+([a-zA-Z ]+)$", msg)
    if match:
        return {"action": match.group(1), "product": match.group(3).strip(), "qty": int(match.group(2))}

    return None


def get_menu() -> str:
    return (
        "👋 *Welcome to Inventory Bot!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📦 *Stock Management*\n"
        "• `stock` — view inventory summary\n"
        "• `stock grains` — view a category\n"
        "• `lowstock` — view low stock items\n\n"
        "➕ `add rice 10`\n"
        "➖ `remove rice 3`\n"
        "🗑️ `delete rice`\n"
        "⚙️ `setlevel rice 15`\n"
        "🏷️ `setcategory rice grains`\n"
        "📊 `export`\n\n"
        "🔴 *Danger Zone*\n"
        "• `clearstock` — zero all quantities\n"
        "• `reset` — wipe entire inventory\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 _Or just type naturally_"
    )


def execute_command(parsed: dict) -> str:
    action = parsed.get("action")
    product = parsed.get("product")
    qty = parsed.get("qty")
    db = SessionLocal()

    try:
        if action == "menu":
            return get_menu()

        elif action == "stock":
            products = get_all_products(db)
            if not products:
                return "📦 No products yet.\nType *menu* to see commands."

            categories = {}
            for p in products:
                cat = p.category or "Uncategorized"
                categories.setdefault(cat, []).append(p)

            critical, warning = [], []
            for p in products:
                indicator, _, _, _ = build_progress_bar(p.quantity, p.reorder_level)
                if indicator == "🔴":
                    critical.append(p.name.title())
                elif indicator == "🟡":
                    warning.append(p.name.title())

            date_str = datetime.now().strftime("%d %b %Y")
            lines = [
                f"📦 *INVENTORY — {date_str}*",
                "━━━━━━━━━━━━━━━━━━━━━━━"
            ]

            for cat, items in sorted(categories.items()):
                emoji = get_category_emoji(cat)
                count = len(items)
                cat_critical = sum(1 for p in items if p.quantity <= p.reorder_level)
                cat_warning = sum(1 for p in items if p.reorder_level < p.quantity <= p.reorder_level * 2)

                if cat_critical:
                    health = "🔴"
                elif cat_warning:
                    health = "⚠️"
                else:
                    health = "✅"

                # pad category name for alignment
                cat_label = cat[:10].ljust(10)
                item_label = f"{count} item{'s' if count != 1 else ''} "
                lines.append(f"{emoji} {cat_label} {item_label} {health}")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"{len(products)} products · 🔴 {len(critical)} · 🟡 {len(warning)}")

            if critical:
                lines.append(f"⚡ Restock: {', '.join(critical)}")
            elif warning:
                lines.append(f"⚡ Watch: {', '.join(warning)}")
            else:
                lines.append("⚡ All products well stocked")

            lines.append("📌 _stock <category> for details_")
            return "\n".join(lines)

        elif action == "lowstock":
            items = get_low_stock(db)
            if not items:
                return "✅ All stock levels are healthy."
            lines = ["⚠️ *Low Stock Alert:*\n"]
            for p in items:
                indicator, bar, pct, status = build_progress_bar(p.quantity, p.reorder_level)
                cat = p.category or "Uncategorized"
                emoji = get_category_emoji(cat)
                lines.append(f"🔴 *{p.name.title()}* {emoji}")
                lines.append(f"   {p.quantity} units  {bar} {pct}%")
                lines.append(f"   Reorder at: {p.reorder_level} units\n")
            return "\n".join(lines)

        elif action == "export":
            return (
                "📊 *Download Stock Sheet*\n\n"
                f"{BASE_URL}/export\n\n"
                "_Opens in Excel or Google Sheets_ ✅"
            )

        elif action == "delete":
            if not product:
                return "❌ Format: delete <product>"
            success, error = delete_product(db, product)
            if error:
                return f"❌ {error}"
            return f"🗑️ *{product.title()}* deleted from inventory."

        elif action == "reset":
            count = reset_inventory(db)
            return f"🗑️ *Inventory Reset*\nAll {count} products permanently deleted."

        elif action == "clearstock":
            count = clear_stock(db)
            return f"🔄 *Stock Cleared*\nAll {count} products zeroed out."

        elif action == "setlevel":
            level = parsed.get("level")
            if not product or level is None:
                return "❌ Format: setlevel <product> <level>"
            p, error = set_reorder_level(db, product, level)
            if error:
                return f"❌ {error}"
            return f"✅ *{p.name.title()}* reorder level set to *{p.reorder_level} units*."

        elif action == "setcategory":
            category = parsed.get("category")
            if not product or not category:
                return "❌ Format: setcategory <product> <category>"
            p, error = set_category(db, product, category)
            if error:
                return f"❌ {error}"
            emoji = get_category_emoji(p.category.lower())
            return f"✅ *{p.name.title()}* moved to {emoji} *{p.category}*."

        elif action == "add":
            if not product or not qty:
                return "❌ Try: add rice 10"
            category = guess_category(product)
            p = add_stock(db, product, qty, category)
            emoji = get_category_emoji(category.lower())
            return (
                f"✅ Added {qty} units of *{p.name.title()}*.\n"
                f"New total: {p.quantity} units.\n"
                f"Category: {emoji} {p.category}"
            )

        elif action == "multi":
            bulk_action = parsed.get("bulk_action", "add")
            items = parsed.get("items", [])
            if not items:
                return "❌ Try: add rice 10, maize 20, sugar 5"
            lines = [f"{'✅ Added' if bulk_action == 'add' else '✅ Removed'}:\n"]
            warnings = []
            for item in items:
                name = item.get("product")
                q = item.get("qty")
                if not name or not q:
                    continue
                if bulk_action == "add":
                    category = guess_category(name)
                    p = add_stock(db, name, q, category)
                    emoji = get_category_emoji(category.lower())
                    lines.append(f"• *{p.name.title()}*: +{q} → {p.quantity} total {emoji}")
                else:
                    p, error = remove_stock(db, name, q)
                    if error:
                        lines.append(f"• *{name.title()}*: ❌ {error}")
                        continue
                    lines.append(f"• *{p.name.title()}*: -{q} → {p.quantity} left")
                    if p.quantity <= p.reorder_level:
                        warnings.append(f"🚨 {p.name.title()}: only {p.quantity} left!")
            if warnings:
                lines.append("\n" + "\n".join(warnings))
            return "\n".join(lines)

        elif action == "remove":
            if not product or not qty:
                return "❌ Try: remove rice 5"
            p, error = remove_stock(db, product, qty)
            if error:
                return f"❌ {error}"
            reply = f"✅ Removed {qty} units of *{p.name.title()}*.\nRemaining: {p.quantity} units."
            if p.quantity <= p.reorder_level:
                reply += (
                    f"\n\n🚨 *Low Stock Warning!*\n"
                    f"*{p.name.title()}* is down to {p.quantity} units.\n"
                    f"Reorder level: {p.reorder_level} units. Restock soon!"
                )
            return reply

        else:
            return None

    finally:
        db.close()


def handle_message(incoming_msg: str) -> str:
    msg = incoming_msg.strip().lower()

    cat_match = re.match(r"^stock\s+([a-zA-Z ]+)$", msg)
    if cat_match:
        category = cat_match.group(1).strip()
        db = SessionLocal()
        try:
            products = get_all_products(db)
            items = [p for p in products if (p.category or "uncategorized").lower() == category.lower()]
            if not items:
                return f"❌ No products found in *{category.title()}*."
            emoji = get_category_emoji(category.lower())
            lines = [f"{emoji} *{category.upper()}*", "━━━━━━━━━━━━━━━━━━━━━━━"]
            for p in items:
                indicator, bar, pct, status = build_progress_bar(p.quantity, p.reorder_level)
                lines.append(f"{indicator} *{p.name.title()}* {status}")
                lines.append(f"   {p.quantity} units  {bar} {pct}%")
            return "\n".join(lines)
        finally:
            db.close()

    parsed = parse_keyword(incoming_msg)
    if not parsed:
        parsed = parse_with_claude(incoming_msg)
    if parsed and parsed.get("action"):
        result = execute_command(parsed)
        if result:
            return result
    return get_menu()


async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg = form.get("Body", "")
    reply = handle_message(incoming_msg)
    resp = MessagingResponse()
    resp.message(reply)
    return PlainTextResponse(str(resp), media_type="application/xml")
