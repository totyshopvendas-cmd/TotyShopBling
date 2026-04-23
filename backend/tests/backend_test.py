"""BlingDrop backend regression tests - auth, products, sync, dashboard, integrations, AI."""
import os
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://bling-johndrop-sync.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

EMAIL = f"test+{uuid.uuid4().hex[:6]}@blingdrop.com"
PASSWORD = "Test1234!"
NAME = "Test User"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def auth(session):
    r = session.post(f"{API}/auth/register", json={"email": EMAIL, "password": PASSWORD, "name": NAME}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "_id" not in data and "_id" not in data["user"]
    token = data["token"]
    return {"token": token, "user_id": data["user"]["user_id"], "email": EMAIL}


@pytest.fixture(scope="module")
def headers(auth):
    return {"Authorization": f"Bearer {auth['token']}", "Content-Type": "application/json"}


# -------- Auth --------
def test_health(session):
    r = session.get(f"{API}/", timeout=15)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_register_duplicate(session, auth):
    r = session.post(f"{API}/auth/register", json={"email": auth["email"], "password": PASSWORD, "name": NAME}, timeout=15)
    assert r.status_code == 400


def test_login_ok(session, auth):
    r = session.post(f"{API}/auth/login", json={"email": auth["email"], "password": PASSWORD}, timeout=15)
    assert r.status_code == 200 and r.json()["user"]["email"] == auth["email"]


def test_login_bad(session, auth):
    r = session.post(f"{API}/auth/login", json={"email": auth["email"], "password": "wrong"}, timeout=15)
    assert r.status_code == 401


def test_me_jwt(session, headers):
    r = session.get(f"{API}/auth/me", headers=headers, timeout=15)
    assert r.status_code == 200
    assert "_id" not in r.json()


def test_me_no_auth(session):
    r = session.get(f"{API}/auth/me", timeout=15)
    assert r.status_code == 401


def test_me_session_cookie(session, auth):
    """Seed a session_token directly in MongoDB and verify cookie + bearer auth."""
    from pymongo import MongoClient
    from datetime import datetime, timezone, timedelta
    mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mc[os.environ.get("DB_NAME", "test_database")]
    stoken = f"sess_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "user_id": auth["user_id"],
        "session_token": stoken,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # cookie
    r = requests.get(f"{API}/auth/me", cookies={"session_token": stoken}, timeout=15)
    assert r.status_code == 200, r.text
    # bearer fallback
    r2 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {stoken}"}, timeout=15)
    assert r2.status_code == 200


def test_logout(session):
    r = session.post(f"{API}/auth/logout", timeout=15)
    assert r.status_code == 200


# -------- Products --------
def test_products_auth_gated(session):
    for path in ["/products", "/dashboard/stats", "/integrations/status"]:
        assert session.get(f"{API}{path}", timeout=15).status_code == 401


def test_seed_products_legacy_no_seo(session, headers):
    """Legacy /products/seed must NOT apply SEO -> raw titles preserved (with brand+EAN)."""
    r = session.post(f"{API}/products/seed", headers=headers, timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert j["created"] == 8 and j["total_available"] == 8
    assert j["apply_seo"] is False
    # idempotent
    r2 = session.post(f"{API}/products/seed", headers=headers, timeout=20)
    assert r2.json()["created"] == 0 and r2.json()["skipped"] == 8
    # Raw titles preserved -> include brand & EAN, may exceed 60
    products = session.get(f"{API}/products", headers=headers, timeout=15).json()
    jd001 = next(p for p in products if p["sku"] == "JD-CRM-001")
    assert "DermaBrasil" in jd001["title"]
    assert "7891234560011" in jd001["title"]


def test_list_and_get(session, headers):
    r = session.get(f"{API}/products", headers=headers, timeout=15)
    assert r.status_code == 200
    products = r.json()
    assert len(products) == 8
    for p in products:
        assert "_id" not in p
        assert "amazon" in p and "shopee" in p and "kwai" in p
    pid = products[0]["id"]
    r2 = session.get(f"{API}/products/{pid}", headers=headers, timeout=15)
    assert r2.status_code == 200 and r2.json()["id"] == pid


def test_create_update_delete(session, headers):
    payload = {
        "sku": f"TEST_{uuid.uuid4().hex[:6]}", "title": "Produto Teste", "product_code": "T001",
        "price": 10.0, "cost": 5.0, "stock_johndrop": 5, "stock_bling": 5,
    }
    r = session.post(f"{API}/products", headers=headers, json=payload, timeout=15)
    assert r.status_code == 200
    pid = r.json()["id"]
    payload["title"] = "Atualizado"
    r2 = session.put(f"{API}/products/{pid}", headers=headers, json=payload, timeout=15)
    assert r2.status_code == 200 and r2.json()["title"] == "Atualizado"
    r3 = session.delete(f"{API}/products/{pid}", headers=headers, timeout=15)
    assert r3.status_code == 200
    r4 = session.get(f"{API}/products/{pid}", headers=headers, timeout=15)
    assert r4.status_code == 404


def test_sync_success_and_stock_replication(session, headers):
    """Create a fully-valid product and verify sync flips to 'synced' + replicates stock."""
    payload = {
        "sku": f"TEST_SYNC_{uuid.uuid4().hex[:6]}",
        "title": "Creme Facial Hidratante 50g JD001",  # <60
        "product_code": "JD001",
        "stock_johndrop": 45, "stock_bling": 0,
        "amazon": {"enabled": True, "bullet_points": ["a"*20, "b"*20, "c"*20, "d"*20, "e"*20, "f"*20]},
        "shopee": {"enabled": True, "weight_kg": 0.15},
    }
    pid = session.post(f"{API}/products", headers=headers, json=payload, timeout=15).json()["id"]
    r = session.post(f"{API}/products/{pid}/sync", headers=headers, timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert j["sync_status"] == "synced"
    assert j["stock_bling"] == j["stock_johndrop"] == 45


def test_sync_out_of_stock(session, headers):
    """Create a product with 0 stock and verify out-of-stock error on sync."""
    payload = {
        "sku": f"TEST_OOS_{uuid.uuid4().hex[:6]}",
        "title": "Sem Estoque JD002",
        "product_code": "JD002",
        "stock_johndrop": 0, "stock_bling": 0,
        "amazon": {"enabled": True, "bullet_points": ["a"*20]*6},
        "shopee": {"enabled": True, "weight_kg": 0.5},
    }
    pid = session.post(f"{API}/products", headers=headers, json=payload, timeout=15).json()["id"]
    r = session.post(f"{API}/products/{pid}/sync", headers=headers, timeout=20)
    j = r.json()
    assert j["sync_status"] == "error"
    assert "estoque" in j["sync_message"].lower()


def test_sync_validation_title_too_long(session, headers):
    payload = {
        "sku": f"TEST_{uuid.uuid4().hex[:6]}",
        "title": "T" * 70, "product_code": "X",
        "stock_johndrop": 10, "stock_bling": 10,
        "amazon": {"enabled": True, "bullet_points": ["a"] * 6},
        "shopee": {"enabled": True, "weight_kg": 0.5},
    }
    r = session.post(f"{API}/products", headers=headers, json=payload, timeout=15)
    pid = r.json()["id"]
    r2 = session.post(f"{API}/products/{pid}/sync", headers=headers, timeout=20)
    msg = r2.json()["sync_message"]
    assert "60" in msg


def test_sync_validation_bullets_and_weight(session, headers):
    payload = {
        "sku": f"TEST_{uuid.uuid4().hex[:6]}",
        "title": "Curto", "product_code": "X",
        "stock_johndrop": 10, "stock_bling": 10,
        "amazon": {"enabled": True, "bullet_points": ["a", "b", "", "", "", ""]},
        "shopee": {"enabled": True, "weight_kg": None},
    }
    r = session.post(f"{API}/products", headers=headers, json=payload, timeout=15)
    pid = r.json()["id"]
    r2 = session.post(f"{API}/products/{pid}/sync", headers=headers, timeout=20)
    msg = r2.json()["sync_message"]
    assert "bullet" in msg.lower() and "peso" in msg.lower()


# -------- Dashboard --------
def test_dashboard_stats(session, headers):
    r = session.get(f"{API}/dashboard/stats", headers=headers, timeout=15)
    assert r.status_code == 200
    j = r.json()
    for k in ("total_products", "synced", "pending", "errors", "marketplace_coverage", "stock_divergences"):
        assert k in j
    assert "amazon" in j["marketplace_coverage"]


# -------- Integrations --------
def test_integrations_default_and_toggle(session, headers):
    r = session.get(f"{API}/integrations/status", headers=headers, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["bling"]["connected"] is False
    r2 = session.post(f"{API}/integrations/toggle", headers=headers,
                      json={"service": "bling", "connected": True}, timeout=15)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["bling"]["connected"] is True and j2["bling"]["token_valid"] is True
    assert j2["bling"]["last_sync"] is not None


# -------- AI --------
@pytest.mark.parametrize("model", ["claude", "gpt"])
def test_ai_generate_title(session, headers, model):
    body = {"product_code": "JD001", "category": "Skincare", "keywords": "creme facial",
            "raw_name": "Creme Facial Hidratante 50g", "model": model}
    r = session.post(f"{API}/ai/generate-title", headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"LLM ({model}) error {r.status_code}: {r.text[:200]}")
    j = r.json()
    assert len(j["title"]) <= 60 and j["length"] == len(j["title"])


def test_ai_generate_bullets(session, headers):
    body = {"title": "Creme Facial Hidratante 50g JD001", "product_code": "JD001",
            "category": "Skincare", "keywords": "hidratante", "model": "claude"}
    r = session.post(f"{API}/ai/generate-bullets", headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"LLM error: {r.text[:200]}")
    bullets = r.json()["bullets"]
    assert len(bullets) == 6


def test_ai_generate_description(session, headers):
    body = {"title": "Creme Facial Hidratante 50g JD001",
            "bullets": ["Hidrata por 24h", "Vitamina C", "Toque seco", "Todos os tipos", "Não comedogênico", "JD001"],
            "model": "claude"}
    r = session.post(f"{API}/ai/generate-description", headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"LLM error: {r.text[:200]}")
    assert isinstance(r.json()["description"], str) and len(r.json()["description"]) > 50



# ============================================================
# Iteration 2: JohnDrop import (with SEO) + Pricing calculator
# ============================================================

# Use isolated user so prior seed/products don't interfere with import counts.
EMAIL2 = f"test+{uuid.uuid4().hex[:6]}@blingdrop.com"


@pytest.fixture(scope="module")
def auth2(session):
    r = session.post(f"{API}/auth/register",
                     json={"email": EMAIL2, "password": PASSWORD, "name": NAME}, timeout=30)
    assert r.status_code == 200, r.text
    return {"token": r.json()["token"], "user_id": r.json()["user"]["user_id"]}


@pytest.fixture(scope="module")
def headers2(auth2):
    return {"Authorization": f"Bearer {auth2['token']}", "Content-Type": "application/json"}


# -------- JohnDrop /api/johndrop/import --------
def test_johndrop_import_blocked_when_disconnected(session, headers2):
    r = session.post(f"{API}/johndrop/import", headers=headers2,
                     json={"apply_seo": True}, timeout=20)
    assert r.status_code == 400
    assert "johndrop" in r.json()["detail"].lower() or "conecte" in r.json()["detail"].lower()


def test_johndrop_import_after_connect_creates_8_with_seo(session, headers2):
    # Connect JohnDrop
    rt = session.post(f"{API}/integrations/toggle", headers=headers2,
                      json={"service": "johndrop", "connected": True}, timeout=15)
    assert rt.status_code == 200
    assert rt.json()["johndrop"]["connected"] is True

    r = session.post(f"{API}/johndrop/import", headers=headers2,
                     json={"apply_seo": True}, timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert j["created"] == 8 and j["skipped"] == 0 and j["total_available"] == 8
    assert j["apply_seo"] is True
    # Items contain seo_title/title_length/raw_title
    assert len(j["items"]) == 8
    for it in j["items"]:
        assert it["title_length"] <= 60
        assert "raw_title" in it and "seo_title" in it


def test_johndrop_import_idempotent_second_call(session, headers2):
    r = session.post(f"{API}/johndrop/import", headers=headers2,
                     json={"apply_seo": True}, timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert j["created"] == 0 and j["skipped"] == 8


def test_imported_products_have_seo_titles(session, headers2):
    """All imported products must: <=60 chars, no brand, no EAN, contain product_code."""
    products = session.get(f"{API}/products", headers=headers2, timeout=15).json()
    assert len(products) == 8
    for p in products:
        title = p["title"]
        assert len(title) <= 60, f"Title >60: {title!r}"
        if p.get("brand"):
            assert p["brand"].lower() not in title.lower(), f"Brand leaked in title: {title}"
        if p.get("ean"):
            assert p["ean"] not in title, f"EAN leaked in title: {title}"
        assert p["product_code"].lower() in title.lower(), f"Code missing in title: {title}"


def test_apply_seo_format_on_jd001(session, headers2):
    """Specifically validate the example from spec for JD-CRM-001."""
    products = session.get(f"{API}/products", headers=headers2, timeout=15).json()
    jd001 = next(p for p in products if p["sku"] == "JD-CRM-001")
    title = jd001["title"]
    assert "DermaBrasil" not in title
    assert "7891234560011" not in title
    assert "JD001" in title
    assert len(title) <= 60
    # Should retain core terms
    assert "Creme" in title and "Facial" in title


# -------- /api/johndrop/import apply_seo=false --------
EMAIL3 = f"test+{uuid.uuid4().hex[:6]}@blingdrop.com"


@pytest.fixture(scope="module")
def headers3(session):
    r = session.post(f"{API}/auth/register",
                     json={"email": EMAIL3, "password": PASSWORD, "name": NAME}, timeout=30)
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    session.post(f"{API}/integrations/toggle", headers=h,
                 json={"service": "johndrop", "connected": True}, timeout=15)
    return h


def test_johndrop_import_apply_seo_false_keeps_raw(session, headers3):
    r = session.post(f"{API}/johndrop/import", headers=headers3,
                     json={"apply_seo": False}, timeout=20)
    assert r.status_code == 200 and r.json()["created"] == 8
    products = session.get(f"{API}/products", headers=headers3, timeout=15).json()
    jd001 = next(p for p in products if p["sku"] == "JD-CRM-001")
    assert "DermaBrasil" in jd001["title"]
    assert "7891234560011" in jd001["title"]
    assert len(jd001["title"]) > 60  # raw is long


# -------- /api/johndrop/import auth gating --------
def test_johndrop_import_requires_auth(session):
    r = session.post(f"{API}/johndrop/import", json={"apply_seo": True}, timeout=15)
    assert r.status_code == 401


# -------- /api/pricing/calculate --------
def test_pricing_requires_auth(session):
    r = session.post(f"{API}/pricing/calculate",
                     json={"cost": 32.5, "packaging": 2, "campaigns": 5}, timeout=15)
    assert r.status_code == 401


def test_pricing_main_formula(session, headers):
    r = session.post(f"{API}/pricing/calculate", headers=headers,
                     json={"cost": 32.5, "packaging": 2, "campaigns": 5}, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["selling_price"] == 73.39
    b = j["breakdown"]
    assert b["total_cost"] == 39.5
    assert b["commission_pct"] == 0.18
    assert b["fixed_fee"] == 6.0
    assert b["min_margin_pct"] == 0.20
    assert b["commission_value"] == 13.21
    assert b["net_profit"] == 14.68


def test_pricing_zero_cost(session, headers):
    r = session.post(f"{API}/pricing/calculate", headers=headers,
                     json={"cost": 0, "packaging": 0, "campaigns": 0}, timeout=15)
    assert r.status_code == 200
    assert r.json()["selling_price"] == 9.68


def test_pricing_default_optional_fields(session, headers):
    """packaging & campaigns default to 0 when omitted."""
    r = session.post(f"{API}/pricing/calculate", headers=headers,
                     json={"cost": 32.5}, timeout=15)
    assert r.status_code == 200
    j = r.json()
    # (32.5 + 6) / 0.62 = 62.0967
    assert j["selling_price"] == 62.10


def test_pricing_negative_cost_rejected(session, headers):
    r = session.post(f"{API}/pricing/calculate", headers=headers,
                     json={"cost": -5, "packaging": 2, "campaigns": 5}, timeout=15)
    assert r.status_code == 422


def test_pricing_negative_packaging_rejected(session, headers):
    r = session.post(f"{API}/pricing/calculate", headers=headers,
                     json={"cost": 10, "packaging": -1, "campaigns": 0}, timeout=15)
    assert r.status_code == 422


# -------- AI auth gating --------
def test_ai_auth_gated(session):
    r = session.post(f"{API}/ai/generate-title",
                     json={"product_code": "x", "raw_name": "x", "model": "claude"}, timeout=15)
    assert r.status_code == 401


# ============================================================
# Iteration 3: REAL JohnDrop integration
# /api/johndrop/connect, /disconnect, /catalog, /import-real
# ============================================================

JD_EMAIL = "totyshopvendas@gmail.com"
JD_PASSWORD = "1593572864To@@##"

EMAIL_JD = f"jd+{uuid.uuid4().hex[:6]}@blingdrop.com"


@pytest.fixture(scope="module")
def auth_jd(session):
    r = session.post(f"{API}/auth/register",
                     json={"email": EMAIL_JD, "password": PASSWORD, "name": NAME}, timeout=30)
    assert r.status_code == 200, r.text
    return {"token": r.json()["token"], "user_id": r.json()["user"]["user_id"]}


@pytest.fixture(scope="module")
def headers_jd(auth_jd):
    return {"Authorization": f"Bearer {auth_jd['token']}", "Content-Type": "application/json"}


# ---------- connect / disconnect ----------
def test_jd_catalog_before_connect_returns_400(session, headers_jd):
    r = session.get(f"{API}/johndrop/catalog?page=1", headers=headers_jd, timeout=30)
    assert r.status_code == 400
    assert "johndrop" in r.json()["detail"].lower() or "conecte" in r.json()["detail"].lower()


def test_jd_connect_wrong_password_401(session, headers_jd):
    r = session.post(f"{API}/johndrop/connect", headers=headers_jd,
                     json={"email": JD_EMAIL, "password": "wrong-password-xxx"}, timeout=60)
    # 401 = auth failed; 502 would indicate network (infra) problem
    if r.status_code == 502:
        pytest.skip(f"JohnDrop unreachable (infra): {r.text[:200]}")
    assert r.status_code == 401, r.text


def test_jd_connect_success(session, headers_jd):
    r = session.post(f"{API}/johndrop/connect", headers=headers_jd,
                     json={"email": JD_EMAIL, "password": JD_PASSWORD}, timeout=60)
    if r.status_code == 502:
        pytest.skip(f"JohnDrop unreachable (infra): {r.text[:200]}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["connected"] is True
    assert j["email"] == JD_EMAIL


def test_jd_integrations_status_has_email(session, headers_jd):
    r = session.get(f"{API}/integrations/status", headers=headers_jd, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["johndrop"]["connected"] is True
    assert j["johndrop"].get("email") == JD_EMAIL


def test_jd_credential_encrypted_in_db(auth_jd):
    """Verify password_enc is stored non-plaintext in db.johndrop_credentials."""
    from pymongo import MongoClient
    mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mc[os.environ.get("DB_NAME", "test_database")]
    doc = db.johndrop_credentials.find_one({"user_id": auth_jd["user_id"]})
    assert doc is not None, "Credential doc not found"
    assert doc["email"] == JD_EMAIL
    assert "password_enc" in doc
    assert doc["password_enc"] != JD_PASSWORD
    assert JD_PASSWORD not in doc["password_enc"]
    # Fernet tokens start with 'gAAAAA'
    assert doc["password_enc"].startswith("gAAAAA")


# ---------- catalog ----------
@pytest.fixture(scope="module")
def catalog_page1(session, headers_jd):
    r = session.get(f"{API}/johndrop/catalog?page=1", headers=headers_jd, timeout=60)
    if r.status_code == 502:
        pytest.skip(f"JohnDrop unreachable (infra): {r.text[:200]}")
    assert r.status_code == 200, r.text
    return r.json()


def test_jd_catalog_page1_shape(catalog_page1):
    d = catalog_page1
    assert len(d["items"]) == 40
    assert len(d["categories"]) == 31
    assert d["max_page"] >= 15
    assert d["current_page"] == 1


def test_jd_catalog_item_fields(catalog_page1):
    for it in catalog_page1["items"]:
        assert isinstance(it["jd_id"], str) and it["jd_id"].isdigit()
        assert isinstance(it["raw_title"], str) and len(it["raw_title"]) > 0
        assert isinstance(it["clean_title"], str)
        assert "product_code" in it
        assert it["image"] is None or it["image"].startswith("https://app.jonhdrop.com.br/")
        assert isinstance(it["price"], (int, float))
        assert isinstance(it["stock"], int)
        assert isinstance(it["already_imported"], bool)
        assert "seo_title_suggestion" in it
        seo = it["seo_title_suggestion"]
        assert len(seo) <= 60, f"SEO title too long ({len(seo)}): {seo}"
        if it["product_code"]:
            assert seo.endswith(it["product_code"]), f"SEO must end with product_code: {seo}"
        assert isinstance(it["price_suggestion"], (int, float))
        if it["price"] > 0:
            assert it["price_suggestion"] > it["price"], \
                f"price_suggestion {it['price_suggestion']} must be > price {it['price']}"


def test_jd_catalog_page2_different(session, headers_jd, catalog_page1):
    r = session.get(f"{API}/johndrop/catalog?page=2", headers=headers_jd, timeout=60)
    if r.status_code == 502:
        pytest.skip(f"JohnDrop unreachable (infra): {r.text[:200]}")
    assert r.status_code == 200, r.text
    d2 = r.json()
    assert d2["current_page"] == 2
    ids1 = {it["jd_id"] for it in catalog_page1["items"]}
    ids2 = {it["jd_id"] for it in d2["items"]}
    assert ids1 != ids2
    assert len(ids1 & ids2) < len(ids1)  # mostly different


# ---------- import-real ----------
@pytest.fixture(scope="module")
def imported_ids(session, headers_jd, catalog_page1):
    # Take 2 items that aren't already imported
    candidates = [it["jd_id"] for it in catalog_page1["items"] if not it["already_imported"]][:2]
    assert len(candidates) >= 1, "No un-imported candidates on page 1"
    r = session.post(f"{API}/johndrop/import-real", headers=headers_jd,
                     json={"jd_ids": candidates, "use_ai_description": False}, timeout=120)
    if r.status_code == 502:
        pytest.skip(f"JohnDrop unreachable (infra): {r.text[:200]}")
    assert r.status_code == 200, r.text
    return {"ids": candidates, "resp": r.json()}


def test_jd_import_real_creates_products(session, headers_jd, imported_ids):
    j = imported_ids["resp"]
    assert j["created"] == len(imported_ids["ids"])
    assert j["skipped"] == 0
    # Verify jd_id linkage via direct DB query (GET /products strips jd_id via response_model)
    from pymongo import MongoClient
    mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mc[os.environ.get("DB_NAME", "test_database")]
    for jid in imported_ids["ids"]:
        doc = db.products.find_one({"jd_id": jid})
        assert doc is not None, f"Product with jd_id={jid} not persisted"
        assert len(doc["title"]) <= 60
        assert doc["product_code"] and doc["product_code"] in doc["title"]
        assert doc["price"] > doc["cost"]  # blindada price > cost
        assert doc["sync_status"] in ("pending", "out_of_stock")
        # SKU format JD-<product_code>
        assert doc["sku"].startswith("JD-")


def test_jd_import_real_idempotent(session, headers_jd, imported_ids):
    r = session.post(f"{API}/johndrop/import-real", headers=headers_jd,
                     json={"jd_ids": imported_ids["ids"], "use_ai_description": False}, timeout=120)
    if r.status_code == 502:
        pytest.skip(f"JohnDrop unreachable: {r.text[:200]}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["created"] == 0
    assert j["skipped"] == len(imported_ids["ids"])


def test_jd_catalog_already_imported_flag(session, headers_jd, imported_ids):
    r = session.get(f"{API}/johndrop/catalog?page=1", headers=headers_jd, timeout=60)
    if r.status_code == 502:
        pytest.skip("JohnDrop unreachable")
    items = r.json()["items"]
    for jid in imported_ids["ids"]:
        hit = next((it for it in items if it["jd_id"] == jid), None)
        if hit is not None:
            assert hit["already_imported"] is True, f"{jid} should be already_imported"


def test_jd_import_real_empty_list_400(session, headers_jd):
    r = session.post(f"{API}/johndrop/import-real", headers=headers_jd,
                     json={"jd_ids": [], "use_ai_description": False}, timeout=30)
    assert r.status_code == 400


def test_jd_import_real_with_ai_description(session, headers_jd, catalog_page1):
    # Pick a fresh un-imported item
    candidates = [it["jd_id"] for it in catalog_page1["items"] if not it["already_imported"]]
    # skip ones already used by imported_ids fixture
    # Grab one that is *still* un-imported at the time of call
    r_cat = session.get(f"{API}/johndrop/catalog?page=1", headers=headers_jd, timeout=60)
    if r_cat.status_code == 502:
        pytest.skip("JohnDrop unreachable")
    fresh = [it["jd_id"] for it in r_cat.json()["items"] if not it["already_imported"]]
    if not fresh:
        pytest.skip("No fresh un-imported items left on page 1")
    target = [fresh[0]]
    r = session.post(f"{API}/johndrop/import-real", headers=headers_jd,
                     json={"jd_ids": target, "use_ai_description": True, "ai_model": "claude"},
                     timeout=180)
    if r.status_code == 502:
        pytest.skip("JohnDrop unreachable")
    assert r.status_code == 200, r.text
    j = r.json()
    if j["created"] == 0:
        pytest.skip("Product already imported in a parallel test")
    # Fetch the created product via DB (response_model strips jd_id)
    from pymongo import MongoClient
    mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mc[os.environ.get("DB_NAME", "test_database")]
    doc = db.products.find_one({"jd_id": target[0]})
    assert doc is not None
    assert isinstance(doc.get("description"), str)
    assert len(doc["description"]) >= 100, f"AI description too short ({len(doc['description'])}): {doc['description'][:120]}"


# ---------- disconnect ----------
def test_jd_disconnect_removes_credentials(session, headers_jd, auth_jd):
    r = session.post(f"{API}/johndrop/disconnect", headers=headers_jd, timeout=15)
    assert r.status_code == 200
    assert r.json()["disconnected"] is True
    # credential doc deleted
    from pymongo import MongoClient
    mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mc[os.environ.get("DB_NAME", "test_database")]
    assert db.johndrop_credentials.find_one({"user_id": auth_jd["user_id"]}) is None
    # catalog now fails with 400
    r2 = session.get(f"{API}/johndrop/catalog?page=1", headers=headers_jd, timeout=30)
    assert r2.status_code == 400


# ---------- apply_seo_format regression (via legacy /johndrop/import) ----------
def test_apply_seo_preserves_code_after_truncation(session):
    """Via unit-level import: raw '(KA-R128) ... Kapbom KA-R128' must end with ' KA-R128', max 60."""
    import sys
    sys.path.insert(0, "/app/backend")
    from server import apply_seo_format
    raw = "Pendrive 128GB Unidade Flash TIPO-C para USB 3.0 de Alta Velocidade Kapbom KA-R128"
    out = apply_seo_format(raw, brand="Kapbom", ean=None, product_code="KA-R128")
    assert len(out) <= 60, f"Length {len(out)}: {out!r}"
    assert out.endswith(" KA-R128"), f"Must end with ' KA-R128': {out!r}"
    # Brand removed
    assert "Kapbom" not in out
    # Code appears exactly once at the end
    assert out.count("KA-R128") == 1


def test_apply_seo_short_title_unchanged_except_code_suffix(session):
    import sys
    sys.path.insert(0, "/app/backend")
    from server import apply_seo_format
    out = apply_seo_format("Creme Facial Hidratante 50g", brand=None, ean=None, product_code="JD001")
    assert out.endswith(" JD001")
    assert len(out) <= 60
    assert "Creme Facial Hidratante" in out
