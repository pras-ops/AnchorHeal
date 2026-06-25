from typing import List, Dict, Optional, Any
from .base import Element

class BS4Element:
    def __init__(self, tag: Any):
        self._tag = tag

    @property
    def tag_name(self) -> str:
        return self._tag.name or ""

    @property
    def classes(self) -> List[str]:
        val = self._tag.get("class")
        if isinstance(val, list):
            return val
        elif isinstance(val, str):
            return val.split()
        return []

    @property
    def id_attr(self) -> Optional[str]:
        val = self._tag.get("id")
        return val if isinstance(val, str) else None

    @property
    def text(self) -> str:
        return self._tag.get_text().strip()

    @property
    def xpath(self) -> str:
        # Compute xpath recursively
        path = []
        curr = self._tag
        while curr and curr.name != '[document]':
            name = curr.name
            if not name:
                break
            parent = curr.parent
            if parent:
                siblings = parent.find_all(name, recursive=False)
                if len(siblings) == 1:
                    path.append(name)
                else:
                    index = siblings.index(curr) + 1
                    path.append(f"{name}[{index}]")
            else:
                path.append(name)
            curr = parent
        path.reverse()
        return "/" + "/".join(path) if path else "/"

    @property
    def rect(self) -> Optional[Dict[str, float]]:
        return None

    def get_attribute(self, name: str) -> Optional[str]:
        val = self._tag.get(name)
        if isinstance(val, list):
            return " ".join(val)
        return val

class BS4Adapter:
    def query(self, ctx: Any, selector: str) -> Optional[Any]:
        try:
            el = ctx.select_one(selector)
            if el:
                return BS4Element(el)
            return None
        except Exception:
            return None

    def query_all(self, ctx: Any, selector: str) -> List[Any]:
        try:
            tags = ctx.select(selector)
            return [BS4Element(t) for t in tags]
        except Exception:
            return []

    def query_candidates(self, ctx: Any, tag_name: str) -> List[Any]:
        try:
            if tag_name == "*":
                return ctx.find_all(True)
            return ctx.find_all(tag_name)
        except Exception:
            return []

    def extract_features_bulk(self, ctx: Any, candidates: List[Any]) -> List[Dict[str, Any]]:
        results = []
        for c in candidates:
            results.append(self.extract_features(c))
        return results

    def extract_features(self, el: Any, ctx: Optional[Any] = None) -> Dict[str, Any]:
        if not isinstance(el, BS4Element):
            el = BS4Element(el)
        tag = el.tag_name
        classes = el.classes
        id_attr = el.id_attr
        text = el.text
        xpath = el.xpath

        # Parent chain extraction
        parent_chain = []
        curr = el._tag.parent
        while curr and curr.name != '[document]' and len(parent_chain) < 5:
            name = curr.name
            if not name:
                break
            id_val = curr.get("id")
            if id_val:
                name += f"#{id_val}"
            classes_val = curr.get("class")
            if classes_val:
                if isinstance(classes_val, list):
                    name += "." + ".".join(classes_val)
                elif isinstance(classes_val, str):
                    name += "." + classes_val
            parent_chain.append(name)
            curr = curr.parent

        # Sibling text extraction
        sibling_text = []
        parent = el._tag.parent
        if parent:
            for child in parent.children:
                if child != el._tag and child.name:
                    txt = child.get_text().strip()
                    if txt:
                        sibling_text.append(txt[:50])

        return {
            "tag": tag,
            "classes": classes,
            "id_attr": id_attr,
            "text": text,
            "xpath": xpath,
            "bbox": None,
            "viewport": None,
            "rel_position": None,
            "parent_chain": parent_chain,
            "sibling_text": sibling_text
        }

