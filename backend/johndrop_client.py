"""JohnDrop session-based scraper client.

Since JohnDrop has no public REST API, we authenticate via Laravel's
session-cookie login and parse the HTML catalog pages.
"""
from __future__ import annotations

import re
import hashlib
import base64
from typing import Optional

import httpx
from cryptography.fernet import Fernet


BASE_URL = "https://app.jonhdrop.com.br"

# Integration channel IDs (mapped from app.jonhdrop.com.br/dashboard/product/create/*)
INTEGRATION_TOTYSHOP_BLING = "1760"
INTEGRATION_TOTYSHOP_KWAI = "1833"
INTEGRATION_TOTYSHOP_AMAZON = "1835"
INTEGRATION_TOTYSHOP_TEMU = "1836"
INTEGRATION_TOTYSHOP_SHOPEE = "1837"


# ---------- credential encryption ----------
def _fernet(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, secret: str) -> str:
    return _fernet(secret).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str, secret: str) -> str:
    return _fernet(secret).decrypt(ciphertext.encode("utf-8")).decode("utf-8")


# ---------- HTML parsing helpers ----------
_PRICE_RE = re.compile(r'product-price-tag[^>]*>\s*R\$\s*([\d.,]+)')
_LINK_RE = re.compile(r'/dashboard/product/create/(\d+)[^"]*"[^>]*>\s*([^<]+)')
_IMG_RE = re.compile(r'<img src="(https://app\.jonhdrop\.com\.br/uploads/[^"]+)"')
_STOCK_RE = re.compile(r'Estoque:\s*(\d+)\s*pcs')
_COR_RE = re.compile(r'Cor:\s*([^<]+)')
_TAM_RE = re.compile(r'Tamanho:\s*([^<]+)')
_CSRF_RE = re.compile(r'<meta name="csrf-token" content="([^"]+)"')
_CARDS_RE = re.compile(
    r'<div class="card product-box">.*?(?=<div class="card product-box">|<div id="footer"|</body>)',
    re.DOTALL,
)
_CATEGORIES_RE = re.compile(
    r'<option value="(\d+)"[^>]*>([^<]+?)\((\d+)\)</option>'
)
_PAGES_RE = re.compile(r'page=(\d+)')


def _brl_to_float(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _parse_catalog_html(html: str) -> list[dict]:
    items: list[dict] = []
    for card in _CARDS_RE.finditer(html):
        block = card.group(0)
        link = _LINK_RE.search(block)
        if not link:
            continue
        img = _IMG_RE.search(block)
        price = _PRICE_RE.search(block)
        stock = _STOCK_RE.search(block)
        cor = _COR_RE.search(block)
        tam = _TAM_RE.search(block)
        raw_title = link.group(2).strip()
        # extract product code between first parentheses if present
        code_match = re.match(r'\(([^)]+)\)\s*(.*)', raw_title)
        product_code = code_match.group(1).strip() if code_match else ""
        clean_title = code_match.group(2).strip() if code_match else raw_title
        items.append({
            "jd_id": link.group(1),
            "raw_title": raw_title,
            "clean_title": clean_title,
            "product_code": product_code,
            "image": img.group(1) if img else None,
            "price": _brl_to_float(price.group(1)) if price else 0.0,
            "stock": int(stock.group(1)) if stock else 0,
            "variation_color": cor.group(1).strip() if cor else None,
            "variation_size": tam.group(1).strip() if tam else None,
        })
    return items


def _parse_categories(html: str) -> list[dict]:
    cats = []
    for cid, cname, count in _CATEGORIES_RE.findall(html):
        cats.append({
            "id": cid,
            "name": cname.strip(),
            "count": int(count),
        })
    return cats


def _parse_max_page(html: str) -> int:
    pages = [int(p) for p in _PAGES_RE.findall(html)]
    return max(pages) if pages else 1


_CSRF_INPUT_RE = re.compile(r'<input[^>]*name="_token"[^>]*value="([^"]*)"')
_FORM_INPUT_RE = re.compile(
    r'<input\b(?=[^>]*\bname="([^"]+)")(?=[^>]*\bvalue="([^"]*)")[^>]*>',
)
_TEXTAREA_RE = re.compile(
    r'<textarea[^>]*\bname="([^"]+)"[^>]*>(.*?)</textarea>',
    re.DOTALL,
)
_SELECT_RE = re.compile(
    r'<select[^>]*\bname="([^"]+)"[^>]*>(.*?)</select>',
    re.DOTALL,
)
_SELECTED_OPTION_RE = re.compile(
    r'<option[^>]*\bselected[^>]*\bvalue="([^"]*)"',
)


def _parse_form_fields(html: str) -> dict:
    """Extract every pre-filled form field from the product create/edit page
    so we can re-submit without losing data."""
    fields: dict = {}
    # CSRF first
    m = _CSRF_INPUT_RE.search(html)
    if m:
        fields["_token"] = m.group(1)

    # Regular inputs with value=""
    for name, value in _FORM_INPUT_RE.findall(html):
        if name in ("uploader[]",):
            continue
        if name.endswith("[]"):
            fields.setdefault(name, []).append(value)
        else:
            # Skip re-setting _token
            if name == "_token":
                continue
            fields[name] = value

    # Textareas
    for name, body in _TEXTAREA_RE.findall(html):
        fields[name] = body.strip()

    # Selects: pick the "selected" option value
    for name, body in _SELECT_RE.findall(html):
        m = _SELECTED_OPTION_RE.search(body)
        if m:
            fields[name] = m.group(1)

    return fields


# ---------- Client ----------
class JohnDropAuthError(Exception):
    pass


class JohnDropClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self._client: Optional[httpx.AsyncClient] = None
        self._logged_in = False

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=25,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (BlingDrop-Integration/1.0)",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            },
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def _get_csrf(self) -> str:
        r = await self._client.get("/login")
        m = _CSRF_RE.search(r.text)
        if not m:
            raise JohnDropAuthError("Não foi possível obter token CSRF")
        return m.group(1)

    async def login(self) -> bool:
        csrf = await self._get_csrf()
        r = await self._client.post(
            "/login",
            data={"_token": csrf, "email": self.email, "password": self.password},
            headers={"X-CSRF-TOKEN": csrf, "Referer": f"{BASE_URL}/login"},
        )
        # Success: redirected to /dashboard (even if status 405 because of redirected POST)
        final_path = str(r.url).replace(BASE_URL, "")
        self._logged_in = "/login" not in final_path
        return self._logged_in

    async def ensure_logged_in(self):
        if not self._logged_in:
            ok = await self.login()
            if not ok:
                raise JohnDropAuthError("Credenciais inválidas ou login falhou")

    async def fetch_catalog_page(
        self,
        page: int = 1,
        integration_filter: str = "without_integration",
        category_id: str = "",
        name: str = "",
    ) -> dict:
        """Fetch and parse a catalog page. Returns {items, categories, max_page}."""
        await self.ensure_logged_in()
        r = await self._client.get(
            "/dashboard/catalog",
            params={
                "page": page,
                "integration_filter": integration_filter,
                "category_id": category_id,
                "name": name,
                "sorter": "",
            },
        )
        if "/login" in str(r.url):
            raise JohnDropAuthError("Sessão expirada")
        items = _parse_catalog_html(r.text)
        categories = _parse_categories(r.text)
        max_page = _parse_max_page(r.text)
        return {
            "items": items,
            "categories": categories,
            "max_page": max_page,
            "current_page": page,
        }

    async def fetch_product_form(self, jd_id: str) -> dict:
        """Fetch the edit page and return all pre-filled form fields."""
        await self.ensure_logged_in()
        r = await self._client.get(f"/dashboard/product/create/{jd_id}")
        if "/login" in str(r.url):
            raise JohnDropAuthError("Sessão expirada")
        return _parse_form_fields(r.text)

    async def find_my_product_id_by_sku(self, sku: str, max_pages: int = 30) -> Optional[str]:
        """Search the user's 'Meus Produtos' page (/dashboard/product) by SKU and return
        the user-side product Id (the number shown in the 'Id' column, e.g. 109908)."""
        await self.ensure_logged_in()
        if not sku:
            return None
        for page in range(1, max_pages + 1):
            r = await self._client.get("/dashboard/product", params={"page": page, "sku": sku})
            if "/login" in str(r.url):
                raise JohnDropAuthError("Sessão expirada")
            html = r.text
            # Each row in 'Meus produtos' has a link/button with the product id and sku.
            # Strategy: find any HTML chunk that contains BOTH the SKU and a numeric id.
            # Look for /dashboard/product/edit/<id> or data attributes referencing the id.
            # Also try simple table-row scan: extract rows containing sku, then first 5-7 digit number.
            import re as _re
            # Try links to edit/{id}
            for m in _re.finditer(r'/dashboard/product/edit/(\d+)', html):
                # Look at +/- 800 chars context around the match to confirm SKU is in same row
                start = max(0, m.start() - 1500)
                end = min(len(html), m.end() + 500)
                ctx = html[start:end]
                if sku in ctx:
                    return m.group(1)
            # Fallback: rows in tbody — look for our SKU and find any 6-digit number near it
            for sku_match in _re.finditer(_re.escape(sku), html):
                start = max(0, sku_match.start() - 1500)
                end = min(len(html), sku_match.end() + 1500)
                ctx = html[start:end]
                # First "Id" column number — usually 5-9 digits
                num_match = _re.search(r'>\s*(\d{5,9})\s*<', ctx)
                if num_match:
                    return num_match.group(1)
            # Nothing found on this page and no SKU filter applied? Stop after page 1 if SKU filter gave 0.
            if "Nenhum registro" in html or "Nenhum produto" in html:
                break
            # If we paginated and the page has no rows, stop.
            if page >= 1 and not _re.search(r'/dashboard/product/edit/\d+', html):
                break
        return None

    async def push_product(self, jd_id: str, patch: dict, integration_ids: Optional[list] = None) -> dict:
        """Re-submit the product form with overrides. Preserves all other fields.
        patch keys are the override values.
        integration_ids: se fornecido, sobrescreve 'integrations[]' com apenas esses IDs
        (útil para forçar só TotyShop-Bling em vez das 5 integrações padrão).

        IMPORTANT: JohnDrop uses enctype=multipart/form-data so we MUST send multipart
        (URL-encoded POSTs return 200 OK but silently discard the data)."""
        fields = await self.fetch_product_form(jd_id)
        # Merge: list fields stay, scalar fields get overridden
        for k, v in patch.items():
            fields[k] = v
        # Override integrations if specified
        if integration_ids is not None:
            fields["integrations[]"] = list(integration_ids)

        # Build multipart/form-data body manually (httpx files= doesn't handle repeated keys cleanly)
        import uuid as _uuid
        boundary = f"----BlingDropFD{_uuid.uuid4().hex}"
        lines: list[str] = []
        for k, v in fields.items():
            if isinstance(v, list):
                items = v
            else:
                items = [v if v is not None else ""]
            for item in items:
                lines.append(f"--{boundary}")
                lines.append(f'Content-Disposition: form-data; name="{k}"')
                lines.append("")
                lines.append(str(item))
        lines.append(f"--{boundary}--")
        lines.append("")
        body = "\r\n".join(lines).encode("utf-8")

        r = await self._client.post(
            f"/dashboard/product/storev2/{jd_id}",
            content=body,
            headers={
                "X-CSRF-TOKEN": fields.get("_token", ""),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Referer": f"{BASE_URL}/dashboard/product/create/{jd_id}",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
        final = str(r.url)
        # JohnDrop returns JSON when X-Requested-With is set:
        # {"success": true, "message": "Produto criado com sucesso..."}
        server_message = ""
        try:
            data = r.json()
            success = bool(data.get("success")) and r.status_code == 200
            server_message = (data.get("message") or "").replace("<br>", " ")
        except Exception:
            success = r.status_code in (200, 302) and "/login" not in final
        return {
            "success": success,
            "status_code": r.status_code,
            "final_url": final,
            "message": server_message,
        }
