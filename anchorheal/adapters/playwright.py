from typing import List, Dict, Optional, Any
from .base import Element

try:
    from PIL import Image
    import io
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

class PlaywrightElement:
    def __init__(self, locator: Any):
        self._locator = locator

    @property
    def tag_name(self) -> str:
        try:
            val = self._locator.evaluate("el => el.tagName.toLowerCase()")
            return val if isinstance(val, str) else ""
        except Exception:
            return ""

    @property
    def classes(self) -> List[str]:
        try:
            val = self._locator.evaluate("el => Array.from(el.classList)")
            return val if isinstance(val, list) else []
        except Exception:
            return []

    @property
    def id_attr(self) -> Optional[str]:
        try:
            val = self._locator.evaluate("el => el.id")
            return val if isinstance(val, str) and val else None
        except Exception:
            return None

    @property
    def text(self) -> str:
        try:
            val = self._locator.inner_text()
            return val if isinstance(val, str) else ""
        except Exception:
            return ""

    @property
    def xpath(self) -> str:
        try:
            xpath_js = """
                el => {
                    var comp, comps = [];
                    var xpath = '';
                    var getPos = function(element) {
                        var sibling, count = 1;
                        var rawSibling = element.previousSibling;
                        while (rawSibling) {
                            if (rawSibling.nodeType == 1 && rawSibling.nodeName == element.nodeName) {
                                count++;
                            }
                            rawSibling = rawSibling.previousSibling;
                        }
                        return count;
                    };
                    for ( ; el && el.nodeType == 1; el = el.parentNode ) {
                        comp = comps[comps.length] = {};
                        comp.name = el.nodeName.toLowerCase();
                        comp.position = getPos(el);
                    }
                    for (var i = comps.length - 1; i >= 0; i--) {
                        comp = comps[i];
                        xpath += '/' + comp.name + '[' + comp.position + ']';
                    }
                    return xpath;
                }
            """
            val = self._locator.evaluate(xpath_js)
            return val if isinstance(val, str) else ""
        except Exception:
            return ""

    @property
    def rect(self) -> Optional[Dict[str, float]]:
        try:
            box = self._locator.bounding_box()
            if box:
                return {
                    "x": float(box.get("x", 0)),
                    "y": float(box.get("y", 0)),
                    "w": float(box.get("width", 0)),
                    "h": float(box.get("height", 0))
                }
            return None
        except Exception:
            return None

    def get_attribute(self, name: str) -> Optional[str]:
        try:
            return self._locator.get_attribute(name)
        except Exception:
            return None

class PlaywrightAdapter:
    def query(self, ctx: Any, selector: str) -> Optional[Any]:
        try:
            loc = ctx.locator(selector).first
            if loc.count() > 0:
                return PlaywrightElement(loc)
            return None
        except Exception:
            return None

    def query_all(self, ctx: Any, selector: str) -> List[Any]:
        try:
            # page.locator(selector).all() returns list of Locators
            locators = ctx.locator(selector).all()
            return [PlaywrightElement(loc) for loc in locators]
        except Exception:
            return []

    def query_candidates(self, ctx: Any, tag_name: str) -> List[Any]:
        try:
            return ctx.locator(tag_name).all()
        except Exception:
            return []

    def extract_features_bulk(self, ctx: Any, candidates: List[Any]) -> List[Dict[str, Any]]:
        if not candidates:
            return []
        js_code = """
        (elements) => {
            var results = [];
            var viewport = {w: window.innerWidth, h: window.innerHeight};
            
            function getAbsoluteXPath(element) {
                var xpath = '';
                try {
                    var comps = [];
                    var curr = element;
                    while (curr && curr.nodeType === 1) {
                        var name = curr.nodeName.toLowerCase();
                        var count = 1;
                        var sib = curr.previousSibling;
                        while (sib) {
                            if (sib.nodeType === 1 && sib.nodeName === curr.nodeName) {
                                count++;
                            }
                            sib = sib.previousSibling;
                        }
                        comps.push({name: name, position: count});
                        curr = curr.parentNode;
                    }
                    for (var j = comps.length - 1; j >= 0; j--) {
                        xpath += '/' + comps[j].name + '[' + comps[j].position + ']';
                    }
                } catch(e) {}
                return xpath;
            }

            for (var i = 0; i < elements.length; i++) {
                var el = elements[i];
                if (!el) {
                    results.push(null);
                    continue;
                }
                
                var tag_name = el.tagName.toLowerCase();
                var classes = el.className ? Array.from(el.classList) : [];
                var id_attr = el.id || null;
                var text = el.textContent ? el.textContent.trim() : "";
                var xpath = getAbsoluteXPath(el);
                
                var bbox = null;
                var rel_position = null;
                try {
                    var rect = el.getBoundingClientRect();
                    bbox = {
                        x: rect.left + window.pageXOffset,
                        y: rect.top + window.pageYOffset,
                        w: rect.width,
                        h: rect.height
                    };
                    if (viewport.w > 0 && viewport.h > 0) {
                        var center_x = bbox.x + bbox.w / 2;
                        var center_y = bbox.y + bbox.h / 2;
                        rel_position = {
                            x_pct: center_x / viewport.w,
                            y_pct: center_y / viewport.h
                        };
                    }
                } catch(e) {}
                
                var parent_chain = [];
                try {
                    var p = el.parentNode;
                    while (p && p.nodeType === 1 && parent_chain.length < 5) {
                        var p_name = p.nodeName.toLowerCase();
                        if (p.id) p_name += '#' + p.id;
                        if (p.className) p_name += '.' + Array.from(p.classList).join('.');
                        parent_chain.push(p_name);
                        p = p.parentNode;
                    }
                } catch(e) {}
                
                var sibling_text = [];
                try {
                    var parentNode = el.parentNode;
                    if (parentNode) {
                        var sib = parentNode.firstChild;
                        while (sib) {
                            if (sib !== el && sib.nodeType === 1 && sib.textContent.trim()) {
                                sibling_text.push(sib.textContent.trim().substring(0, 50));
                            }
                            sib = sib.nextSibling;
                        }
                    }
                } catch(e) {}
                
                results.push({
                    tag: tag_name,
                    classes: classes,
                    id_attr: id_attr,
                    text: text,
                    xpath: xpath,
                    bbox: bbox,
                    viewport: viewport,
                    rel_position: rel_position,
                    parent_chain: parent_chain,
                    sibling_text: sibling_text
                });
            }
            return results;
        }
        """
        try:
            # We construct a locator matching the tag of the candidates and evaluate
            # to run the script in a single round-trip.
            # Page can be retrieved from locator.page or ctx
            page = getattr(ctx, "page", ctx)
            if hasattr(candidates[0], "_locator"):
                first_tag = candidates[0].tag_name
            else:
                first_tag = candidates[0].evaluate("el => el.tagName.toLowerCase()")
            
            # Check if all candidates have the same tag name to prevent desync on mixed tags
            uniform = True
            for c in candidates[1:]:
                if hasattr(c, "_locator"):
                    c_tag = c.tag_name
                else:
                    c_tag = c.evaluate("el => el.tagName.toLowerCase()")
                if c_tag != first_tag:
                    uniform = False
                    break
            
            tag = first_tag if uniform else "*"
            res = page.locator(tag).evaluate_all(js_code)
            if isinstance(res, list) and len(res) == len(candidates):
                return res
        except Exception:
            pass
        results = []
        for c in candidates:
            results.append(self.extract_features(c))
        return results

    def extract_features(self, el: Any, ctx: Optional[Any] = None) -> Dict[str, Any]:
        if not isinstance(el, PlaywrightElement):
            el = PlaywrightElement(el)
        tag = el.tag_name
        classes = el.classes
        id_attr = el.id_attr
        text = el.text
        xpath = el.xpath
        bbox = el.rect

        # Rel position and viewport
        rel_position = None
        viewport = None
        try:
            # We need the page to evaluate viewport
            # page can be retrieved from locator.page
            page = el._locator.page
            v_size = page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
            viewport = {"w": float(v_size["w"]), "h": float(v_size["h"])}
            
            if bbox and viewport["w"] > 0 and viewport["h"] > 0:
                center_x = bbox["x"] + bbox["w"] / 2
                center_y = bbox["y"] + bbox["h"] / 2
                rel_position = {
                    "x_pct": center_x / viewport["w"],
                    "y_pct": center_y / viewport["h"]
                }
        except Exception:
            pass

        # Context features (parent chain & sibling text)
        parent_chain = []
        sibling_text = []
        try:
            parent_chain_js = """
                el => {
                    var parents = [];
                    var p = el.parentNode;
                    while (p && p.nodeType === 1 && parents.length < 5) {
                        var name = p.nodeName.toLowerCase();
                        if (p.id) name += '#' + p.id;
                        if (p.className) name += '.' + Array.from(p.classList).join('.');
                        parents.push(name);
                        p = p.parentNode;
                    }
                    return parents;
                }
            """
            val = el._locator.evaluate(parent_chain_js)
            parent_chain = val if isinstance(val, list) else []
            
            sibling_text_js = """
                el => {
                    var textList = [];
                    var sib = el.parentNode.firstChild;
                    while (sib) {
                        if (sib !== el && sib.nodeType === 1 && sib.textContent.trim()) {
                            textList.push(sib.textContent.trim().substring(0, 50));
                        }
                        sib = sib.nextSibling;
                    }
                    return textList;
                }
            """
            val = el._locator.evaluate(sibling_text_js)
            sibling_text = val if isinstance(val, list) else []
        except Exception:
            pass

        return {
            "tag": tag,
            "classes": classes,
            "id_attr": id_attr,
            "text": text,
            "xpath": xpath,
            "bbox": bbox,
            "viewport": viewport,
            "rel_position": rel_position,
            "parent_chain": parent_chain,
            "sibling_text": sibling_text
        }

    def get_crop(self, ctx: Any, bbox: Dict[str, float]) -> Optional[bytes]:
        # ctx is page
        if not HAS_PIL:
            return None
        try:
            # Get screenshot from Playwright page
            png_bytes = ctx.screenshot()
            img = Image.open(io.BytesIO(png_bytes))
            
            center_x = bbox["x"] + bbox["w"] / 2
            center_y = bbox["y"] + bbox["h"] / 2
            
            crops = {}
            for size in (32, 64):
                left = max(0, center_x - size / 2)
                top = max(0, center_y - size / 2)
                right = min(img.width, center_x + size / 2)
                bottom = min(img.height, center_y + size / 2)
                
                cropped = img.crop((left, top, right, bottom))
                out = io.BytesIO()
                cropped.save(out, format="PNG")
                crops[size] = out.getvalue()
                
            return crops
        except Exception:
            return None
