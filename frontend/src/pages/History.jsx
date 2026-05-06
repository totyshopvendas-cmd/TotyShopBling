import React, { useEffect, useState } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { toast } from "sonner";
import { CheckCircle2, ExternalLink, Sparkles, Package, Link2, AlertTriangle } from "lucide-react";

export default function History() {
  const [tab, setTab] = useState("johndrop");
  const [jdItems, setJdItems] = useState([]);
  const [blingItems, setBlingItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [jd, bling] = await Promise.all([
          api.get("/johndrop/history"),
          api.get("/bling/enrich-history"),
        ]);
        setJdItems(jd.data.items || []);
        setBlingItems(bling.data.items || []);
      } catch (_e) {
        toast.error("Falha ao carregar histórico");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const money = (v) => v != null ? `R$ ${Number(v).toFixed(2).replace(".", ",")}` : "-";

  const TabBtn = ({ id, label, count, icon: Icon }) => (
    <button
      onClick={() => setTab(id)}
      className={`flex items-center gap-2 px-5 py-3 font-mono text-xs uppercase tracking-wider border-b-2 transition-colors ${
        tab === id
          ? "border-[#002FA7] text-[#002FA7]"
          : "border-transparent text-neutral-500 hover:text-[#0A0A0A]"
      }`}
    >
      <Icon size={13} />
      {label}
      <span className={`px-1.5 py-0.5 text-[10px] font-mono ${tab === id ? "bg-[#002FA7] text-white" : "bg-[#EBEBEB] text-neutral-600"}`}>
        {count}
      </span>
    </button>
  );

  return (
    <Layout>
      <PageHeader
        overline="// histórico · auditoria"
        title="Histórico"
        description="Registro completo de cadastros JohnDrop e enriquecimentos Bling com IA."
      />

      {/* Tabs */}
      <div className="border-b border-[#E5E5E5] px-8 flex gap-0">
        <TabBtn id="johndrop" label="Cadastros JohnDrop" count={jdItems.length} icon={Package} />
        <TabBtn id="bling" label="Enriquecimentos Bling" count={blingItems.length} icon={Sparkles} />
      </div>

      <div className="p-8">
        {loading ? (
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">
            carregando<span className="ai-cursor" />
          </div>
        ) : tab === "johndrop" ? (
          <>
            {jdItems.length === 0 ? (
              <div className="border border-[#E5E5E5] p-16 text-center">
                <p className="text-sm text-neutral-600">
                  Nenhum cadastro feito ainda. Vá em Catálogo JohnDrop para começar.
                </p>
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
                    {jdItems.map((it, i) => (
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
                Os produtos cadastrados aparecem em <strong>"Meus produtos"</strong> da sua conta JohnDrop em{" "}
                <a
                  href="https://app.jonhdrop.com.br/dashboard/product"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[#002FA7] underline"
                >
                  app.jonhdrop.com.br/dashboard/product
                </a>{" "}
                e são repassados automaticamente ao Bling via extensão TotyShop-Bling.
              </div>
            </div>
          </>
        ) : (
          <>
            {blingItems.length === 0 ? (
              <div className="border border-[#E5E5E5] p-16 text-center">
                <p className="text-sm text-neutral-600">
                  Nenhum enriquecimento feito ainda. Vá em Catálogo Bling para enriquecer produtos com IA.
                </p>
              </div>
            ) : (
              <div className="border border-[#E5E5E5]" data-testid="bling-enrich-history-table">
                <table className="w-full text-sm">
                  <thead className="border-b border-[#E5E5E5]">
                    <tr>
                      <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Data</th>
                      <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Código Bling</th>
                      <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Produto</th>
                      <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">NCM</th>
                      <th className="text-left py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Categoria</th>
                      <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Fornecedor</th>
                      <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Modelo IA</th>
                      <th className="text-center py-3 px-4 font-mono text-[10px] uppercase tracking-wider text-neutral-500">Desc. JD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {blingItems.map((it, i) => (
                      <tr key={i} className="border-b border-[#E5E5E5] hover:bg-[#F7F7F7]">
                        <td className="py-2.5 px-4 font-mono text-xs text-neutral-500 whitespace-nowrap">
                          {new Date(it.enriched_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
                        </td>
                        <td className="py-2.5 px-4 font-mono text-xs">{it.bling_code || "-"}</td>
                        <td className="py-2.5 px-4 max-w-xs truncate text-sm">{it.bling_title || "-"}</td>
                        <td className="py-2.5 px-4 text-center font-mono text-[10px]">
                          {it.ncm ? (
                            <span className="text-[#008A00]">{it.ncm}</span>
                          ) : (
                            <span className="text-neutral-400">-</span>
                          )}
                        </td>
                        <td className="py-2.5 px-4 font-mono text-[10px] max-w-[140px] truncate">
                          {it.category_assigned || <span className="text-neutral-400">-</span>}
                        </td>
                        <td className="py-2.5 px-4 text-center">
                          {it.supplier_linked ? (
                            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-[#008A00]">
                              <Link2 size={11} /> vinculado
                            </span>
                          ) : it.supplier_error ? (
                            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-[#E60000]" title={it.supplier_error}>
                              <AlertTriangle size={11} /> erro
                            </span>
                          ) : (
                            <span className="text-neutral-400 text-[10px] font-mono">-</span>
                          )}
                        </td>
                        <td className="py-2.5 px-4 text-center">
                          <span className={`inline-block px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider ${
                            it.ai_model === "claude" ? "bg-[#F0F4FF] text-[#002FA7]" : "bg-[#FFF4E5] text-[#FF6B00]"
                          }`}>
                            {it.ai_model || "claude"}
                          </span>
                        </td>
                        <td className="py-2.5 px-4 text-center">
                          {it.used_johndrop_description ? (
                            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-[#008A00]">
                              <CheckCircle2 size={11} /> sim
                            </span>
                          ) : (
                            <span className="text-neutral-400 text-[10px] font-mono">não</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="mt-6 flex items-start gap-3 border border-[#E5E5E5] p-4 bg-[#FAFAFA]">
              <Sparkles size={16} className="text-[#FF4500] shrink-0 mt-0.5" />
              <div className="text-xs text-neutral-600 leading-relaxed">
                O enriquecimento IA preenche <strong>descrição completa, NCM, categoria, peso e dimensões</strong> diretamente no Bling,
                sem alterar título, SKU ou preço. Quando disponível, a IA usa a descrição original da JohnDrop como base.
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
