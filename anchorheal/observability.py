import datetime
from typing import Dict, Any, List, Optional
from .store import AnchorStore
from .models import Anchor, HealEvent

class ObservabilityManager:
    def __init__(self, db_path: str = "anchorheal.db"):
        self.store = AnchorStore(db_path=db_path)

    def get_selector_drift(self, caller_id: str) -> Dict[str, Any]:
        """
        Analyze confidence trend and compute the drift slope.
        Returns a dict with slope, current confidence, and trend category.
        """
        history = self.store.get_confidence_history(caller_id)
        if len(history) < 2:
            return {
                "caller_id": caller_id,
                "current_confidence": 1.0 if not history else history[-1][1],
                "slope": 0.0,
                "status": "stable",
                "message": "Insufficient history to calculate drift"
            }
            
        t1, c1 = history[0]
        tn, cn = history[-1]
        
        # Calculate slope over time (per day)
        time_diff = (tn - t1).total_seconds() / 86400.0 # diff in days
        if time_diff > 0.01:
            slope = (cn - c1) / time_diff
        else:
            # Fallback to index-based slope if t1 and tn are virtually identical
            slope = (cn - c1) / float(len(history) - 1)

        # Classify status
        if cn < 0.4 and slope < 0:
            status = "critical_risk"
            msg = "High risk of total failure. Confidence is critically low and declining."
        elif slope < -0.05:
            status = "decaying"
            msg = "Selector is actively decaying. Drift detected."
        elif slope > 0.05:
            status = "healing"
            msg = "Confidence is increasing due to successful matches."
        else:
            status = "stable"
            msg = "Selector is stable."

        return {
            "caller_id": caller_id,
            "current_confidence": cn,
            "slope": slope,
            "status": status,
            "message": msg,
            "history_points": len(history)
        }

    def predict_failures(self) -> List[Dict[str, Any]]:
        """
        Scan all active anchors and predict which scrapers are about to break.
        """
        predictions = []
        with self.store._get_conn() as conn:
            rows = conn.execute("SELECT caller_id FROM anchors").fetchall()
            caller_ids = [r["caller_id"] for r in rows]

        for cid in caller_ids:
            analysis = self.get_selector_drift(cid)
            if analysis["status"] in ("critical_risk", "decaying"):
                predictions.append(analysis)
                
        return predictions

    def get_health_report(self) -> Dict[str, Any]:
        """
        Generates a summary health report for all monitored scraping anchors.
        """
        with self.store._get_conn() as conn:
            rows = conn.execute("SELECT caller_id, confidence, primary_selector, tag FROM anchors").fetchall()
            
        anchors_summary = []
        total_confidence = 0.0
        critical_count = 0
        decaying_count = 0
        stable_count = 0
        
        for r in rows:
            cid = r["caller_id"]
            analysis = self.get_selector_drift(cid)
            
            total_confidence += r["confidence"]
            if analysis["status"] == "critical_risk":
                critical_count += 1
            elif analysis["status"] == "decaying":
                decaying_count += 1
            else:
                stable_count += 1
                
            anchors_summary.append({
                "caller_id": cid,
                "primary_selector": r["primary_selector"],
                "tag": r["tag"],
                "confidence": r["confidence"],
                "status": analysis["status"],
                "slope": analysis["slope"]
            })
            
        total_anchors = len(rows)
        avg_confidence = total_confidence / total_anchors if total_anchors > 0 else 1.0
        
        # Query total heal events
        with self.store._get_conn() as conn:
            heals_count = conn.execute("SELECT COUNT(*) as count FROM heal_events").fetchone()["count"]

        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_anchors": total_anchors,
            "average_confidence": avg_confidence,
            "status_breakdown": {
                "stable": stable_count,
                "decaying": decaying_count,
                "critical_risk": critical_count
            },
            "total_heals_triggered": heals_count,
            "anchors": anchors_summary
        }
