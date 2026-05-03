import React, { useCallback, useEffect, useState } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, Sparkles, Search, Package, CheckCircle2, AlertTriangle } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function BlingCatalog() {
  const [page, setPage] = useState(1);
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [enriching, setEnriching] = useState(false);
  const [aiModel, setAiModel] = useState("claude");
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, c] = await Promise.all([
        api.get("/bling/products", { params: { page, limit: 100 } }),
        api.get("/bling/categories"),
      ]);
      setItems(p.data.items || []);
      setCategories(c.data.items || []);
      setSelected(new Set());
    } catch (err) {
      const msg = err?.response?.data?.detail || "Falha ao carregar Bling";
      toast.error(msg);
      if (err?.response?.status === 400) navigate("/integrations");
    } finally {
      setLoading(false);
    }
  }, [page, navigate]);

  useEffect(() => { load(); }, [load]);

  const filtered = items.filter((it) => {
    const q = query.toLowerCase();
    return !q || (it.nome || "").toLowerCase().includes(q) || (it.codigo || "").toLowerCase().includes(q);
  });

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    const incomplete = filtered.filter((it) => !it.already_enriched);
    const allSelected = incomplete.every((it) => selected.has(it.id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) incomplete.forEach((it) => next.delete(it.id));
      else incomplete.forEach((it) => next.add(it.id));
      return next;
    });
  };

  const enrichSelected = async () => {
    if (selected.size === 0) { toast.info("Selecione ao menos 1 produto"); return; }
    if (!window.confirm(`Enriquecer ${selected.size} produto(s) no Bling?\n\nA IA vai preencher:\n• Descrição completa (500-900 chars)\n• Descrição complementar (1 linha)\n• NCM\n• Categoria (cria se não existir)\n• Peso e dimensões\n\nTítulo, SKU e preço NÃO serão alterados.`)) return;
    setEnriching(true);
    try {
      const { data } = await api.post("/bling/enrich", {
        bling_product_ids: Array.from(selected),
        ai_model: aiModel,
        auto_create_categories: true,
      });
      toast.success(`${data.enriched} produto(s) enriquecido(s) no Bling!`);
      if (data.failed?.length) toast.warning(`${data.failed.length} falharam`);
      setSelected(new Set());
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Falha no enriquecimento");
    } finally {
      setEnriching(false);
    }
  };

  const money = (v) => v != null ? `R$ ${Number(v).toFixed(2).replace(".", ",")}` : "-";
  const hasDesc = (it) => !!(it.descricaoCurta || it.descricaoComplementar);
  const hasNcm = (it) => !!(it.tributacao?.ncm);
  const hasCat = (it) => !!(it.categoria?.id);

  return (
    <Layout>
      <PageHeader
        overline="// bling · enriquecimento ia"
        title="Catálogo Bling"
        description="IA analisa cada produto e preenche: descrição completa, NCM, categoria (cria se não existir), peso e dimensões. Título, SKU e preço permanecem intocados."
        actions={
          <>
            <select
              value={aiModel}
              onChange={(e) => setAiModel(e.target.value)}
              className="border border-[#E5E5E5] bg-white px-3 py-2 text-[10px] font-mono uppercase tracking-wider"
            >
              <option value="claude">Claude 4.5</option>
              <option value="gpt">GPT-5.2</option>
            </select>
            <button
              onClick={enrichSelected}
              disabled={enriching || selected.size === 0}
              data-testid="bling-enrich-button"
              className="bg-[#FF4500] hover:bg-[#cc3700] disabled:opacity-50 text-white px-4 py-2 text-xs font-mono uppercase tracking-wider flex items-center gap-2 transition-colors shadow-[2px_2px_0px_#0A0A0A]"
            >
              <Sparkles size={12} />
              {enriching ? "Enriquecendo..." : `Enriquecer ${selected.size || ""} com IA`}
            </button>
          </>
        }
      />

      <div className="p-8 space-y-4">
        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="border border-[#E5E5E5] p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500">total na página</div>
            <div className="font-heading text-2xl font-medium">{items.length}</div>
          </div>
          <div className="border border-[#E5E5E5] p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500">com categoria</div>
            <div className="font-heading text-2xl font-medium text-[#008A00]">{items.filter(hasCat).length}</div>
          </div>
          <div className="border border-[#E5E5E5] p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500">com NCM</div>
            <div className="font-heading text-2xl font-medium text-[#008A00]">{items.filter(hasNcm).length}</div>
          </div>
          <div className="border border-[#E5E5E5] p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500">categorias existentes</div>
            <div className="font-heading text-2xl font-medium">{categories.length}</div>
          </div>
        </div>

        {/* Search + select-all */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por nome ou código..."
              data-testid="bling-search"
              className="w-full bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none pl-9 pr-3 py-2 text-sm"
            />
          </div>
          <label className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-neutral-600 cursor-pointer">
            <input
              type="checkbox"
              onChange={toggleAll}
              checked={filtered.filter((it) => !it.already_enriched).every((it) => selected.has(it.id)) && filtered.some((it) => !it.already_enriched)}
              className="accent-[#002FA7] w-4 h-4"
              data-testid="bling-select-all"
            />
            Selecionar incompletos
          </label>
          <div className="ml-auto font-mono text-[10px] uppercase tracking-wider text-neutral-500">
            {selected.size} sel · página {page}
          </div>
        </div>

        {loading ? (
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">carregando do bling<span className="ai-cursor"/></div>
        ) : filtered.length === 0 ? (
          <div className="border border-[#E5E5E5] p-16 text-center">
            <Package size={24} className="mx-auto text-neutral-300 mb-3" />
            <p className="text-sm text-neutral-600">Nenhum produto no Bling. Primeiro cadastre produtos via Catálogo JohnDrop — eles aparecem aqui depois de ~5 min.</p>
          </div>
        ) : (
          <div className="border border-[#E5E5E5]" data-testid="bling-table">
            <table className="w-full text-sm">
              <thead className="border-b border-[#E5E5E5]">
                <tr>
                  <th className="w-10 py-3 px-3"></th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Código</th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Produto · Preço</th>
                  <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Desc</th>
                  <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">NCM</th>
                  <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Categoria</th>
                  <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Peso</th>
                  <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">IA</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((it) => {
                  const isSel = selected.has(it.id);
                  return (
                    <tr key={it.id} className={`border-b border-[#E5E5E5] transition-colors ${isSel ? "bg-[#F0F4FF]" : "hover:bg-[#F7F7F7]"}`}>
                      <td className="py-3 px-3">
                        <input type="checkbox" checked={isSel} onChange={() => toggle(it.id)} disabled={it.already_enriched} className="accent-[#002FA7] w-4 h-4" data-testid={`bling-select-${it.id}`} />
                      </td>
                      <td className="py-3 px-4 font-mono text-xs">{it.codigo}</td>
                      <td className="py-3 px-4 max-w-md">
                        <div className="truncate">{it.nome}</div>
                        <div className="font-mono text-[10px] text-neutral-500">{money(it.preco)}</div>
                      </td>
                      <td className="py-3 px-4 text-center">
                        {hasDesc(it) ? <CheckCircle2 size={14} className="inline text-[#008A00]" /> : <AlertTriangle size={14} className="inline text-[#FFB800]" />}
                      </td>
                      <td className="py-3 px-4 text-center font-mono text-[10px]">
                        {hasNcm(it) ? <span className="text-[#008A00]">{it.tributacao.ncm}</span> : <AlertTriangle size={14} className="inline text-[#FFB800]" />}
                      </td>
                      <td className="py-3 px-4 text-center font-mono text-[10px]">
                        {hasCat(it) ? <span className="text-[#008A00]">✓</span> : <AlertTriangle size={14} className="inline text-[#FFB800]" />}
                      </td>
                      <td className="py-3 px-4 text-center font-mono text-[10px]">
                        {(it.pesoLiquido || it.pesoBruto) ? <span className="text-[#008A00]">{it.pesoLiquido || it.pesoBruto}kg</span> : <AlertTriangle size={14} className="inline text-[#FFB800]" />}
                      </td>
                      <td className="py-3 px-4 text-center">
                        {it.already_enriched && <span className="inline-flex items-center gap-1 text-[10px] font-mono text-[#FF4500]"><Sparkles size={10}/> IA</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-center gap-2 pt-2">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="border border-[#E5E5E5] hover:border-[#0A0A0A] disabled:opacity-40 px-3 py-1.5 text-xs font-mono uppercase tracking-wider flex items-center gap-1">
            <ChevronLeft size={12} /> Anterior
          </button>
          <div className="font-mono text-xs px-4">Página {page}</div>
          <button onClick={() => setPage((p) => p + 1)} disabled={items.length < 100} className="border border-[#E5E5E5] hover:border-[#0A0A0A] disabled:opacity-40 px-3 py-1.5 text-xs font-mono uppercase tracking-wider flex items-center gap-1">
            Próxima <ChevronRight size={12} />
          </button>
        </div>
      </div>
    </Layout>
  );
}
