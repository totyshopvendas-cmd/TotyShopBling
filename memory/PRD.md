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
