import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from anchorheal import heal
from anchorheal.store import AnchorStore

DB_PATH = "demo_selenium.db"

# Clear old DB
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

# Setup @heal on Selenium scraper
@heal(driver_type="selenium", db_path=DB_PATH)
def scrape_product(driver):
    price_el = driver.find_element("css selector", ".price-tag")
    return price_el.text

def run():
    print("=" * 80)
    print("                 ANCHORHEAL SELENIUM WEBDRIVER DEMO")
    print("=" * 80)
    
    url = "http://localhost:5000/product"
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        print(f"[Error] Failed to initialize Chrome WebDriver: {e}")
        return

    try:
        # 1. Scrape v1 (Baseline)
        print("Step 1: Scraping Baseline page (v1)...")
        driver.get(f"{url}?v=1")
        price1 = scrape_product(driver)
        print(f"  Scraped Price: {price1}")
        
        # Check database
        store = AnchorStore(db_path=DB_PATH)
        with store._get_conn() as conn:
            row = conn.execute("SELECT caller_id, confidence, tag, bbox, rel_position FROM anchors").fetchone()
            print(f"  Saved Anchor: ID={row['caller_id']}, Confidence={row['confidence']}, Tag={row['tag']}")
            print(f"  Coordinates: BBox={row['bbox']}, RelPosition={row['rel_position']}")
            
        # 2. Scrape v2 (Class Rename)
        print("\nStep 2: Scraping Class Rename page (v2)...")
        driver.get(f"{url}?v=2")
        
        # Will trigger healing using DOM + Visual + Context + Text
        price2 = scrape_product(driver)
        print(f"  Scraped Price (Healed): {price2}")
        
        events = store.get_heal_events(row["caller_id"])
        if events:
            print(f"  Heal Event Logged: {events[0].old_selector} -> {events[0].new_selector}")
            print(f"  Winning Signal: {events[0].primary_winning_signal.upper()}")
            print(f"  Confidence updated: {events[0].confidence_before:.2f} -> {events[0].confidence_after:.2f}")
            
    finally:
        driver.quit()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            
    print("=" * 80)

if __name__ == "__main__":
    run()
