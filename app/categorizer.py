import json
import urllib.request
import os

API_KEY = os.getenv("ANTHROPIC_API_KEY")

KNOWN_CATEGORIES = {
    "rice": "Grains", "unga": "Grains", "maize": "Grains", "beans": "Grains",
    "wheat": "Grains", "sorghum": "Grains", "millet": "Grains",
    "milk": "Dairy", "eggs": "Dairy", "blueband": "Dairy", "butter": "Dairy",
    "cheese": "Dairy", "yogurt": "Dairy",
    "soap": "Cleaning", "omo": "Cleaning", "sunlight": "Cleaning",
    "tissue": "Cleaning", "bleach": "Cleaning", "detergent": "Cleaning",
    "coke": "Beverages", "fanta": "Beverages", "sprite": "Beverages",
    "juice": "Beverages", "water": "Beverages", "tea": "Beverages",
    "coffee": "Beverages", "soda": "Beverages",
    "biscuits": "Snacks", "crisps": "Snacks", "chocolate": "Snacks",
    "sweets": "Snacks", "candy": "Snacks", "nuts": "Snacks",
    "bread": "Bakery", "chapati": "Bakery", "mandazi": "Bakery",
    "cake": "Bakery", "rolls": "Bakery",
    "sugar": "Condiments", "salt": "Condiments", "oil": "Condiments",
    "cookingoil": "Condiments", "vinegar": "Condiments", "ketchup": "Condiments",
    "toothbrush": "Personal Care", "toothpaste": "Personal Care",
    "lotion": "Personal Care", "pads": "Personal Care", "shampoo": "Personal Care",
    "kerosene": "Household", "charcoal": "Household", "matches": "Household",
    "airtime": "Household", "candles": "Household",
}

def guess_category(product_name: str) -> str:
    name = product_name.strip().lower()

    # check hardcoded lookup first
    if name in KNOWN_CATEGORIES:
        return KNOWN_CATEGORIES[name]

    # fallback to Claude
    if not API_KEY:
        return "Uncategorized"

    prompt = f"""What category does this product belong to?
Product: "{product_name}"

Choose ONE from: Grains, Dairy, Cleaning, Beverages, Snacks, Produce, Meat, Bakery, Frozen, Household, Personal Care, Condiments, Uncategorized

Reply with ONLY the category name, nothing else."""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 10,
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
            return data["content"][0]["text"].strip().title()
    except Exception:
        return "Uncategorized"
