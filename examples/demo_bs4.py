import os
import requests
from bs4 import BeautifulSoup
from anchorheal import heal
from anchorheal.store import AnchorStore

DB_PATH = "demo_bs4.db"

# Clear old DB
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

# Setup @heal on BS4 scraper
@heal(driver_type="bs4", db_path=DB_PATH)
def scrape_product(soup):
    # original baseline selector is '.price-tag'
    price_el = soup.select_one(".price-tag")
    if price_el:
        return price_el.text
    return None

def run():
    print("=" * 80)
    print("                 ANCHORHEAL BEAUTIFULSOUP4 DEMO (ZERO-DEP)")
    print("=" * 80)
    
    url = "http://localhost:5000/product"
    
    # 1. Scrape v1 (Baseline)
    print("Step 1: Scraping Baseline page (v1)...")
    try:
        r1 = requests.get(f"{url}?v=1")
    except requests.exceptions.ConnectionError:
        print("[Error] Flask test website is not running at http://localhost:5000.")
        print("Please start testsite/app.py in a separate shell first.")
        return
        
    soup1 = BeautifulSoup(r1.text, "lxml")
    price1 = scrape_product(soup1)
    print(f"  Scraped Price: {price1.strip() if price1 else None}")
    
    # Check anchor created
    store = AnchorStore(db_path=DB_PATH)
    with store._get_conn() as conn:
        row = conn.execute("SELECT caller_id, confidence, tag FROM anchors").fetchone()
        print(f"  Saved Anchor: ID={row['caller_id']}, Confidence={row['confidence']}, Tag={row['tag']}")
        
    # 2. Scrape v2 (Class Rename: .price-tag -> .product-amount)
    print("\nStep 2: Scraping Class Rename page (v2)...")
    r2 = requests.get(f"{url}?v=2")
    soup2 = BeautifulSoup(r2.text, "lxml")
    
    # Scraping v2 will trigger BS4 healing automatically!
    price2 = scrape_product(soup2)
    print(f"  Scraped Price (Healed): {price2.strip() if price2 else None}")
    
    # Read heal logs
    events = store.get_heal_events(row["caller_id"])
    if events:
        print(f"  Heal Event Logged: {events[0].old_selector} -> {events[0].new_selector}")
        print(f"  Winning Signal: {events[0].primary_winning_signal.upper()}")
        print(f"  Confidence updated: {events[0].confidence_before:.2f} -> {events[0].confidence_after:.2f}")
    
    print("=" * 80)
    
    # Clean up
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

if __name__ == "__main__":
    run()
