import React, { useState } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { toast } from "sonner";
import { Calculator, TrendingUp } from "lucide-react";

const Input = ({ label, value, onChange, testId, prefix = "R$" }) => (
  <div>
    <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">{label}</label>
    <div className="flex items-center bg-[#F7F7F7] border-b-2 border-transparent focus-within:border-[#002FA7] transition-colors">
      <span className="px-3 font-mono text-xs text-neutral-500">{prefix}</span>
      <input
        type="number"
        step="0.01"
        min="0"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        data-testid={testId}
        className="flex-1 bg-transparent focus:outline-none py-2 pr-3 text-sm font-mono"
      />
    </div>
  </div>
);

export default function Pricing() {
  const [cost, setCost] = useState(32.5);
  const [packaging, setPackaging] = useState(2.0);
  const [campaigns, setCampaigns] = useState(5.0);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const calc = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/pricing/calculate", { cost, packaging, campaigns });
      setResult(data);
    } catch (_e) {
      toast.error("Falha ao calcular");
    } finally {
      setLoading(false);
    }
  };

  const money = (v) => `R$ ${Number(v).toFixed(2).replace(".", ",")}`;

  return (
    <Layout>
      <PageHeader
        overline="// calculadora blindada"
        title="Preço de venda seguro"
        description="Lucro real garantido com todas as despesas descontadas. Comissão 18% · Taxa fixa R$ 6,00 · Margem mínima 20%."
      />

      <div className="p-8 grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Inputs */}
        <div className="lg:col-span-5 border border-[#E5E5E5] p-6 bg-white">
          <div className="flex items-center gap-2 mb-5">
            <Calculator size={16} className="text-[#002FA7]" />
            <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500">// entradas</span>
          </div>

          <div className="space-y-4">
            <Input label="Custo do Produto" value={cost} onChange={setCost} testId="cost-input" />
            <Input label="Despesa com Embalagem" value={packaging} onChange={setPackaging} testId="packaging-input" />
            <Input label="Despesa com Campanhas" value={campaigns} onChange={setCampaigns} testId="campaigns-input" />
          </div>

          <button
            onClick={calc}
            disabled={loading}
            data-testid="calculate-button"
            className="w-full mt-6 bg-[#002FA7] hover:bg-[#00227A] text-white px-4 py-3 text-xs font-mono uppercase tracking-wider transition-colors disabled:opacity-60"
          >
            {loading ? "Calculando..." : "Calcular preço de venda"}
          </button>

          <div className="mt-6 pt-6 border-t border-[#E5E5E5] space-y-1.5">
            <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 mb-2">// regras fixas</div>
            <div className="flex justify-between text-xs">
              <span className="text-neutral-600">Comissão marketplace</span>
              <span className="font-mono">18,00%</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-neutral-600">Taxa fixa por venda</span>
              <span className="font-mono">R$ 6,00</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-neutral-600">Margem mínima garantida</span>
              <span className="font-mono">20,00%</span>
            </div>
          </div>
        </div>

        {/* Result */}
        <div className="lg:col-span-7 space-y-4">
          {!result ? (
            <div className="border border-[#E5E5E5] p-16 text-center">
              <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 mb-2">// aguardando</div>
              <p className="text-sm text-neutral-600">
                Digite o custo do produto e suas despesas para calcular o preço de venda seguro com garantia de lucro mínimo de 20%.
              </p>
            </div>
          ) : (
            <>
              <div className="border-2 border-[#002FA7] p-8 bg-white shadow-[4px_4px_0px_#002FA7]" data-testid="pricing-result">
                <div className="flex items-center gap-2 mb-3">
                  <TrendingUp size={14} className="text-[#002FA7]" />
                  <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-[#002FA7]">// preço de venda sugerido</span>
                </div>
                <div className="font-heading text-6xl tracking-tighter font-medium text-[#0A0A0A]" data-testid="selling-price">
                  {money(result.selling_price)}
                </div>
                <div className="mt-4 flex items-center gap-6">
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">Lucro líquido</div>
                    <div className="font-heading text-xl text-[#008A00] font-medium">{money(result.breakdown.net_profit)}</div>
                  </div>
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">Margem</div>
                    <div className="font-heading text-xl text-[#008A00] font-medium">
                      {((result.breakdown.net_profit / result.selling_price) * 100).toFixed(1)}%
                    </div>
                  </div>
                </div>
              </div>

              <div className="border border-[#E5E5E5] p-6">
                <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500 mb-4">// decomposição</div>
                <table className="w-full text-sm">
                  <tbody>
                    {[
                      ["Custo do produto", result.breakdown.cost, "#0A0A0A"],
                      ["Embalagem", result.breakdown.packaging, "#0A0A0A"],
                      ["Campanhas", result.breakdown.campaigns, "#0A0A0A"],
                      ["Subtotal de custos", result.breakdown.total_cost, "#525252", true],
                      ["Comissão 18%", result.breakdown.commission_value, "#E60000"],
                      ["Taxa fixa", result.breakdown.fixed_fee, "#E60000"],
                      ["Margem mínima 20%", result.breakdown.min_margin_value, "#008A00"],
                    ].map(([label, val, color, bold]) => (
                      <tr key={label} className="border-b border-[#E5E5E5]">
                        <td className={`py-2.5 ${bold ? "font-medium" : ""}`} style={{ color }}>{label}</td>
                        <td className="py-2.5 text-right font-mono" style={{ color }}>{money(val)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td className="py-3 font-heading font-medium">Preço final de venda</td>
                      <td className="py-3 text-right font-mono font-medium text-[#002FA7]">{money(result.selling_price)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </Layout>
  );
}
