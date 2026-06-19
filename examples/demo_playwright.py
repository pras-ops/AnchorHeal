import os
from playwright.sync_api import sync_playwright
from anchorheal import heal
from anchorheal.store import AnchorStore

DB_PATH = "demo_playwright.db"

# Clear old DB
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

# Setup @heal on Playwright scraper
@heal(driver_type="playwright", db_path=DB_PATH)
def scrape_product(page):
    price_locator = page.locator(".price-tag")
    # action triggers evaluation and healing if necessary
    return price_locator.inner_text()

def run():
    print("=" * 80)
    print("                 ANCHORHEAL PLAYWRIGHT SYNC DEMO")
    print("=" * 80)
    
    url = "http://localhost:5000/product"
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # 1. Scrape v1 (Baseline)
            print("Step 1: Scraping Baseline page (v1)...")
            page.goto(f"{url}?v=1")
            price1 = scrape_product(page)
            print(f"  Scraped Price: {price1}")
            
            # Check database
            store = AnchorStore(db_path=DB_PATH)
            with store._get_conn() as conn:
                row = conn.execute("SELECT caller_id, confidence, tag, bbox, rel_position FROM anchors").fetchone()
                print(f"  Saved Anchor: ID={row['caller_id']}, Confidence={row['confidence']}, Tag={row['tag']}")
                print(f"  Coordinates: BBox={row['bbox']}, RelPosition={row['rel_position']}")
                
            # 2. Scrape v2 (Class Rename)
            print("\nStep 2: Scraping Class Rename page (v2)...")
            page.goto(f"{url}?v=2")
            
            # Will trigger locator healing
            price2 = scrape_product(page)
            print(f"  Scraped Price (Healed): {price2}")
            
            events = store.get_heal_events(row["caller_id"])
            if events:
                print(f"  Heal Event Logged: {events[0].old_selector} -> {events[0].new_selector}")
                print(f"  Winning Signal: {events[0].primary_winning_signal.upper()}")
                print(f"  Confidence updated: {events[0].confidence_before:.2f} -> {events[0].confidence_after:.2f}")
                
            browser.close()
        except Exception as e:
            print(f"[Error] Playwright execution failed: {e}")
            
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        
    print("=" * 80)

if __name__ == "__main__":
    run()
