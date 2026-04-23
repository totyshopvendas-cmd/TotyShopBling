import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { toast } from "sonner";
import { Sparkles, Save, RefreshCw, ArrowLeft, AlertCircle, CheckCircle2, Image as ImageIcon, Calculator } from "lucide-react";

const TABS = [
  { id: "geral", label: "Geral", color: "#0A0A0A" },
  { id: "amazon", label: "Amazon", color: "#FF9900" },
  { id: "shopee", label: "Shopee", color: "#EE4D2D" },
  { id: "kwai", label: "Kwai Shop", color: "#FF3B30" },
];

const Input = ({ label, value, onChange, type = "text", testId, mono = false, ...rest }) => (
  <div>
    <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">{label}</label>
    <input
      type={type}
      value={value ?? ""}
      onChange={(e) => onChange(type === "number" ? parseFloat(e.target.value || 0) : e.target.value)}
      data-testid={testId}
      className={`w-full bg-[#F7F7F7] border-b-2 border-transparent hover:border-[#E5E5E5] focus:border-[#002FA7] focus:outline-none px-3 py-2 text-sm transition-colors ${mono ? "font-mono" : ""}`}
      {...rest}
    />
  </div>
);

const Checkbox = ({ label, checked, onChange, testId }) => (
  <label className="flex items-center gap-2 cursor-pointer select-none">
    <input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} data-testid={testId} className="accent-[#002FA7] w-4 h-4" />
    <span className="text-sm">{label}</span>
  </label>
);

export default function ProductEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState("geral");
  const [aiModel, setAiModel] = useState("claude");
  const [aiBusy, setAiBusy] = useState({ title: false, bullets: false, description: false });
  const [packaging, setPackaging] = useState(2.0);
  const [campaigns, setCampaigns] = useState(5.0);
  const [pricingResult, setPricingResult] = useState(null);
  const [pricingBusy, setPricingBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/products/${id}`);
        setProduct(data);
      } catch (_e) {
        toast.error("Produto não encontrado");
        navigate("/products");
      } finally {
        setLoading(false);
      }
    })();
  }, [id, navigate]);

  if (loading || !product) {
    return <Layout><div className="p-8 font-mono text-xs text-neutral-500 uppercase tracking-wider">carregando<span className="ai-cursor"/></div></Layout>;
  }

  const update = (patch) => setProduct((p) => ({ ...p, ...patch }));
  const updateAmazon = (patch) => setProduct((p) => ({ ...p, amazon: { ...p.amazon, ...patch } }));
  const updateShopee = (patch) => setProduct((p) => ({ ...p, shopee: { ...p.shopee, ...patch } }));
  const updateKwai = (patch) => setProduct((p) => ({ ...p, kwai: { ...p.kwai, ...patch } }));

  const titleLen = (product.title || "").length;
  const titleOver = titleLen > 60;
  const titleHasBrand = product.brand && product.title?.toLowerCase().includes(product.brand.toLowerCase());
  const titleHasEan = product.ean && product.title?.includes(product.ean);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        sku: product.sku,
        title: product.title,
        product_code: product.product_code,
        brand: product.brand || "",
        ean: product.ean || "",
        description: product.description || "",
        price: product.price || 0,
        cost: product.cost || 0,
        stock_johndrop: product.stock_johndrop || 0,
        stock_bling: product.stock_bling || 0,
        images: product.images || [],
        amazon: product.amazon,
        shopee: product.shopee,
        kwai: product.kwai,
      };
      const { data } = await api.put(`/products/${id}`, payload);
      setProduct(data);
      toast.success("Produto salvo");
    } catch (_e) {
      toast.error("Falha ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const sync = async () => {
    setSaving(true);
    try {
      const { data } = await api.post(`/products/${id}/sync`);
      setProduct(data);
      if (data.sync_status === "synced") toast.success("Sincronizado com Bling");
      else toast.error(data.sync_message || "Erro");
    } finally { setSaving(false); }
  };

  const genTitle = async () => {
    setAiBusy((s) => ({ ...s, title: true }));
    try {
      const { data } = await api.post("/ai/generate-title", {
        raw_name: product.title || product.sku,
        product_code: product.product_code,
        category: product.amazon?.category || "",
        keywords: "",
        model: aiModel,
      });
      update({ title: data.title });
      toast.success(`Título gerado (${data.length}/60)`);
    } catch (_e) {
      toast.error("Falha na IA");
    } finally { setAiBusy((s) => ({ ...s, title: false })); }
  };

  const genBullets = async () => {
    setAiBusy((s) => ({ ...s, bullets: true }));
    try {
      const { data } = await api.post("/ai/generate-bullets", {
        title: product.title,
        product_code: product.product_code,
        category: product.amazon?.category || "",
        keywords: "",
        model: aiModel,
      });
      updateAmazon({ bullet_points: data.bullets });
      toast.success("6 bullet points gerados");
    } catch (_e) { toast.error("Falha na IA"); }
    finally { setAiBusy((s) => ({ ...s, bullets: false })); }
  };

  const genDesc = async () => {
    setAiBusy((s) => ({ ...s, description: true }));
    try {
      const { data } = await api.post("/ai/generate-description", {
        title: product.title,
        bullets: product.amazon?.bullet_points || [],
        model: aiModel,
      });
      update({ description: data.description });
      toast.success("Descrição gerada");
    } catch (_e) { toast.error("Falha na IA"); }
    finally { setAiBusy((s) => ({ ...s, description: false })); }
  };

  const calcPrice = async () => {
    setPricingBusy(true);
    try {
      const { data } = await api.post("/pricing/calculate", {
        cost: product.cost || 0,
        packaging,
        campaigns,
      });
      setPricingResult(data);
    } catch (_e) { toast.error("Falha ao calcular"); }
    finally { setPricingBusy(false); }
  };

  const applyPrice = () => {
    if (!pricingResult) return;
    update({ price: pricingResult.selling_price });
    toast.success("Preço aplicado ao produto");
  };

  const money = (v) => `R$ ${Number(v).toFixed(2).replace(".", ",")}`;

  return (
    <Layout>
      <PageHeader
        overline={`// ${product.sku}`}
        title={product.title || "Sem título"}
        description={`Editando produto ${product.product_code} · Status: ${product.sync_status}`}
        actions={
          <>
            <button
              onClick={() => navigate("/products")}
              data-testid="back-button"
              className="border border-[#E5E5E5] hover:border-[#0A0A0A] px-3 py-2 text-xs font-mono uppercase tracking-wider transition-colors flex items-center gap-1.5"
            >
              <ArrowLeft size={12} /> Voltar
            </button>
            <button
              onClick={sync}
              disabled={saving}
              data-testid="sync-product-button"
              className="border border-[#E5E5E5] hover:border-[#0A0A0A] px-3 py-2 text-xs font-mono uppercase tracking-wider transition-colors flex items-center gap-1.5 disabled:opacity-60"
            >
              <RefreshCw size={12} /> Sync Bling
            </button>
            <button
              onClick={save}
              disabled={saving}
              data-testid="save-product-button"
              className="bg-[#002FA7] hover:bg-[#00227A] text-white px-4 py-2 text-xs font-mono uppercase tracking-wider transition-colors flex items-center gap-1.5 disabled:opacity-60"
            >
              <Save size={12} /> {saving ? "Salvando..." : "Salvar"}
            </button>
          </>
        }
      />

      <div className="p-8 space-y-6">
        {product.sync_message && (
          <div className={`border-l-4 px-4 py-3 text-xs ${product.sync_status === "error" ? "border-[#E60000] bg-red-50 text-[#E60000]" : product.sync_status === "synced" ? "border-[#008A00] bg-green-50 text-[#008A00]" : "border-[#FFB800] bg-yellow-50 text-[#8a6100]"}`}>
            <strong className="font-mono uppercase tracking-wider">{product.sync_status}</strong> · {product.sync_message}
          </div>
        )}

        {/* AI model selector */}
        <div className="border border-[#E5E5E5] p-4 flex flex-wrap items-center gap-4 bg-[#FAFAFA]">
          <div className="flex items-center gap-2">
            <Sparkles size={14} className="text-[#FF4500]" />
            <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-700">IA Copy Engine</span>
          </div>
          <div className="flex gap-1">
            {[
              { k: "claude", label: "Claude Sonnet 4.5" },
              { k: "gpt", label: "GPT-5.2" },
            ].map((m) => (
              <button
                key={m.k}
                onClick={() => setAiModel(m.k)}
                data-testid={`ai-model-${m.k}`}
                className={`px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider border transition-colors ${aiModel === m.k ? "bg-[#0A0A0A] text-white border-[#0A0A0A]" : "border-[#E5E5E5] hover:border-[#0A0A0A]"}`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[#E5E5E5]">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              data-testid={`tab-${t.id}`}
              className={`px-5 py-3 font-mono text-[10px] uppercase tracking-wider border-t-2 transition-colors ${tab === t.id ? "text-[#0A0A0A] bg-white" : "text-neutral-500 hover:text-[#0A0A0A] border-transparent"}`}
              style={tab === t.id ? { borderTopColor: t.color } : {}}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Panels */}
        {tab === "geral" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-8 space-y-5">
              {/* Title with counter */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">Título SEO</label>
                  <div className="flex items-center gap-3">
                    <span
                      data-testid="title-char-counter"
                      className={`font-mono text-xs ${titleOver ? "text-[#E60000] font-bold" : "text-neutral-500"}`}
                    >
                      {titleLen} / 60
                    </span>
                    <button
                      onClick={genTitle}
                      disabled={aiBusy.title}
                      data-testid="ai-generate-title"
                      className="border-2 border-[#FF4500] text-[#FF4500] hover:bg-[#FF4500] hover:text-white px-3 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors flex items-center gap-1.5 shadow-[2px_2px_0px_#FF4500] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] disabled:opacity-60"
                    >
                      <Sparkles size={10} /> {aiBusy.title ? "Gerando..." : "Gerar IA"}
                    </button>
                  </div>
                </div>
                <input
                  value={product.title || ""}
                  onChange={(e) => update({ title: e.target.value })}
                  data-testid="seo-title-input"
                  className={`w-full bg-[#F7F7F7] border-b-2 focus:outline-none px-3 py-2 text-sm transition-colors ${titleOver ? "border-[#E60000]" : "border-transparent focus:border-[#002FA7]"}`}
                />
                <div className="mt-1.5 text-[11px] text-neutral-500 space-y-0.5">
                  {titleOver && <div className="text-[#E60000] flex items-center gap-1"><AlertCircle size={10}/> Título excede 60 caracteres</div>}
                  {titleHasBrand && <div className="text-[#E60000] flex items-center gap-1"><AlertCircle size={10}/> Remova a marca do título (detectado: "{product.brand}")</div>}
                  {titleHasEan && <div className="text-[#E60000] flex items-center gap-1"><AlertCircle size={10}/> Remova o EAN do título</div>}
                  {!titleOver && !titleHasBrand && !titleHasEan && titleLen > 0 && (
                    <div className="text-[#008A00] flex items-center gap-1"><CheckCircle2 size={10}/> Título no padrão SEO</div>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <Input label="SKU" value={product.sku} onChange={(v) => update({ sku: v })} mono testId="sku-input" />
                <Input label="Código do produto" value={product.product_code} onChange={(v) => update({ product_code: v })} mono testId="product-code-input" />
                <Input label="Marca (não entra no título)" value={product.brand} onChange={(v) => update({ brand: v })} testId="brand-input" />
                <Input label="EAN (não entra no título)" value={product.ean} onChange={(v) => update({ ean: v })} mono testId="ean-input" />
                <Input label="Preço (R$)" type="number" value={product.price} onChange={(v) => update({ price: v })} mono testId="price-input" />
                <Input label="Custo (R$)" type="number" value={product.cost} onChange={(v) => update({ cost: v })} mono testId="cost-input" />
                <Input label="Estoque JohnDrop" type="number" value={product.stock_johndrop} onChange={(v) => update({ stock_johndrop: v })} mono testId="stock-jd-input" />
                <Input label="Estoque Bling" type="number" value={product.stock_bling} onChange={(v) => update({ stock_bling: v })} mono testId="stock-bling-input" />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">Descrição geral</label>
                  <button
                    onClick={genDesc}
                    disabled={aiBusy.description}
                    data-testid="ai-generate-description"
                    className="border-2 border-[#FF4500] text-[#FF4500] hover:bg-[#FF4500] hover:text-white px-3 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors flex items-center gap-1.5 shadow-[2px_2px_0px_#FF4500] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] disabled:opacity-60"
                  >
                    <Sparkles size={10} /> {aiBusy.description ? "Gerando..." : "Gerar IA"}
                  </button>
                </div>
                <textarea
                  value={product.description || ""}
                  onChange={(e) => update({ description: e.target.value })}
                  rows={5}
                  data-testid="description-input"
                  className="w-full bg-[#F7F7F7] border-b-2 border-transparent hover:border-[#E5E5E5] focus:border-[#002FA7] focus:outline-none px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="lg:col-span-4 space-y-4">
              <div className="border border-[#E5E5E5] p-4">
                <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 mb-3">// imagens (URLs)</div>
                {(product.images || []).map((img, i) => (
                  <div key={i} className="flex items-center gap-2 mb-2">
                    <div className="w-12 h-12 bg-[#F7F7F7] border border-[#E5E5E5] flex items-center justify-center overflow-hidden">
                      {img ? <img src={img} alt="" className="w-full h-full object-cover" /> : <ImageIcon size={14} className="text-neutral-400" />}
                    </div>
                    <input
                      value={img}
                      onChange={(e) => {
                        const arr = [...product.images];
                        arr[i] = e.target.value;
                        update({ images: arr });
                      }}
                      className="flex-1 bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none px-2 py-1 text-xs font-mono"
                    />
                    <button
                      onClick={() => update({ images: product.images.filter((_, ix) => ix !== i) })}
                      className="text-[10px] font-mono uppercase tracking-wider text-neutral-500 hover:text-[#E60000]"
                    >
                      remover
                    </button>
                  </div>
                ))}
                <button
                  onClick={() => update({ images: [...(product.images || []), ""] })}
                  className="mt-2 w-full border border-dashed border-[#E5E5E5] hover:border-[#0A0A0A] py-2 text-[10px] font-mono uppercase tracking-wider text-neutral-500 hover:text-[#0A0A0A] transition-colors"
                >
                  + adicionar imagem
                </button>
                <div className="mt-3 text-[10px] text-neutral-500 leading-relaxed">
                  Regra: fundo branco/transparente, alta resolução.
                </div>
              </div>

              {/* Pricing widget */}
              <div className="border-2 border-[#002FA7] p-4 bg-white" data-testid="pricing-widget">
                <div className="flex items-center gap-2 mb-3">
                  <Calculator size={14} className="text-[#002FA7]" />
                  <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-[#002FA7]">// calculadora blindada</span>
                </div>
                <div className="space-y-3">
                  <div>
                    <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">Embalagem (R$)</label>
                    <input
                      type="number"
                      step="0.01"
                      value={packaging}
                      onChange={(e) => setPackaging(parseFloat(e.target.value) || 0)}
                      data-testid="pricing-packaging"
                      className="w-full bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none px-3 py-1.5 text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">Campanhas (R$)</label>
                    <input
                      type="number"
                      step="0.01"
                      value={campaigns}
                      onChange={(e) => setCampaigns(parseFloat(e.target.value) || 0)}
                      data-testid="pricing-campaigns"
                      className="w-full bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none px-3 py-1.5 text-xs font-mono"
                    />
                  </div>
                  <button
                    onClick={calcPrice}
                    disabled={pricingBusy}
                    data-testid="pricing-calc-button"
                    className="w-full bg-[#002FA7] hover:bg-[#00227A] text-white px-3 py-2 text-[10px] font-mono uppercase tracking-wider transition-colors disabled:opacity-60"
                  >
                    {pricingBusy ? "Calculando..." : "Calcular preço sugerido"}
                  </button>
                </div>

                {pricingResult && (
                  <div className="mt-4 pt-4 border-t border-[#E5E5E5]" data-testid="pricing-result">
                    <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">preço sugerido</div>
                    <div className="font-heading text-3xl tracking-tighter font-medium text-[#002FA7]">
                      {money(pricingResult.selling_price)}
                    </div>
                    <div className="grid grid-cols-2 gap-2 mt-2 text-[10px] font-mono">
                      <div>
                        <div className="text-neutral-500">Lucro</div>
                        <div className="text-[#008A00]">{money(pricingResult.breakdown.net_profit)}</div>
                      </div>
                      <div>
                        <div className="text-neutral-500">Margem</div>
                        <div className="text-[#008A00]">
                          {((pricingResult.breakdown.net_profit / pricingResult.selling_price) * 100).toFixed(1)}%
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={applyPrice}
                      data-testid="apply-price-button"
                      className="w-full mt-3 border border-[#002FA7] text-[#002FA7] hover:bg-[#002FA7] hover:text-white px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors"
                    >
                      Aplicar como preço de venda
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {tab === "amazon" && (
          <div className="space-y-5 max-w-4xl">
            <Checkbox label="Habilitar Amazon" checked={product.amazon?.enabled} onChange={(v) => updateAmazon({ enabled: v })} testId="amazon-enabled" />
            <Input label="Categoria Amazon" value={product.amazon?.category} onChange={(v) => updateAmazon({ category: v })} testId="amazon-category" />
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">6 Bullet Points (padrão Amazon)</label>
                <button
                  onClick={genBullets}
                  disabled={aiBusy.bullets}
                  data-testid="ai-generate-bullets"
                  className="border-2 border-[#FF4500] text-[#FF4500] hover:bg-[#FF4500] hover:text-white px-3 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors flex items-center gap-1.5 shadow-[2px_2px_0px_#FF4500] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] disabled:opacity-60"
                >
                  <Sparkles size={10} /> {aiBusy.bullets ? "Gerando..." : "Gerar 6 bullets"}
                </button>
              </div>
              <div className="space-y-2">
                {(product.amazon?.bullet_points || []).map((b, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <div className="w-6 h-8 flex items-center justify-center font-mono text-xs text-neutral-500 bg-[#F7F7F7] border border-[#E5E5E5]">
                      {i + 1}
                    </div>
                    <input
                      value={b}
                      onChange={(e) => {
                        const arr = [...(product.amazon?.bullet_points || [])];
                        arr[i] = e.target.value;
                        updateAmazon({ bullet_points: arr });
                      }}
                      data-testid={`bullet-point-input-${i + 1}`}
                      placeholder={`Bullet point ${i + 1}`}
                      className="flex-1 bg-[#F7F7F7] border-b-2 border-transparent hover:border-[#E5E5E5] focus:border-[#FF9900] focus:outline-none px-3 py-2 text-sm"
                    />
                  </div>
                ))}
              </div>
              <div className="text-[10px] text-neutral-500 mt-2">
                Amazon exige exatamente 6 bullets preenchidos para sincronização.
              </div>
            </div>
          </div>
        )}

        {tab === "shopee" && (
          <div className="space-y-5 max-w-4xl">
            <Checkbox label="Habilitar Shopee" checked={product.shopee?.enabled} onChange={(v) => updateShopee({ enabled: v })} testId="shopee-enabled" />
            <div className="grid grid-cols-2 gap-4">
              <Input label="Categoria Shopee" value={product.shopee?.category} onChange={(v) => updateShopee({ category: v })} testId="shopee-category" />
              <Input label="Variação: Cor" value={product.shopee?.variation_color} onChange={(v) => updateShopee({ variation_color: v })} testId="shopee-color" />
              <Input label="Variação: Tamanho" value={product.shopee?.variation_size} onChange={(v) => updateShopee({ variation_size: v })} testId="shopee-size" />
              <Input label="Peso (kg)" type="number" value={product.shopee?.weight_kg} onChange={(v) => updateShopee({ weight_kg: v })} mono testId="shopee-weight" />
              <Input label="Comprimento (cm)" type="number" value={product.shopee?.length_cm} onChange={(v) => updateShopee({ length_cm: v })} mono testId="shopee-length" />
              <Input label="Largura (cm)" type="number" value={product.shopee?.width_cm} onChange={(v) => updateShopee({ width_cm: v })} mono testId="shopee-width" />
              <Input label="Altura (cm)" type="number" value={product.shopee?.height_cm} onChange={(v) => updateShopee({ height_cm: v })} mono testId="shopee-height" />
            </div>
            <div className="text-[11px] text-neutral-500">
              Peso e dimensões são obrigatórios para cálculo do frete via Shopee Xpress.
            </div>
          </div>
        )}

        {tab === "kwai" && (
          <div className="space-y-5 max-w-4xl">
            <Checkbox label="Habilitar Kwai Shop" checked={product.kwai?.enabled} onChange={(v) => updateKwai({ enabled: v })} testId="kwai-enabled" />
            <div className="grid grid-cols-2 gap-4">
              <Input label="Categoria Kwai" value={product.kwai?.category} onChange={(v) => updateKwai({ category: v })} testId="kwai-category" />
              <Input label="Voltagem (se eletrônico)" value={product.kwai?.voltage} onChange={(v) => updateKwai({ voltage: v })} testId="kwai-voltage" />
            </div>
            <div>
              <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">Especificações técnicas</label>
              <textarea
                value={product.kwai?.tech_specs || ""}
                onChange={(e) => updateKwai({ tech_specs: e.target.value })}
                rows={4}
                data-testid="kwai-specs"
                className="w-full bg-[#F7F7F7] border-b-2 border-transparent hover:border-[#E5E5E5] focus:border-[#FF3B30] focus:outline-none px-3 py-2 text-sm"
              />
            </div>
            <div className="text-[11px] text-neutral-500">
              Kwai Shop exige campos técnicos específicos conforme a categoria. Aprovação via API.
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
