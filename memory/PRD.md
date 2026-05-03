# BlingDrop - Product Management Dashboard

## Original Problem Statement (Portuguese BR)
User requested a system integrating **Bling (ERP)** with **JohnDrop (dropshipping supplier)** for Brazilian e-commerce:
1. **Bling & JohnDrop Integration**: JohnDrop ships directly to end customer; Bling centralizes management. Stock sync via Make.com + Discord alerts. Handle token expiration errors.
2. **Product SEO Rules**: Titles max 60 chars (no brand, no EAN, MUST include product code), 6 Amazon-style bullet points with icons, high-quality white/transparent background images.
3. **Marketplace Customization**: Amazon (unique SKU, 6 bullets, category mapping), Shopee (variation color/size, weight & dimensions for Shopee Xpress, category taxonomy), Kwai Shop (category-specific technical fields like voltage).

## User Choices
- Main objective: **Management/monitoring panel** (no real API integration yet)
- Integration scope: JohnDrop → Bling only (mock for now)
- AI: **Claude Sonnet 4.5 + GPT-5.2** (runtime toggle, via Emergent LLM Key)
- Auth: **Both Google Login (Emergent) + JWT email/password**
- Design: **Light theme** (delivered as Swiss/Neo-Brutalist Utility aesthetic, #002FA7 Klein Blue primary)

## Architecture
- **Backend**: FastAPI + MongoDB (Motor) - single `server.py` with `/api` prefix
- **Frontend**: React 19 + React Router 7 + Tailwind + shadcn/ui + Sonner toasts + lucide-react icons
- **Fonts**: Work Sans (headings), IBM Plex Sans (body), JetBrains Mono (technical data)
- **AI**: emergentintegrations library with Claude Sonnet 4.5 and GPT-5.2 via EMERGENT_LLM_KEY

## What's Implemented (Feb 23, 2026 - MVP)
### Backend
- Auth: `/api/auth/register`, `/login`, `/me`, `/logout`, `/session` (Emergent Google callback)
- Products: full CRUD + `/seed` (3 mock JohnDrop products) + `/{id}/sync` (validator)
- Sync validation rules: title > 60 chars → error, Amazon needs 6 bullets, Shopee needs weight_kg, stock_johndrop ≤ 0 → out_of_stock
- Dashboard stats: totals, marketplace coverage, stock divergences JohnDrop vs Bling
- Integrations: toggle Bling/JohnDrop/Make/Discord (mock connection state + tokens)
- AI endpoints: `/ai/generate-title`, `/ai/generate-bullets` (exactly 6), `/ai/generate-description`

### Frontend
- Login page (split layout, Google + JWT, grayscale image)
- AuthCallback page (processes `#session_id=` from Emergent OAuth)
- Dashboard (5 stat cards, marketplace coverage bars, stock divergence table)
- Products (search, sync status table, channel indicators, per-product sync/edit)
- Product Editor (4 tabs: Geral, Amazon, Shopee, Kwai), strict 60-char SEO title counter, brand/EAN detection warnings, AI model toggle (Claude/GPT), AI generate buttons (title/6 bullets/description), image URL manager
- Integrations page (4 service cards with connect/disconnect toggle)

### Testing
- 23/23 backend tests pass (auth, CRUD, sync validation, dashboard, integrations, AI real calls)

## Iteration 2 (Feb 23, 2026)
### Added
- **Auto-import JohnDrop → Meus Produtos** (`POST /api/johndrop/import`): guarded by integration status, imports 8-product mock catalog, applies `apply_seo_format()` helper (strip brand, strip EAN, append product_code, truncate 60 chars). Idempotent via SKU check.
- **Calculadora Blindada** (`POST /api/pricing/calculate`): fixed 18% commission, R$6 fee, 20% margin (matches calcblindada-krrwemcx.manus.space). Formula: `P = (cost+packaging+campaigns+6) / 0.62`.
- Frontend: standalone `/pricing` page + "Calculadora" sidebar nav + pricing widget inside ProductEditor Geral tab with "Aplicar como preço de venda" button.
- Integrations page: "Importar catálogo → Meus Produtos" button appears when JohnDrop is connected.
- SEED_PRODUCTS expanded from 3 to 8 (skincare, eletrônicos, casa, pet, fitness, iluminação, beleza, escritório), with intentionally "raw" titles (brand + EAN) to demo the SEO auto-format on import.

### Testing iteration 2
- 36/36 backend tests pass. Zero critical or minor issues.

## Iteration 3 (Feb 23, 2026) - REAL JohnDrop Integration
### Added
- **Session-based scraper** for JohnDrop (no public REST API exists). New module `/app/backend/johndrop_client.py` does Laravel CSRF login and parses HTML catalog pages with regex.
- **Encrypted credential storage**: passwords encrypted with Fernet (key derived from JWT_SECRET via SHA-256), stored in `johndrop_credentials` collection.
- **New endpoints**:
  - `POST /api/johndrop/connect` - tests login + saves encrypted credentials
  - `POST /api/johndrop/disconnect` - removes credentials
  - `GET /api/johndrop/catalog?page=N&category_id=&name=&integration_filter=without_integration` - returns real products with SEO title suggestion + price_suggestion + already_imported flag
  - `POST /api/johndrop/import-real` - imports selected products by jd_id with SEO format + calculated price + optional AI description
- **Frontend**:
  - New page `/johndrop-catalog` lists real products (paginated 17 pages × 40 items), shows raw vs SEO title, calculated blindada price, margin %, image, stock. Multi-select + bulk import.
  - Integrations page now has real JohnDrop login form (email + password) instead of fake toggle. Encrypted credentials shown as connected status.
  - "Catálogo JohnDrop" link in sidebar.
- **apply_seo_format fix**: now always strips product_code and re-appends at end so 60-char truncation preserves the code.
- **Product model**: added optional `jd_id` field exposed in API response for traceability.
- **Error hardening**: `decrypt_secret` failure → 401 (not 500); narrowed `connect` exception catch to `httpx.HTTPError`.

### Testing iteration 3
- 52/52 backend tests pass against live `https://app.jonhdrop.com.br`. Real catalog: 17 páginas, ~680 produtos, 31 categorias.

## Iteration 4 (Feb 23, 2026) - Push-back to JohnDrop + UX Reorg
### Added
- **POST /api/johndrop/push/{product_id}** - Aplica o produto atualizado (título SEO + descrição + preço) DIRETAMENTE no painel da JohnDrop via `POST /dashboard/product/storev2/{jd_id}`. Preserva todos os 28 campos do formulário (SKU, EAN, marca, categoria, NCM, dimensões, 5 canais de integração TotyShop-Bling) — só sobrescreve `name`, `description`, `sale_value`. A JohnDrop então repassa automaticamente ao Bling via ToyShop-Bling.
- `JohnDropClient.fetch_product_form(jd_id)` + `push_product(jd_id, patch)` — mirror form + patch overrides.
- **Frontend**: Botão laranja "Aplicar na JohnDrop → Bling" no ProductEditor (aparece só se jd_id existir) com confirmação antes do push.
- **UX Reorganização de navegação**: espelha o fluxo real da JohnDrop:
  - Sidebar "Produtos" → agora aponta para catálogo JohnDrop (sem cadastro)
  - Sidebar "Meus Produtos" → novo nome para produtos importados
- **Error hardening**: jd_id exposto no Product model; decrypt_secret falha → 401; httpx.HTTPError específico.

### Fluxo completo (agora end-to-end)
1. Conectar JohnDrop em Integrações (email+senha) — credenciais criptografadas Fernet
2. "Produtos" → ver 680 produtos sem cadastro, filtrar, selecionar lote
3. "Importar selecionados" → aparece em Meus Produtos com SEO + preço blindado
4. Abrir produto em Meus Produtos → ajustar se quiser, gerar descrição IA
5. Botão "Aplicar na JohnDrop → Bling" → POST direto pro painel da JohnDrop → ToyShop-Bling empurra pro Bling automaticamente

## Iteration 5 (Feb 23, 2026) - Calculadora 100% fiel à original
### Fixed
- **Fórmula exata espelhada** de https://calcblindada-krrwemcx.manus.space/ (código-fonte JS extraído e decifrado):
  - Processamento fixo: **R$ 1,00** adicionado ao custo (antes era zero)
  - Markup escalonado: **cost ≤ 20 → 2.6x | 20 < cost ≤ 50 → 2.1x | cost > 50 → 1.8x**
  - Preço final = **max(custoTotal × markup, totalDespesas / 0.62)**
  - **Alerta de segurança** quando markup não cobre a versão blindada
- Caso de teste validado: custo R$ 32,50 → R$ 70,35 (markup 2,1x, lucro R$ 18,19 = 25,9% margem) ✓
- UI atualizada: exibe markup badge, lucro real com %, preço blindado comparativo, alerta amarelo, resumo de despesas detalhado + tabela de regras fixas + tabela de markup escalonado
- **Bug fix frontend**: ProductEditor.jsx tinha lixo de código duplicado no fim causando erro de sintaxe no webpack

## Prioritized Backlog
### P0 (post-MVP, for next phase)
- Real Bling API OAuth integration (token management, auto-refresh)
- Real JohnDrop API (or webhook/scraper) for live stock
- Make.com webhook receiver for real-time stock sync
- Discord webhook firing for stock variations and token errors

### P1
- Bulk CSV import/export of products
- Per-marketplace export preview (visual mockup of final listing)
- Historical sync log per product
- Image upload with object storage (replace URL paste flow)
- Rate limiting on /api/ai/* endpoints

### P2
- AI keyword research (competitor SEO scraping)
- Price suggestion based on margin + competitor data
- Sales reports per marketplace
- Multi-user / team roles
- i18n beyond pt-BR

## Next Action Items
- User to review UI/UX and confirm the marketplace field coverage matches their Bling workflow
- Gather real Bling API credentials if/when user wants to plug real integration
- Consider adding CSV bulk import as highest-value next feature
