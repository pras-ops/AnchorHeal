import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from anchorheal import heal
from anchorheal.store import AnchorStore
from anchorheal.observability import ObservabilityManager

DB_PATH = "demo_drift.db"

# Clear old DB
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

# Scraper uses '.price-section span' which matches the price element under all drift states,
# but the element's features (classes/text/visual coordinates) erode progressively.
@heal(driver_type="selenium", db_path=DB_PATH)
def scrape_price(driver):
    # Query price span inside the price section
    el = driver.find_element("css selector", ".price-section span")
    if el:
        return el.text
    return None

def run():
    print("=" * 80)
    print("            ANCHORHEAL CONTINUOUS DRIFT & EARLY-WARNING DEMO")
    print("=" * 80)
    
    url = "http://localhost:5000/product"
    store = AnchorStore(db_path=DB_PATH)
    obs = ObservabilityManager(db_path=DB_PATH)
    
    # We step through increasing drift levels
    drift_levels = [0, 20, 45, 70, 90]
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    
    caller_id = None
    
    try:
        for drift in drift_levels:
            print(f"\n---> Running scrape at Drift = {drift}%")
            try:
                driver.get(f"{url}?drift={drift}")
            except Exception:
                print("[Error] Flask test website is not running at http://localhost:5000.")
                print("Please start testsite/app.py in a separate shell first.")
                return
                
            val = scrape_price(driver)
            
            # Resolve caller_id on first pass
            if not caller_id:
                with store._get_conn() as conn:
                    row = conn.execute("SELECT caller_id FROM anchors").fetchone()
                    if row:
                        caller_id = row["caller_id"]
                        
            # Fetch current confidence and drift status
            analysis = obs.get_selector_drift(caller_id)
            current_conf = analysis["current_confidence"]
            status = analysis["status"]
            slope = analysis["slope"]
            
            print(f"  Scraped Value: {val}")
            print(f"  Current Confidence: {current_conf:.4f} (drift slope: {slope:+.4f}/run)")
            print(f"  Status: {status.upper()}")
            
            # Check for predictions
            predictions = obs.predict_failures()
            if predictions:
                print(f"  [observability] ⚠ PREDICTED BREAK WARNING: Selector is in critical risk!")
                print(f"  Message: {predictions[0]['message']}")
    finally:
        driver.quit()
        
    print("\n" + "=" * 80)
    
    # Clean up
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

if __name__ == "__main__":
    run()
