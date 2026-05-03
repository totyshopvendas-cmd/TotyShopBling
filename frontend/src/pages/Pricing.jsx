import React, { useState } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { toast } from "sonner";
import { Calculator, TrendingUp, AlertTriangle, Shield } from "lucide-react";

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
  const [packaging, setPackaging] = useState(0);
  const [campaigns, setCampaigns] = useState(0);
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
        description="Lucro real garantido com todas as despesas descontadas. Comissão 18% · Taxa fixa R$ 6,00 · Processamento R$ 1,00 · Margem mínima 20%."
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
            <div className="flex justify-between text-xs"><span className="text-neutral-600">Comissão marketplace</span><span className="font-mono">18,00%</span></div>
            <div className="flex justify-between text-xs"><span className="text-neutral-600">Taxa fixa por venda</span><span className="font-mono">R$ 6,00</span></div>
            <div className="flex justify-between text-xs"><span className="text-neutral-600">Custo de processamento</span><span className="font-mono">R$ 1,00</span></div>
            <div className="flex justify-between text-xs"><span className="text-neutral-600">Margem mínima garantida</span><span className="font-mono">20,00%</span></div>
          </div>

          <div className="mt-5 pt-5 border-t border-[#E5E5E5] space-y-1">
            <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 mb-2">// markup escalonado</div>
            <div className="flex justify-between text-xs"><span className="text-neutral-600">Custo ≤ R$ 20</span><span className="font-mono">2,6x</span></div>
            <div className="flex justify-between text-xs"><span className="text-neutral-600">Custo R$ 20,01 – 50,00</span><span className="font-mono">2,1x</span></div>
            <div className="flex justify-between text-xs"><span className="text-neutral-600">Custo &gt; R$ 50</span><span className="font-mono">1,8x</span></div>
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
              {/* Safety Alert */}
              {result.safety_alert && (
                <div className="border-2 border-[#FFB800] bg-[#FFF8E6] p-4 flex items-start gap-3" data-testid="safety-alert">
                  <AlertTriangle size={18} className="text-[#8a6100] mt-0.5 shrink-0" />
                  <div className="text-xs text-[#8a6100]">
                    <strong className="font-mono uppercase tracking-wider">Alerta de segurança:</strong> o markup deste custo não cobre as despesas mínimas. O preço foi ajustado para a versão blindada (cobre 100% dos custos + 20% de margem).
                  </div>
                </div>
              )}

              {/* Main result */}
              <div className="border-2 border-[#002FA7] p-8 bg-white shadow-[4px_4px_0px_#002FA7]" data-testid="pricing-result">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <TrendingUp size={14} className="text-[#002FA7]" />
                    <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-[#002FA7]">// preço de venda seguro</span>
                  </div>
                  <div className="flex items-center gap-1.5 bg-[#0A0A0A] text-white px-2 py-1">
                    <span className="font-mono text-[10px] uppercase tracking-wider">markup</span>
                    <span className="font-mono text-xs font-bold">{result.markup.toString().replace(".", ",")}x</span>
                  </div>
                </div>
                <div className="font-heading text-6xl tracking-tighter font-medium text-[#0A0A0A]" data-testid="selling-price">
                  {money(result.selling_price)}
                </div>
                <div className="mt-4 flex items-center gap-6">
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">Lucro real no bolso</div>
                    <div className="font-heading text-xl text-[#008A00] font-medium">{money(result.breakdown.net_profit)}</div>
                    <div className="font-mono text-[10px] text-neutral-500">({result.breakdown.net_profit_pct}% de margem)</div>
                  </div>
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">Preço blindado mín.</div>
                    <div className="font-heading text-xl text-neutral-700 font-medium">{money(result.breakdown.preco_blindado)}</div>
                    <div className="font-mono text-[10px] text-neutral-500 flex items-center gap-1"><Shield size={10} /> garante 20% margem</div>
                  </div>
                </div>
              </div>

              {/* Breakdown */}
              <div className="border border-[#E5E5E5] p-6">
                <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500 mb-4">// resumo de despesas</div>
                <table className="w-full text-sm">
                  <tbody>
                    <tr className="border-b border-[#E5E5E5]">
                      <td className="py-2.5">Custo + processamento</td>
                      <td className="py-2.5 text-right font-mono">-{money(result.breakdown.custo_total)}</td>
                    </tr>
                    {result.breakdown.packaging > 0 && (
                      <tr className="border-b border-[#E5E5E5]">
                        <td className="py-2.5">Embalagem</td>
                        <td className="py-2.5 text-right font-mono">-{money(result.breakdown.packaging)}</td>
                      </tr>
                    )}
                    {result.breakdown.campaigns > 0 && (
                      <tr className="border-b border-[#E5E5E5]">
                        <td className="py-2.5">Campanhas</td>
                        <td className="py-2.5 text-right font-mono">-{money(result.breakdown.campaigns)}</td>
                      </tr>
                    )}
                    <tr className="border-b border-[#E5E5E5]">
                      <td className="py-2.5">Comissão (18%)</td>
                      <td className="py-2.5 text-right font-mono text-[#E60000]">-{money(result.breakdown.commission_value)}</td>
                    </tr>
                    <tr className="border-b border-[#E5E5E5]">
                      <td className="py-2.5">Taxa fixa</td>
                      <td className="py-2.5 text-right font-mono text-[#E60000]">-{money(result.breakdown.fixed_fee)}</td>
                    </tr>
                    <tr className="border-b-2 border-[#0A0A0A]">
                      <td className="py-2.5 font-medium">Total de despesas</td>
                      <td className="py-2.5 text-right font-mono font-medium">
                        -{money(result.breakdown.custo_total + result.breakdown.packaging + result.breakdown.campaigns + result.breakdown.commission_value + result.breakdown.fixed_fee)}
                      </td>
                    </tr>
                    <tr>
                      <td className="py-3 font-heading font-medium text-[#002FA7]">Preço de venda</td>
                      <td className="py-3 text-right font-mono font-medium text-[#002FA7] text-base">{money(result.selling_price)}</td>
                    </tr>
                    <tr>
                      <td className="py-1 font-heading font-medium text-[#008A00]">Lucro no bolso</td>
                      <td className="py-1 text-right font-mono font-medium text-[#008A00] text-base">{money(result.breakdown.net_profit)}</td>
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
