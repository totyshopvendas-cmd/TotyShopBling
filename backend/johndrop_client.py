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
