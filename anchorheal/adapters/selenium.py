from typing import List, Dict, Optional, Any
from .base import Element

# Try imports, fallback to None if not present
try:
    from selenium.webdriver.common.by import By
except ImportError:
    class By:
        CSS_SELECTOR = "css selector"

try:
    from PIL import Image
    import io
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

class SeleniumElement:
    def __init__(self, el: Any):
        self._el = el

    @property
    def tag_name(self) -> str:
        return self._el.tag_name

    @property
    def classes(self) -> List[str]:
        cls_str = self._el.get_attribute("class")
        return cls_str.split() if cls_str else []

    @property
    def id_attr(self) -> Optional[str]:
        return self._el.get_attribute("id")

    @property
    def text(self) -> str:
        return self._el.text

    @property
    def xpath(self) -> str:
        # Query xpath using Javascript on the driver
        try:
            driver = self._el.parent
            xpath_js = """
                function getAbsoluteXPath(element) {
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
                    for ( ; element && element.nodeType == 1; element = element.parentNode ) {
                        comp = comps[comps.length] = {};
                        comp.name = element.nodeName.toLowerCase();
                        comp.position = getPos(element);
                    }
                    for (var i = comps.length - 1; i >= 0; i--) {
                        comp = comps[i];
                        xpath += '/' + comp.name + '[' + comp.position + ']';
                    }
                    return xpath;
                }
                return getAbsoluteXPath(arguments[0]);
            """
            return driver.execute_script(xpath_js, self._el) or ""
        except Exception:
            return ""

    @property
    def rect(self) -> Optional[Dict[str, float]]:
        try:
            r = self._el.rect
            return {
                "x": float(r.get("x", 0)),
                "y": float(r.get("y", 0)),
                "w": float(r.get("width", 0)),
                "h": float(r.get("height", 0))
            }
        except Exception:
            return None

    def get_attribute(self, name: str) -> Optional[str]:
        return self._el.get_attribute(name)

class SeleniumAdapter:
    def query(self, ctx: Any, selector: str) -> Optional[Any]:
        try:
            el = ctx.find_element(By.CSS_SELECTOR, selector)
            return SeleniumElement(el)
        except Exception:
            return None

    def query_all(self, ctx: Any, selector: str) -> List[Any]:
        try:
            elements = ctx.find_elements(By.CSS_SELECTOR, selector)
            return [SeleniumElement(el) for el in elements]
        except Exception:
            return []

    def query_candidates(self, ctx: Any, tag_name: str) -> List[Any]:
        try:
            if tag_name == "*":
                # Find all
                elements = ctx.find_elements("xpath", "//*")
            else:
                elements = ctx.find_elements("css selector", tag_name)
            return elements
        except Exception:
            return []

    def extract_features_bulk(self, ctx: Any, candidates: List[Any]) -> List[Dict[str, Any]]:
        if not candidates:
            return []
        js_code = """
        var elements = arguments[0];
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
        """
        try:
            driver = getattr(ctx, "parent", ctx)
            if hasattr(driver, "execute_script"):
                res = driver.execute_script(js_code, candidates)
                if isinstance(res, list):
                    return res
            if candidates and hasattr(candidates[0], "parent"):
                res = candidates[0].parent.execute_script(js_code, candidates)
                if isinstance(res, list):
                    return res
        except Exception:
            pass
        return [self.extract_features(c) for c in candidates]

    def extract_features(self, el: Any, ctx: Optional[Any] = None) -> Dict[str, Any]:
        if not isinstance(el, SeleniumElement):
            el = SeleniumElement(el)
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
            driver = el._el.parent
            # Get viewport size
            v_size = driver.execute_script("return {w: window.innerWidth, h: window.innerHeight};")
            viewport = {"w": float(v_size["w"]), "h": float(v_size["h"])}
            
            if bbox and viewport["w"] > 0 and viewport["h"] > 0:
                # Calculate center position
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
            driver = el._el.parent
            parent_chain_js = """
                var parents = [];
                var p = arguments[0].parentNode;
                while (p && p.nodeType === 1 && parents.length < 5) {
                    var name = p.nodeName.toLowerCase();
                    if (p.id) name += '#' + p.id;
                    if (p.className) name += '.' + Array.from(p.classList).join('.');
                    parents.push(name);
                    p = p.parentNode;
                }
                return parents;
            """
            val = driver.execute_script(parent_chain_js, el._el)
            parent_chain = val if isinstance(val, list) else []
            
            sibling_text_js = """
                var textList = [];
                var sib = arguments[0].parentNode.firstChild;
                while (sib) {
                    if (sib !== arguments[0] && sib.nodeType === 1 && sib.textContent.trim()) {
                        textList.push(sib.textContent.trim().substring(0, 50));
                    }
                    sib = sib.nextSibling;
                }
                return textList;
            """
            val = driver.execute_script(sibling_text_js, el._el)
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
        # ctx is driver
        if not HAS_PIL:
            return None
        try:
            # Get full page screenshot
            png_bytes = ctx.get_screenshot_as_png()
            img = Image.open(io.BytesIO(png_bytes))
            
            # Crop elements
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
