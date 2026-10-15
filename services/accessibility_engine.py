class AccessibilityEngine:
    """Accessibilità come confidence morbida, senza penalità hard."""

    def trail_confidence(self, trail_dist_m):
        """Score accessibilità più sensibile sotto i 50 m.

        GeoLichen 2.9.6:
        distingue meglio un punto sul sentiero da uno solo vicino.
        """
        try:
            if trail_dist_m is None:
                return 50.0
            d = float(trail_dist_m)
            if d <= 5:
                return 100.0
            if d <= 10:
                return 98.0
            if d <= 20:
                return 95.0
            if d <= 30:
                return 90.0
            if d <= 50:
                return 80.0
            if d <= 75:
                return 65.0
            if d <= 100:
                return 50.0
            if d <= 200:
                return 30.0
            return 10.0
        except Exception:
            return 50.0

    def trail_class(self, trail_dist_m):
        try:
            if trail_dist_m is None:
                return "unknown"
            d = float(trail_dist_m)
            if d <= 10:
                return "on_trail"
            if d <= 30:
                return "very_close"
            if d <= 50:
                return "close"
            if d <= 100:
                return "moderate"
            if d <= 200:
                return "far"
            return "very_far"
        except Exception:
            return "unknown"


    def context_confidence(self, context_dist_m, context=None):
        context = context or {}
        ctx_type = str(context.get("type") or "").lower()
        try:
            if context_dist_m is None:
                return 50.0
            d = float(context_dist_m)
            if ctx_type in ["pass", "summit_peak", "refuge_malga", "hydro", "lake"]:
                if d <= 100: return 100.0
                if d <= 300: return 90.0
                if d <= 700: return 75.0
                if d <= 1200: return 60.0
                return 40.0
            if ctx_type in ["mountain_area", "mountain_group", "valley", "forest_area", "locality", "generic_toponym"]:
                if d <= 300: return 95.0
                if d <= 800: return 85.0
                if d <= 1500: return 72.0
                if d <= 3000: return 58.0
                return 40.0
            if d <= 250: return 90.0
            if d <= 1000: return 70.0
            if d <= 2500: return 55.0
            return 40.0
        except Exception:
            return 50.0

    def trail_weight(self, context=None):
        context = context or {}
        ctx_type = str(context.get("type") or "").lower()
        text = str(context.get("text") or context.get("raw") or "").lower()
        if any(k in text for k in ["sentiero", "mulattiera", "traccia", "strada forestale", "cai", "via "]) or ctx_type == "trail":
            return 0.70
        if ctx_type in ["pass", "refuge_malga"]:
            return 0.45
        if ctx_type in ["mountain_area", "mountain_group", "forest_area", "valley"]:
            return 0.25
        return 0.35

    def final_accessibility_score(self, trail_dist_m=None, context_dist_m=None, context=None):
        trail = self.trail_confidence(trail_dist_m)
        ctx = self.context_confidence(context_dist_m, context=context)
        tw = self.trail_weight(context)
        cw = 1.0 - tw
        acc = max(0.0, min(100.0, (tw * trail) + (cw * ctx)))
        return {
            "accessibility_score": acc,
            "accessibility_confidence": acc,
            "trail_accessibility_score": trail,
            "trail_class": self.trail_class(trail_dist_m),
            "context_score": ctx,
            "context_weight": cw,
            "trail_weight": tw,
            "rule": "soft_accessibility_confidence_no_penalty",
        }
