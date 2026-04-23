import React, { useEffect, useState } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Plus, Search } from "lucide-react";
import { toast } from "sonner";

const STATUS_CONFIG = {
  synced: { label: "Sincronizado", color: "#008A00" },
  pending: { label: "Pendente", color: "#FFB800" },
  error: { label: "Erro", color: "#E60000" },
  out_of_stock: { label: "Sem estoque", color: "#525252" },
};

export default function Products() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [syncingId, setSyncingId] = useState(null);
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

  const syncOne = async (id) => {
    setSyncingId(id);
    try {
      const { data } = await api.post(`/products/${id}/sync`);
      setProducts((p) => p.map((x) => (x.id === id ? data : x)));
      if (data.sync_status === "synced") toast.success("Produto sincronizado com Bling");
      else if (data.sync_status === "error") toast.error(data.sync_message || "Erro na sincronização");
      else toast.info(data.sync_message || "Pendente");
    } catch (_e) {
      toast.error("Falha ao sincronizar");
    } finally {
      setSyncingId(null);
    }
  };

  const createNew = async () => {
    try {
      const { data } = await api.post("/products", {
        sku: `SKU-${Date.now()}`,
        title: "Novo produto",
        product_code: `PROD${Date.now()}`,
        brand: "",
        ean: "",
        description: "",
        price: 0,
        cost: 0,
        stock_johndrop: 0,
        stock_bling: 0,
        images: [],
      });
      navigate(`/products/${data.id}/edit`);
    } catch (_e) {
      toast.error("Falha ao criar produto");
    }
  };

  const filtered = products.filter((p) => {
    const q = query.toLowerCase();
    return !q || p.title.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || p.product_code.toLowerCase().includes(q);
  });

  return (
    <Layout>
      <PageHeader
        overline="// catálogo"
        title="Produtos"
        description="Catálogo importado da JohnDrop. Cada produto deve ser enriquecido no padrão Bling antes da exportação para os marketplaces."
        actions={
          <button
            onClick={createNew}
            data-testid="new-product-button"
            className="bg-[#002FA7] hover:bg-[#00227A] text-white px-4 py-2 text-xs font-mono uppercase tracking-wider flex items-center gap-2 transition-colors"
          >
            <Plus size={12} /> Novo produto
          </button>
        }
      />

      <div className="p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por SKU, código ou título..."
              data-testid="product-search-input"
              className="w-full bg-[#F7F7F7] border-b-2 border-transparent hover:border-[#E5E5E5] focus:border-[#002FA7] focus:outline-none pl-9 pr-3 py-2 text-sm transition-colors"
            />
          </div>
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">
            {filtered.length} / {products.length}
          </div>
        </div>

        {loading ? (
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">carregando<span className="ai-cursor"/></div>
        ) : filtered.length === 0 ? (
          <div className="border border-[#E5E5E5] p-16 text-center">
            <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 mb-2">// vazio</div>
            <p className="text-sm text-neutral-600">Nenhum produto encontrado. Use "Importar mock JohnDrop" no Dashboard para dados de exemplo.</p>
          </div>
        ) : (
          <div className="border border-[#E5E5E5]" data-testid="products-table">
            <table className="w-full text-sm">
              <thead className="border-b border-[#E5E5E5] bg-white sticky top-0">
                <tr>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Status</th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">SKU</th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Título</th>
                  <th className="text-right py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">JD / Bling</th>
                  <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Canais</th>
                  <th className="text-right py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Ações</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((p) => {
                  const cfg = STATUS_CONFIG[p.sync_status] || STATUS_CONFIG.pending;
                  return (
                    <tr key={p.id} className="border-b border-[#E5E5E5] hover:bg-[#F7F7F7] transition-colors">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2" data-testid={`status-${p.id}`}>
                          <span className="w-1.5 h-1.5" style={{ background: cfg.color }} />
                          <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: cfg.color }}>
                            {cfg.label}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-4 font-mono text-xs">{p.sku}</td>
                      <td className="py-3 px-4 max-w-md">
                        <button
                          onClick={() => navigate(`/products/${p.id}/edit`)}
                          className="text-left hover:text-[#002FA7] transition-colors"
                          data-testid={`product-title-${p.id}`}
                        >
                          <div className="truncate">{p.title}</div>
                          <div className="font-mono text-[10px] text-neutral-400">{p.title.length} chars</div>
                        </button>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-xs">
                        <span className={p.stock_johndrop !== p.stock_bling ? "text-[#E60000]" : ""}>
                          {p.stock_johndrop} / {p.stock_bling}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center justify-center gap-1.5">
                          {p.amazon?.enabled && <span title="Amazon" className="w-1.5 h-1.5" style={{ background: "#FF9900" }} />}
                          {p.shopee?.enabled && <span title="Shopee" className="w-1.5 h-1.5" style={{ background: "#EE4D2D" }} />}
                          {p.kwai?.enabled && <span title="Kwai" className="w-1.5 h-1.5" style={{ background: "#FF3B30" }} />}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => syncOne(p.id)}
                            disabled={syncingId === p.id}
                            data-testid={`sync-${p.id}`}
                            className="border border-[#E5E5E5] hover:border-[#0A0A0A] px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider flex items-center gap-1.5 transition-colors disabled:opacity-60"
                          >
                            <RefreshCw size={10} className={syncingId === p.id ? "animate-spin" : ""} />
                            Sync
                          </button>
                          <button
                            onClick={() => navigate(`/products/${p.id}/edit`)}
                            data-testid={`edit-${p.id}`}
                            className="bg-[#0A0A0A] hover:bg-[#002FA7] text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors"
                          >
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
