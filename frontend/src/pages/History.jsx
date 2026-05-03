import React, { useEffect, useState } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { toast } from "sonner";
import { CheckCircle2, ExternalLink } from "lucide-react";

export default function History() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/johndrop/history");
        setItems(data.items);
      } catch (_e) {
        toast.error("Falha ao carregar histórico");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const money = (v) => `R$ ${Number(v).toFixed(2).replace(".", ",")}`;

  return (
    <Layout>
      <PageHeader
        overline="// histórico · auditoria"
        title="Histórico de cadastros"
        description="Produtos cadastrados na JohnDrop via BlingDrop. Todos já estão em 'Meus produtos' da JohnDrop, integrados ao Bling via TotyShop."
      />

      <div className="p-8">
        {loading ? (
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">carregando<span className="ai-cursor"/></div>
        ) : items.length === 0 ? (
          <div className="border border-[#E5E5E5] p-16 text-center">
            <p className="text-sm text-neutral-600">Nenhum cadastro feito ainda. Vá em Catálogo JohnDrop para começar.</p>
          </div>
        ) : (
          <div className="border border-[#E5E5E5]" data-testid="history-table">
            <table className="w-full text-sm">
              <thead className="border-b border-[#E5E5E5]">
                <tr>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Data</th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Código</th>
                  <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Título SEO aplicado</th>
                  <th className="text-right py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Custo → Venda</th>
                  <th className="text-right py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Markup</th>
                  <th className="text-right py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, i) => (
                  <tr key={i} className="border-b border-[#E5E5E5] hover:bg-[#F7F7F7]">
                    <td className="py-2.5 px-4 font-mono text-xs text-neutral-500">
                      {new Date(it.registered_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-xs">{it.product_code}</td>
                    <td className="py-2.5 px-4 max-w-md truncate">{it.seo_title}</td>
                    <td className="py-2.5 px-4 text-right font-mono text-xs">
                      <span className="text-neutral-500">{money(it.price_cost)}</span>
                      <span className="text-neutral-400 mx-1">→</span>
                      <span className="text-[#002FA7] font-bold">{money(it.price_sale)}</span>
                    </td>
                    <td className="py-2.5 px-4 text-right font-mono text-xs">{it.markup}x</td>
                    <td className="py-2.5 px-4 text-right">
                      <div className="inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-wider text-[#008A00]">
                        <CheckCircle2 size={12} /> cadastrado
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-6 flex items-start gap-3 border border-[#E5E5E5] p-4 bg-[#FAFAFA]">
          <ExternalLink size={16} className="text-neutral-500 shrink-0 mt-0.5" />
          <div className="text-xs text-neutral-600 leading-relaxed">
            Os produtos cadastrados aparecem em <strong>"Meus produtos"</strong> da sua conta JohnDrop em <a href="https://app.jonhdrop.com.br/dashboard/product" target="_blank" rel="noopener noreferrer" className="text-[#002FA7] underline">app.jonhdrop.com.br/dashboard/product</a> e são repassados automaticamente ao Bling via extensão TotyShop-Bling.
          </div>
        </div>
      </div>
    </Layout>
  );
}
