import React, { useEffect, useState, useMemo } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Plus, Search, Sparkles, Trash2, Send, DollarSign, FileText, Zap, Shield } from "lucide-react";
import { toast } from "sonner";

const STATUS_CONFIG = {
  synced: { label: "Sincronizado", color: "#008A00" },
  pending: { label: "Pendente", color: "#FFB800" },
  error: { label: "Erro", color: "#E60000" },
  out_of_stock: { label: "Sem estoque", color: "#525252" },
};

function healthScore(p) {
  let s = 0;
  if (p.title && p.title.length <= 60) s += 25;
  if (p.product_code) s += 10;
  const desc = p.description || "";
  if (desc.length >= 200) s += 25;
  else if (desc.length >= 50) s += 10;
  if ((p.price || 0) > 0) s += 20;
  if ((p.stock_johndrop || 0) > 0) s += 10;
  if (p.images && p.images.length > 0) s += 10;
  return s;
}

const HealthBar = ({ score }) => {
  const color = score >= 90 ? "#008A00" : score >= 50 ? "#FFB800" : "#E60000";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-[#EBEBEB] relative">
        <div className="absolute inset-y-0 left-0 transition-all" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="font-mono text-[10px] tabular-nums" style={{ color }}>{score}%</span>
    </div>
  );
};

export default function Products() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [syncingId, setSyncingId] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [aiModel, setAiModel] = useState("claude");
  const [bulkRunning, setBulkRunning] = useState(null);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/products");
      setProducts(data);
    } catch (_e) {
      toast.error("Falha ao carregar produtos");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    return products.filter((p) => {
      const q = query.toLowerCase();
      return !q || p.title.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || (p.product_code || "").toLowerCase().includes(q);
    });
  }, [products, query]);

  const healthCounts = useMemo(() => {
    const c = { ready: 0, warning: 0, blocked: 0 };
    for (const p of products) {
      const s = healthScore(p);
      if (s >= 90) c.ready++;
      else if (s >= 50) c.warning++;
      else c.blocked++;
    }
    return c;
  }, [products]);

  const toggleSel = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === filtered.length) setSelected(new Set());
    else setSelected(new Set(filtered.map((p) => p.id)));
  };

  const selectReady = () => {
    const ids = products.filter((p) => healthScore(p) >= 90).map((p) => p.id);
    setSelected(new Set(ids));
    toast.success(`${ids.length} produtos 100% prontos selecionados`);
  };

  const syncOne = async (id) => {
    setSyncingId(id);
    try {
      const { data } = await api.post(`/products/${id}/sync`);
      setProducts((p) => p.map((x) => (x.id === id ? data : x)));
      if (data.sync_status === "synced") toast.success("Sincronizado");
      else if (data.sync_status === "error") toast.error(data.sync_message || "Erro");
      else toast.info(data.sync_message || "Pendente");
    } catch (_e) { toast.error("Falha"); }
    finally { setSyncingId(null); }
  };

  const bulkAction = async (action) => {
    if (selected.size === 0) { toast.error("Selecione ao menos 1 produto"); return; }
    const ids = Array.from(selected);
    setBulkRunning(action);
    try {
      if (action === "delete") {
        if (!window.confirm(`Apagar ${ids.length} produto(s)?`)) { setBulkRunning(null); return; }
        const { data } = await api.post("/products/bulk/delete", { product_ids: ids });
        toast.success(`${data.deleted} apagados`);
      } else if (action === "improve-titles") {
        toast.info(`Melhorando ${ids.length} títulos com IA...`);
        const { data } = await api.post("/products/bulk/improve-titles", { product_ids: ids, ai_model: aiModel });
        toast.success(`${data.updated} títulos melhorados${data.errors?.length ? ` (${data.errors.length} erros)` : ""}`);
      } else if (action === "generate-descriptions") {
        toast.info(`Gerando descrições para ${ids.length} produtos...`);
        const { data } = await api.post("/products/bulk/generate-descriptions", { product_ids: ids, ai_model: aiModel });
        toast.success(`${data.updated} descrições geradas`);
      } else if (action === "recalc-prices") {
        const { data } = await api.post("/products/bulk/recalculate-prices", { product_ids: ids });
        toast.success(`${data.updated} preços recalculados (arredondados ,00/,50)`);
      } else if (action === "push") {
        if (!window.confirm(`Aplicar ${ids.length} produto(s) na JohnDrop → Bling?\n\nIsso vai atualizar cada produto no seu painel da JohnDrop via TotyShop-Bling.`)) { setBulkRunning(null); return; }
        toast.info(`Aplicando ${ids.length} produtos na JohnDrop...`);
        const { data } = await api.post("/products/bulk/push-johndrop", { product_ids: ids });
        toast.success(`${data.pushed} aplicados na JohnDrop${data.failed?.length ? ` (${data.failed.length} falharam)` : ""}`);
      }
      setSelected(new Set());
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Falha na operação");
    } finally {
      setBulkRunning(null);
    }
  };

  const despacharTudoPronto = async () => {
    const readyIds = products.filter((p) => healthScore(p) >= 90 && p.jd_id).map((p) => p.id);
    if (readyIds.length === 0) { toast.error("Nenhum produto 100% pronto vinculado à JohnDrop"); return; }
    if (!window.confirm(`🚀 Despachar ${readyIds.length} produto(s) 100% prontos para a JohnDrop → Bling?`)) return;
    setBulkRunning("despachar");
    try {
      const { data } = await api.post("/products/bulk/push-johndrop", { product_ids: readyIds });
      toast.success(`🚀 ${data.pushed} despachados para o Bling via TotyShop!`);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Falha");
    } finally {
      setBulkRunning(null);
    }
  };

  const createNew = async () => {
    try {
      const { data } = await api.post("/products", {
        sku: `SKU-${Date.now()}`,
        title: "Novo produto",
        product_code: `PROD${Date.now()}`,
        price: 0, cost: 0, stock_johndrop: 0, stock_bling: 0, images: [],
      });
      navigate(`/products/${data.id}/edit`);
    } catch (_e) { toast.error("Falha"); }
  };

  const allSelectedOnPage = filtered.length > 0 && filtered.every((p) => selected.has(p.id));

  return (
    <Layout>
      <PageHeader
        overline="// meus produtos · linha de produção"
        title="Meus Produtos"
        description="Selecione em massa e despache. Automação inteligente: IA melhora títulos, gera descrições, recalcula preços e aplica tudo na JohnDrop → Bling em lote."
        actions={
          <>
            <button
              onClick={despacharTudoPronto}
              disabled={bulkRunning === "despachar" || healthCounts.ready === 0}
              data-testid="despachar-tudo-button"
              className="bg-[#FF4500] hover:bg-[#cc3700] disabled:opacity-50 text-white px-4 py-2 text-xs font-mono uppercase tracking-wider flex items-center gap-2 transition-colors shadow-[2px_2px_0px_#0A0A0A]"
            >
              <Zap size={12} />
              {bulkRunning === "despachar" ? "Despachando..." : `Despachar ${healthCounts.ready} Prontos`}
            </button>
            <button
              onClick={createNew}
              data-testid="new-product-button"
              className="border border-[#E5E5E5] hover:border-[#0A0A0A] px-3 py-2 text-xs font-mono uppercase tracking-wider flex items-center gap-1 transition-colors"
            >
              <Plus size={12} /> Novo
            </button>
          </>
        }
      />

      <div className="p-8 space-y-4">
        {/* Health summary */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[
            { label: "100% prontos", count: healthCounts.ready, color: "#008A00", icon: Shield },
            { label: "Precisam atenção", count: healthCounts.warning, color: "#FFB800", icon: Sparkles },
            { label: "Incompletos", count: healthCounts.blocked, color: "#E60000", icon: FileText },
          ].map((s) => (
            <div key={s.label} className="border border-[#E5E5E5] p-4 flex items-center justify-between">
              <div>
                <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500">{s.label}</div>
                <div className="font-heading text-3xl tracking-tighter font-medium" style={{ color: s.color }}>{s.count}</div>
              </div>
              <s.icon size={20} style={{ color: s.color }} />
            </div>
          ))}
        </div>

        {/* Search + controls */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por SKU, código ou título..."
              data-testid="product-search-input"
              className="w-full bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none pl-9 pr-3 py-2 text-sm"
            />
          </div>
          <button
            onClick={selectReady}
            className="border border-[#E5E5E5] hover:border-[#008A00] hover:text-[#008A00] px-3 py-2 text-[10px] font-mono uppercase tracking-wider"
          >
            Selecionar 100% prontos
          </button>
          <div className="ml-auto font-mono text-[10px] uppercase tracking-wider text-neutral-500">
            {filtered.length} / {products.length}
          </div>
        </div>

        {/* Bulk action bar */}
        {selected.size > 0 && (
          <div className="sticky top-2 z-10 border-2 border-[#002FA7] bg-[#002FA7] text-white p-3 flex flex-wrap items-center gap-2 shadow-[4px_4px_0px_#0A0A0A]" data-testid="bulk-action-bar">
            <span className="font-mono text-xs uppercase tracking-wider">{selected.size} selecionado{selected.size === 1 ? "" : "s"}</span>
            <span className="font-mono text-[10px] opacity-75">IA:</span>
            <select value={aiModel} onChange={(e) => setAiModel(e.target.value)} className="bg-[#00227A] text-white text-[10px] font-mono px-2 py-1 focus:outline-none">
              <option value="claude">Claude 4.5</option>
              <option value="gpt">GPT-5.2</option>
            </select>
            <div className="flex flex-wrap gap-1.5 ml-auto">
              <button onClick={() => bulkAction("improve-titles")} disabled={bulkRunning} data-testid="bulk-improve-titles" className="bg-white text-[#002FA7] hover:bg-[#FF4500] hover:text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider flex items-center gap-1 disabled:opacity-50">
                <Sparkles size={10} /> Melhorar títulos
              </button>
              <button onClick={() => bulkAction("generate-descriptions")} disabled={bulkRunning} data-testid="bulk-generate-descriptions" className="bg-white text-[#002FA7] hover:bg-[#FF4500] hover:text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider flex items-center gap-1 disabled:opacity-50">
                <FileText size={10} /> Gerar descrições
              </button>
              <button onClick={() => bulkAction("recalc-prices")} disabled={bulkRunning} data-testid="bulk-recalc-prices" className="bg-white text-[#002FA7] hover:bg-[#008A00] hover:text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider flex items-center gap-1 disabled:opacity-50">
                <DollarSign size={10} /> Recalcular preços
              </button>
              <button onClick={() => bulkAction("push")} disabled={bulkRunning} data-testid="bulk-push" className="bg-[#FF4500] hover:bg-[#cc3700] text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider flex items-center gap-1 disabled:opacity-50">
                <Send size={10} /> Aplicar JohnDrop
              </button>
              <button onClick={() => bulkAction("delete")} disabled={bulkRunning} data-testid="bulk-delete" className="bg-white text-[#E60000] hover:bg-[#E60000] hover:text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider flex items-center gap-1 disabled:opacity-50">
                <Trash2 size={10} /> Apagar
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">carregando<span className="ai-cursor"/></div>
        ) : filtered.length === 0 ? (
          <div className="border border-[#E5E5E5] p-16 text-center">
            <p className="text-sm text-neutral-600">Nenhum produto. Vá em "Produtos" (catálogo JohnDrop) para importar.</p>
          </div>
        ) : (
          <div className="border border-[#E5E5E5]" data-testid="products-table">
            <table className="w-full text-sm">
              <thead className="border-b border-[#E5E5E5] bg-white">
                <tr>
                  <th className="w-10 py-3 px-3">
                    <input type="checkbox" checked={allSelectedOnPage} onChange={toggleAll} className="accent-[#002FA7] w-4 h-4" data-testid="select-all-products" />
                  </th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Status</th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">SKU</th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Título · Preço</th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Saúde</th>
                  <th className="text-right py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">JD / Bling</th>
                  <th className="text-right py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Ações</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((p) => {
                  const cfg = STATUS_CONFIG[p.sync_status] || STATUS_CONFIG.pending;
                  const score = healthScore(p);
                  const isSel = selected.has(p.id);
                  return (
                    <tr key={p.id} className={`border-b border-[#E5E5E5] transition-colors ${isSel ? "bg-[#F0F4FF]" : "hover:bg-[#F7F7F7]"}`}>
                      <td className="py-3 px-3">
                        <input type="checkbox" checked={isSel} onChange={() => toggleSel(p.id)} className="accent-[#002FA7] w-4 h-4" data-testid={`select-${p.id}`} />
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className="w-1.5 h-1.5" style={{ background: cfg.color }} />
                          <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: cfg.color }}>{cfg.label}</span>
                        </div>
                      </td>
                      <td className="py-3 px-4 font-mono text-xs whitespace-nowrap">{p.sku}</td>
                      <td className="py-3 px-4 max-w-md">
                        <button onClick={() => navigate(`/products/${p.id}/edit`)} className="text-left hover:text-[#002FA7] transition-colors" data-testid={`product-title-${p.id}`}>
                          <div className="truncate">{p.title}</div>
                          <div className="font-mono text-[10px] text-neutral-500">{p.title.length}ch · R$ {Number(p.price).toFixed(2).replace(".",",")}</div>
                        </button>
                      </td>
                      <td className="py-3 px-4">
                        <HealthBar score={score} />
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-xs">
                        <span className={p.stock_johndrop !== p.stock_bling ? "text-[#E60000]" : ""}>
                          {p.stock_johndrop} / {p.stock_bling}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center justify-end gap-1.5">
                          <button onClick={() => syncOne(p.id)} disabled={syncingId === p.id} data-testid={`sync-${p.id}`} className="border border-[#E5E5E5] hover:border-[#0A0A0A] px-2 py-1.5 text-[10px] font-mono uppercase tracking-wider flex items-center gap-1 transition-colors disabled:opacity-60">
                            <RefreshCw size={10} className={syncingId === p.id ? "animate-spin" : ""} />
                          </button>
                          <button onClick={() => navigate(`/products/${p.id}/edit`)} data-testid={`edit-${p.id}`} className="bg-[#0A0A0A] hover:bg-[#002FA7] text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors">
                            Editar
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}
