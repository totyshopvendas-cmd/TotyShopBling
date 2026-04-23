import React, { useEffect, useState } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { Package, CheckCircle2, Clock, AlertTriangle, PackageX, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

const StatusDot = ({ color }) => (
  <span className="inline-block w-1.5 h-1.5" style={{ background: color }} />
);

const StatCard = ({ label, value, hint, icon: Icon, color, testId }) => (
  <div className="bg-white border border-[#E5E5E5] p-5 transition-all hover:border-[#0A0A0A] hover:shadow-[2px_2px_0px_#0A0A0A]" data-testid={testId}>
    <div className="flex items-start justify-between mb-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500">{label}</div>
      <Icon size={14} style={{ color }} />
    </div>
    <div className="font-heading text-4xl tracking-tighter font-medium text-[#0A0A0A]">{value}</div>
    {hint && <div className="text-xs text-neutral-500 mt-1">{hint}</div>}
  </div>
);

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);

  const load = async () => {
    try {
      const { data } = await api.get("/dashboard/stats");
      setStats(data);
    } catch (_e) {
      toast.error("Falha ao carregar métricas");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const seed = async () => {
    setSeeding(true);
    try {
      const { data } = await api.post("/products/seed");
      toast.success(`${data.created} produtos importados da JohnDrop`);
      load();
    } catch (_e) {
      toast.error("Falha ao importar");
    } finally {
      setSeeding(false);
    }
  };

  return (
    <Layout>
      <PageHeader
        overline="// visão geral"
        title="Dashboard"
        description="Métricas em tempo real da sincronização JohnDrop → Bling e cobertura dos marketplaces."
        actions={
          <button
            onClick={seed}
            disabled={seeding}
            data-testid="seed-products-button"
            className="border border-[#E5E5E5] hover:border-[#0A0A0A] px-4 py-2 text-xs font-mono uppercase tracking-wider transition-colors disabled:opacity-60"
          >
            {seeding ? "Importando..." : "Importar mock JohnDrop"}
          </button>
        }
      />

      <div className="p-8 space-y-8">
        {loading ? (
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">carregando<span className="ai-cursor" /></div>
        ) : stats && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
              <StatCard label="Total produtos" value={stats.total_products} icon={Package} color="#0A0A0A" testId="stat-total" />
              <StatCard label="Sincronizados" value={stats.synced} icon={CheckCircle2} color="#008A00" testId="stat-synced" />
              <StatCard label="Pendentes" value={stats.pending} icon={Clock} color="#FFB800" testId="stat-pending" />
              <StatCard label="Com erro" value={stats.errors} icon={AlertTriangle} color="#E60000" testId="stat-errors" />
              <StatCard label="Sem estoque" value={stats.out_of_stock} icon={PackageX} color="#525252" testId="stat-oos" />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
              {/* Marketplace coverage */}
              <div className="lg:col-span-5 bg-white border border-[#E5E5E5] p-6" data-testid="marketplace-coverage">
                <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500 mb-4">// cobertura marketplaces</div>
                <div className="space-y-4">
                  {[
                    { name: "Amazon", count: stats.marketplace_coverage.amazon, color: "#FF9900" },
                    { name: "Shopee", count: stats.marketplace_coverage.shopee, color: "#EE4D2D" },
                    { name: "Kwai Shop", count: stats.marketplace_coverage.kwai, color: "#FF3B30" },
                  ].map((m) => {
                    const pct = stats.total_products ? (m.count / stats.total_products) * 100 : 0;
                    return (
                      <div key={m.name}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <StatusDot color={m.color} />
                            <span className="font-heading text-sm font-medium">{m.name}</span>
                          </div>
                          <span className="font-mono text-xs text-neutral-500">
                            {m.count} / {stats.total_products}
                          </span>
                        </div>
                        <div className="h-1.5 bg-[#EBEBEB]">
                          <div className="h-full transition-all" style={{ width: `${pct}%`, background: m.color }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Divergence table */}
              <div className="lg:col-span-7 bg-white border border-[#E5E5E5]" data-testid="stock-divergence">
                <div className="px-6 py-4 border-b border-[#E5E5E5] flex items-center justify-between">
                  <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500">// divergência de estoque</div>
                  <Link to="/products" className="text-xs font-mono uppercase tracking-wider text-[#002FA7] hover:underline flex items-center gap-1">
                    ver todos <ArrowRight size={12} />
                  </Link>
                </div>
                {stats.stock_divergences.length === 0 ? (
                  <div className="p-8 text-sm text-neutral-500 text-center">
                    Sem divergências. JohnDrop e Bling estão alinhados.
                  </div>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#E5E5E5] text-left">
                        <th className="py-2.5 px-6 font-mono text-[10px] uppercase tracking-wider text-neutral-500">SKU</th>
                        <th className="py-2.5 px-2 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Produto</th>
                        <th className="py-2.5 px-2 font-mono text-[10px] uppercase tracking-wider text-neutral-500 text-right">JohnDrop</th>
                        <th className="py-2.5 px-6 font-mono text-[10px] uppercase tracking-wider text-neutral-500 text-right">Bling</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.stock_divergences.map((d) => (
                        <tr key={d.id} className="border-b border-[#E5E5E5] hover:bg-[#F7F7F7]">
                          <td className="py-2.5 px-6 font-mono text-xs">{d.sku}</td>
                          <td className="py-2.5 px-2 truncate max-w-xs">{d.title}</td>
                          <td className="py-2.5 px-2 text-right font-mono text-xs">{d.stock_johndrop}</td>
                          <td className="py-2.5 px-6 text-right font-mono text-xs text-[#E60000]">{d.stock_bling}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
