import os
import sqlite3
from flask import Flask, request, render_template, g
import datetime

app = Flask(__name__)

# DB Path for dashboard
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "anchorheal.db"))

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/product")
def product():
    v = request.args.get("v", 1, type=int)
    drift = request.args.get("drift", None, type=int)
    
    # Defaults
    title_tag = "h1"
    title_class = "product-title"
    title_id = None
    title_text = "AnchorHeal Test Widget"
    
    price_tag = "span"
    price_class = "price-tag"
    price_id = None
    price_text = "$19.99"
    price_style = ""
    
    cart_tag = "button"
    cart_class = "btn"
    cart_id = "add-to-cart"
    cart_text = "Add to Cart"
    
    stock_tag = "span"
    stock_class = "stock-badge"
    stock_id = None
    stock_text = "In Stock (5)"
    
    desc_tag = "p"
    desc_class = "description"
    desc_id = None
    desc_text = "Product description goes here…"
    
    banner = None
    decoy = None
    
    # Apply continuous drift
    if drift is not None:
        # 1. Slide element down the page
        price_style = f"margin-top: {drift * 3}px; display: inline-block;"
        
        # 2. Mutate class name based on drift levels
        if drift < 25:
            price_class = "price-tag"
        elif drift < 60:
            price_class = "price-tag-v2"
        elif drift < 80:
            price_class = "amount"
        else:
            price_class = "cost"
    else:
        # Apply discrete scenarios
        if v == 2:
            # Class rename: .price-tag -> .product-amount
            price_class = "product-amount"
            
        elif v == 3:
            # Layout shift: banner injected pushes all content down
            banner = {
                "text": "🔥 SUMMER SALE: 50% OFF TODAY ONLY! 🔥",
                "style": "height: 120px; background: linear-gradient(135deg, #ff416c, #ff4b2b); color: white; display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: bold; margin-bottom: 20px; border-radius: 8px;"
            }
            
        elif v == 4:
            # Drastic re-tree
            title_tag = "div"
            title_class = "widget-name"
            
            price_tag = "span"
            price_class = "cost"
            
            cart_tag = "a"
            cart_class = "add-link"
            cart_id = "buy-now-link"
            cart_text = "Buy Now"
            
            stock_tag = "div"
            stock_class = "availability"
            
            desc_tag = "section"
            desc_class = "summary"
            
        elif v == 5:
            # Decoy/Ad hijack
            # Inject decoy that steals '.price-tag'
            decoy = {
                "tag": "span",
                "class": "price-tag",
                "text": "Buy Bitcoin!",
                "style": "position: absolute; top: 10px; right: 10px; background: gold; padding: 10px; border-radius: 4px; font-weight: bold; color: black;"
            }
            # Real price moves & changes class
            price_class = "real-price"
            price_style = "margin-top: 100px; display: inline-block;"
            
    return render_template(
        "product.html",
        v=v,
        drift=drift,
        banner=banner,
        decoy=decoy,
        title_tag=title_tag,
        title_class=title_class,
        title_id=title_id,
        title_text=title_text,
        price_tag=price_tag,
        price_class=price_class,
        price_id=price_id,
        price_text=price_text,
        price_style=price_style,
        cart_tag=cart_tag,
        cart_class=cart_class,
        cart_id=cart_id,
        cart_text=cart_text,
        stock_tag=stock_tag,
        stock_class=stock_class,
        stock_id=stock_id,
        stock_text=stock_text,
        desc_tag=desc_tag,
        desc_class=desc_class,
        desc_id=desc_id,
        desc_text=desc_text
    )

@app.route("/dashboard")
def dashboard():
    # If DB doesn't exist yet, pass empty list
    if not os.path.exists(DB_PATH):
        return render_template("dashboard.html", anchors=[])
        
    db = get_db()
    # Read anchors and calculate drift slope
    anchors_rows = db.execute("SELECT * FROM anchors").fetchall()
    anchors = []
    
    for row in anchors_rows:
        cid = row["caller_id"]
        # Query history
        hist = db.execute(
            "SELECT timestamp, confidence FROM confidence_history WHERE caller_id = ? ORDER BY timestamp ASC",
            (cid,)
        ).fetchall()
        
        status = "stable"
        slope = 0.0
        
        if len(hist) >= 2:
            t1 = datetime.datetime.fromisoformat(hist[0]["timestamp"])
            tn = datetime.datetime.fromisoformat(hist[-1]["timestamp"])
            c1 = hist[0]["confidence"]
            cn = hist[-1]["confidence"]
            time_diff = (tn - t1).total_seconds() / 86400.0
            if time_diff > 0.01:
                slope = (cn - c1) / time_diff
            else:
                slope = (cn - c1) / float(len(hist) - 1)
                
            if cn < 0.4 and slope < 0:
                status = "critical"
            elif slope < -0.05:
                status = "decaying"
            elif slope > 0.05:
                status = "improving"
                
        anchors.append({
            "caller_id": cid,
            "primary_selector": row["primary_selector"],
            "confidence": row["confidence"],
            "status": status,
            "slope": slope,
            "history_count": len(hist)
        })
        
    return render_template("dashboard.html", anchors=anchors)

if __name__ == "__main__":
    app.run(port=5000, debug=True)
