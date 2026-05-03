import React, { useEffect, useState, useCallback } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, Download, Sparkles, Search, CheckCircle2, Package } from "lucide-react";
import { useNavigate } from "react-router-dom";

const pct = (a, b) => (b > 0 ? ((a / b) * 100).toFixed(1) : "0");

export default function JohnDropCatalog() {
  const [page, setPage] = useState(1);
  const [maxPage, setMaxPage] = useState(1);
  const [categoryId, setCategoryId] = useState("");
  const [nameFilter, setNameFilter] = useState("");
  const [categories, setCategories] = useState([]);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(new Set());
  const [importing, setImporting] = useState(false);
  const [useAiDesc, setUseAiDesc] = useState(false);
  const [aiModel, setAiModel] = useState("claude");
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/johndrop/catalog", {
        params: {
          page,
          category_id: categoryId,
          name: nameFilter,
          integration_filter: "without_integration",
        },
      });
      setItems(data.items);
      setMaxPage(data.max_page);
      setCategories(data.categories);
      setSelected(new Set());
    } catch (err) {
      const msg = err?.response?.data?.detail || "Falha ao buscar catálogo";
      toast.error(msg);
      if (err?.response?.status === 400) navigate("/integrations");
    } finally {
      setLoading(false);
    }
  }, [page, categoryId, nameFilter, navigate]);

  useEffect(() => { load(); }, [load]);

  const toggle = (jd_id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(jd_id) ? next.delete(jd_id) : next.add(jd_id);
      return next;
    });
  };

  const toggleAllOnPage = () => {
    const selectable = items.filter((i) => !i.already_imported).map((i) => i.jd_id);
    const allSelected = selectable.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) selectable.forEach((id) => next.delete(id));
      else selectable.forEach((id) => next.add(id));
      return next;
    });
  };

  const importSelected = async () => {
    if (selected.size === 0) {
      toast.info("Selecione pelo menos 1 produto");
      return;
    }
    if (!window.confirm(`Cadastrar ${selected.size} produto(s) direto na JohnDrop?\n\nCada produto vai receber: título SEO (60 chars) + preço blindado (,00/,50) + ${useAiDesc ? "descrição IA" : "descrição da JohnDrop"}.\n\nApós o cadastro, eles aparecem em 'Meus produtos' da JohnDrop (já integrados ao Bling via TotyShop).`)) return;
    setImporting(true);
    try {
      const { data } = await api.post("/johndrop/register-direct", {
        jd_ids: Array.from(selected),
        use_ai_description: useAiDesc,
        ai_model: aiModel,
      });
      toast.success(`${data.registered} cadastrado(s)! Aguarde até 5 min para efetivar a transação no Bling via TotyShop.`);
      if (data.failed?.length) toast.warning(`${data.failed.length} falharam - verifique o histórico`);
      setSelected(new Set());
      await load();  // refresh - cadastrados somem do catálogo (filter=without_integration)
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Falha no cadastro");
    } finally {
      setImporting(false);
    }
  };

  const registerOne = async (jd_id) => {
    if (!window.confirm("Cadastrar este produto direto na JohnDrop com SEO + preço blindado aplicados?")) return;
    try {
      const { data } = await api.post("/johndrop/register-direct", {
        jd_ids: [jd_id],
        use_ai_description: useAiDesc,
        ai_model: aiModel,
      });
      if (data.registered > 0) {
        toast.success(`Cadastrado! ${data.successes[0].price_sale ? `Preço: R$ ${data.successes[0].price_sale.toFixed(2).replace(".",",")} · ` : ""}Aguarde até 5 min para o produto aparecer no Bling (TotyShop repassando).`);
        await load();
      } else {
        toast.error(data.failed[0]?.reason || "Falhou");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Falha");
    }
  };

  const money = (v) => `R$ ${Number(v).toFixed(2).replace(".", ",")}`;

  return (
    <Layout>
      <PageHeader
        overline="// produtos · não cadastrados"
        title="Produtos da JohnDrop"
        description="Seguindo o fluxo da JohnDrop: Publicar Catálogo → Todos que eu não cadastrei. Título SEO, código e preço blindado já pré-calculados."
        actions={
          <button
            onClick={importSelected}
            disabled={importing || selected.size === 0}
            data-testid="import-selected-button"
            className="bg-[#002FA7] hover:bg-[#00227A] disabled:opacity-50 text-white px-4 py-2 text-xs font-mono uppercase tracking-wider flex items-center gap-2 transition-colors"
          >
            <Download size={12} />
            {importing ? "Cadastrando na JohnDrop..." : `Cadastrar ${selected.size} na JohnDrop`}
          </button>
        }
      />

      <div className="p-8 space-y-5">
        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[220px] max-w-sm">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
            <input
              type="text"
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (setPage(1), load())}
              placeholder="Buscar produto..."
              data-testid="jd-search-input"
              className="w-full bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none pl-9 pr-3 py-2 text-sm"
            />
          </div>
          <select
            value={categoryId}
            onChange={(e) => { setCategoryId(e.target.value); setPage(1); }}
            data-testid="jd-category-select"
            className="bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none px-3 py-2 text-sm min-w-[220px]"
          >
            <option value="">Todas categorias</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.count})</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-neutral-600 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={useAiDesc}
              onChange={(e) => setUseAiDesc(e.target.checked)}
              className="accent-[#FF4500] w-4 h-4"
              data-testid="use-ai-desc-toggle"
            />
            <Sparkles size={12} className="text-[#FF4500]" />
            Descrição IA
          </label>
          {useAiDesc && (
            <div className="flex gap-1">
              {[
                { k: "claude", label: "Claude" },
                { k: "gpt", label: "GPT-5.2" },
              ].map((m) => (
                <button
                  key={m.k}
                  onClick={() => setAiModel(m.k)}
                  data-testid={`jd-ai-${m.k}`}
                  className={`px-2 py-1 text-[10px] font-mono uppercase tracking-wider border transition-colors ${aiModel === m.k ? "bg-[#0A0A0A] text-white border-[#0A0A0A]" : "border-[#E5E5E5] hover:border-[#0A0A0A]"}`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          )}
          <div className="ml-auto font-mono text-[10px] uppercase tracking-wider text-neutral-500">
            página {page} / {maxPage} · {items.length} itens
          </div>
        </div>

        {loading ? (
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">carregando da jonhdrop<span className="ai-cursor" /></div>
        ) : items.length === 0 ? (
          <div className="border border-[#E5E5E5] p-16 text-center">
            <Package size={24} className="mx-auto text-neutral-300 mb-3" />
            <p className="text-sm text-neutral-600">Nenhum produto encontrado com esses filtros.</p>
          </div>
        ) : (
          <>
            {/* Select-all header */}
            <div className="flex items-center justify-between border border-[#E5E5E5] bg-[#F7F7F7] px-4 py-2">
              <label className="flex items-center gap-2 cursor-pointer text-xs font-mono uppercase tracking-wider text-neutral-700">
                <input
                  type="checkbox"
                  onChange={toggleAllOnPage}
                  checked={items.filter((i) => !i.already_imported).every((i) => selected.has(i.jd_id)) && items.some((i) => !i.already_imported)}
                  className="accent-[#002FA7] w-4 h-4"
                  data-testid="select-all-page"
                />
                Selecionar todos da página
              </label>
              <div className="font-mono text-[10px] text-neutral-500">
                {selected.size} selecionado{selected.size === 1 ? "" : "s"} no total
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3" data-testid="jd-catalog-grid">
              {items.map((it) => {
                const isSel = selected.has(it.jd_id);
                const disabled = it.already_imported;
                return (
                  <div
                    key={it.jd_id}
                    onClick={() => !disabled && toggle(it.jd_id)}
                    data-testid={`jd-item-${it.jd_id}`}
                    className={`border p-4 cursor-pointer transition-all ${
                      disabled
                        ? "border-[#E5E5E5] bg-[#FAFAFA] opacity-60 cursor-not-allowed"
                        : isSel
                        ? "border-[#002FA7] bg-[#F0F4FF] shadow-[2px_2px_0px_#002FA7]"
                        : "border-[#E5E5E5] hover:border-[#0A0A0A]"
                    }`}
                  >
                    <div className="flex gap-4">
                      <div className="relative shrink-0">
                        <div className="w-24 h-24 bg-white border border-[#E5E5E5] overflow-hidden">
                          {it.image && <img src={it.image} alt="" className="w-full h-full object-contain" />}
                        </div>
                        {disabled && (
                          <div className="absolute -top-1 -right-1 bg-[#008A00] text-white p-1">
                            <CheckCircle2 size={10} />
                          </div>
                        )}
                      </div>
                      <div className="flex-1 min-w-0 space-y-1.5">
                        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider">
                          <span className="text-neutral-500">#{it.jd_id}</span>
                          {it.product_code && <span className="text-[#002FA7]">{it.product_code}</span>}
                          <span className="text-neutral-400">estoque {it.stock}</span>
                          {disabled && <span className="text-[#008A00]">✓ já em meus produtos</span>}
                        </div>
                        <div className="text-[11px] text-neutral-400 line-through truncate">
                          {it.raw_title}
                        </div>
                        <div className="text-sm font-medium truncate" data-testid={`jd-seo-title-${it.jd_id}`}>
                          {it.seo_title_suggestion}
                          <span className="ml-2 font-mono text-[10px] text-neutral-400">
                            {it.seo_title_suggestion.length}/60
                          </span>
                        </div>
                        <div className="flex items-center gap-4 pt-1">
                          <div>
                            <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">custo jd</span>
                            <div className="font-mono text-xs">{money(it.price)}</div>
                          </div>
                          <div>
                            <span className="font-mono text-[10px] uppercase tracking-wider text-[#002FA7]">preço blindado</span>
                            <div className="font-mono text-xs text-[#002FA7] font-bold">{money(it.price_suggestion)}</div>
                          </div>
                          <div>
                            <span className="font-mono text-[10px] uppercase tracking-wider text-[#008A00]">margem</span>
                            <div className="font-mono text-xs text-[#008A00]">
                              {pct(it.price_suggestion - it.price - 7 - it.price_suggestion * 0.18, it.price_suggestion)}%
                            </div>
                          </div>
                          {!disabled && (
                            <button
                              onClick={(e) => { e.stopPropagation(); registerOne(it.jd_id); }}
                              data-testid={`register-one-${it.jd_id}`}
                              className="ml-auto bg-[#FF4500] hover:bg-[#cc3700] text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors shadow-[2px_2px_0px_#0A0A0A] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px]"
                            >
                              + Cadastrar
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-center gap-2 pt-4">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                data-testid="jd-prev-page"
                className="border border-[#E5E5E5] hover:border-[#0A0A0A] disabled:opacity-40 px-3 py-1.5 text-xs font-mono uppercase tracking-wider flex items-center gap-1"
              >
                <ChevronLeft size={12} /> Anterior
              </button>
              <div className="font-mono text-xs px-4">{page} / {maxPage}</div>
              <button
                onClick={() => setPage((p) => Math.min(maxPage, p + 1))}
                disabled={page >= maxPage}
                data-testid="jd-next-page"
                className="border border-[#E5E5E5] hover:border-[#0A0A0A] disabled:opacity-40 px-3 py-1.5 text-xs font-mono uppercase tracking-wider flex items-center gap-1"
              >
                Próxima <ChevronRight size={12} />
              </button>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
