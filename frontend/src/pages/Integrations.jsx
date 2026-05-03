import React, { useEffect, useState } from "react";
import Layout, { PageHeader } from "../components/Layout";
import { api } from "../lib/api";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, XCircle, MessageSquare, Zap, Download, Sparkles } from "lucide-react";

const SERVICES = [
  {
    key: "johndrop",
    name: "JohnDrop",
    color: "#002FA7",
    description: "Fornecedor dropshipping. Envia produtos direto ao cliente final.",
    role: "Fonte do catálogo e estoque",
  },
  {
    key: "bling",
    name: "Bling ERP",
    color: "#0A0A0A",
    description: "Centraliza gestão, emite NF e exporta para marketplaces.",
    role: "Hub de integração",
  },
  {
    key: "make",
    name: "Make.com",
    color: "#6D00CC",
    description: "Automação da sincronização de estoque JohnDrop → Bling.",
    role: "Automação",
  },
  {
    key: "discord",
    name: "Discord Webhook",
    color: "#5865F2",
    description: "Notificações de variação de estoque e erros de integração.",
    role: "Alertas",
  },
];

export default function Integrations() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [discordHook, setDiscordHook] = useState("");
  const [jdEmail, setJdEmail] = useState("");
  const [jdPassword, setJdPassword] = useState("");
  const [jdConnecting, setJdConnecting] = useState(false);
  const navigate = useNavigate();

  const load = async () => {
    try {
      const { data } = await api.get("/integrations/status");
      setStatus(data);
      setDiscordHook(data?.discord?.webhook || "");
      if (data?.johndrop?.email) setJdEmail(data.johndrop.email);
    } catch (_e) { toast.error("Falha ao carregar"); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const toggle = async (service, connected, webhook) => {
    try {
      const { data } = await api.post("/integrations/toggle", { service, connected, webhook });
      setStatus(data);
      toast.success(connected ? "Conectado" : "Desconectado");
    } catch (_e) { toast.error("Falha"); }
  };

  const connectBling = async () => {
    try {
      const { data } = await api.get("/bling/authorize-url");
      window.location.href = data.url;
    } catch (_e) { toast.error("Falha ao iniciar OAuth Bling"); }
  };

  const disconnectBling = async () => {
    try {
      await api.post("/bling/disconnect");
      toast.success("Bling desconectada");
      await load();
    } catch (_e) { toast.error("Falha"); }
  };

  const connectJohnDrop = async () => {
    if (!jdEmail || !jdPassword) {
      toast.error("Email e senha obrigatórios");
      return;
    }
    setJdConnecting(true);
    try {
      await api.post("/johndrop/connect", { email: jdEmail, password: jdPassword });
      toast.success("JohnDrop conectada com sucesso!");
      setJdPassword("");
      await load();
      setTimeout(() => navigate("/johndrop-catalog"), 1200);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Falha ao conectar");
    } finally {
      setJdConnecting(false);
    }
  };

  const disconnectJohnDrop = async () => {
    try {
      await api.post("/johndrop/disconnect");
      toast.success("JohnDrop desconectada");
      setJdPassword("");
      await load();
    } catch (_e) { toast.error("Falha"); }
  };

  return (
    <Layout>
      <PageHeader
        overline="// infraestrutura"
        title="Integrações"
        description="Conexões ativas entre JohnDrop, Bling e ferramentas de automação. Tokens inválidos interrompem a sincronização e exigem reautorização."
      />

      <div className="p-8 space-y-6">
        {loading || !status ? (
          <div className="font-mono text-xs text-neutral-500 uppercase tracking-wider">carregando<span className="ai-cursor"/></div>
        ) : (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {SERVICES.map((s) => {
                const st = status[s.key] || {};
                const connected = !!st.connected;
                return (
                  <div key={s.key} className="border border-[#E5E5E5] p-6 hover:border-[#0A0A0A] transition-colors" data-testid={`integration-${s.key}`}>
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 flex items-center justify-center" style={{ background: s.color }}>
                          <span className="text-white font-heading font-bold">{s.name[0]}</span>
                        </div>
                        <div>
                          <div className="font-heading text-lg font-medium tracking-tight">{s.name}</div>
                          <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">{s.role}</div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {connected ? <CheckCircle2 size={14} className="text-[#008A00]" /> : <XCircle size={14} className="text-neutral-400" />}
                        <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: connected ? "#008A00" : "#A3A3A3" }}>
                          {connected ? "conectado" : "desconectado"}
                        </span>
                      </div>
                    </div>
                    <p className="text-sm text-neutral-600 mb-4 leading-relaxed">{s.description}</p>

                    {st.last_sync && (
                      <div className="font-mono text-[10px] text-neutral-500 mb-3">
                        última sincronização: {new Date(st.last_sync).toLocaleString("pt-BR")}
                      </div>
                    )}

                    {(s.key === "bling" || s.key === "johndrop") && (
                      <div className="border-t border-[#E5E5E5] pt-3 mt-3">
                        <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 mb-1">token</div>
                        <div className="flex items-center gap-2">
                          <span className="w-1.5 h-1.5" style={{ background: st.token_valid ? "#008A00" : "#E60000" }} />
                          <span className="font-mono text-xs" style={{ color: st.token_valid ? "#008A00" : "#E60000" }}>
                            {st.token_valid ? "válido" : "inválido / expirado"}
                          </span>
                        </div>
                      </div>
                    )}

                    {s.key === "discord" && (
                      <div className="mt-3">
                        <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">Webhook URL</label>
                        <input
                          value={discordHook}
                          onChange={(e) => setDiscordHook(e.target.value)}
                          placeholder="https://discord.com/api/webhooks/..."
                          data-testid="discord-webhook-input"
                          className="w-full bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none px-3 py-2 text-xs font-mono"
                        />
                      </div>
                    )}

                    <div className="flex gap-2 mt-4">
                      {s.key === "johndrop" ? (
                        connected ? (
                          <button
                            onClick={disconnectJohnDrop}
                            data-testid="toggle-johndrop"
                            className="flex-1 px-4 py-2 text-xs font-mono uppercase tracking-wider border border-[#E5E5E5] hover:border-[#E60000] hover:text-[#E60000] transition-colors"
                          >
                            Desconectar
                          </button>
                        ) : null
                      ) : (
                        <button
                          onClick={() => toggle(s.key, !connected, s.key === "discord" ? discordHook : undefined)}
                          data-testid={`toggle-${s.key}`}
                          className={`flex-1 px-4 py-2 text-xs font-mono uppercase tracking-wider transition-colors ${connected ? "border border-[#E5E5E5] hover:border-[#E60000] hover:text-[#E60000]" : "bg-[#002FA7] hover:bg-[#00227A] text-white"}`}
                        >
                          {connected ? "Desconectar" : "Conectar"}
                        </button>
                      )}
                    </div>

                    {/* JohnDrop real login form */}
                    {s.key === "johndrop" && !connected && (
                      <div className="mt-3 space-y-2 border-t border-[#E5E5E5] pt-3">
                        <div className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">// credenciais jonhdrop</div>
                        <input
                          type="email"
                          placeholder="email@jonhdrop.com.br"
                          value={jdEmail}
                          onChange={(e) => setJdEmail(e.target.value)}
                          data-testid="jd-email-input"
                          className="w-full bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none px-3 py-2 text-sm font-mono"
                        />
                        <input
                          type="password"
                          placeholder="senha"
                          value={jdPassword}
                          onChange={(e) => setJdPassword(e.target.value)}
                          data-testid="jd-password-input"
                          className="w-full bg-[#F7F7F7] border-b-2 border-transparent focus:border-[#002FA7] focus:outline-none px-3 py-2 text-sm font-mono"
                        />
                        <button
                          onClick={connectJohnDrop}
                          disabled={jdConnecting}
                          data-testid="jd-connect-button"
                          className="w-full bg-[#002FA7] hover:bg-[#00227A] text-white px-4 py-2 text-xs font-mono uppercase tracking-wider transition-colors disabled:opacity-60"
                        >
                          {jdConnecting ? "Testando login..." : "Conectar JohnDrop"}
                        </button>
                        <div className="text-[10px] text-neutral-500 leading-relaxed">
                          Credenciais criptografadas no servidor. Usadas apenas para acessar seu catálogo e importar produtos.
                        </div>
                      </div>
                    )}

                    {s.key === "johndrop" && connected && (
                      <>
                        <div className="mt-3 font-mono text-[10px] text-neutral-500">
                          conectado como: <span className="text-[#0A0A0A]">{st.email}</span>
                        </div>
                        <button
                          onClick={() => navigate("/johndrop-catalog")}
                          data-testid="goto-jd-catalog"
                          className="w-full mt-2 border-2 border-[#002FA7] text-[#002FA7] hover:bg-[#002FA7] hover:text-white px-4 py-2 text-xs font-mono uppercase tracking-wider flex items-center justify-center gap-2 transition-colors shadow-[2px_2px_0px_#002FA7] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px]"
                        >
                          <Download size={12} />
                          Ver catálogo sem integração →
                        </button>
                      </>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="border border-[#E5E5E5] p-6 bg-[#FAFAFA]">
              <div className="flex items-start gap-3">
                <Zap size={18} className="text-[#FF4500] mt-0.5 shrink-0" />
                <div>
                  <div className="font-heading text-sm font-medium mb-1">Gestão de erros de integração</div>
                  <p className="text-xs text-neutral-600 leading-relaxed">
                    Falhas comuns como tokens inválidos desconectam o vínculo entre JohnDrop e Bling, exigindo a renovação da autorização
                    para que o catálogo e o estoque voltem a sincronizar. Mantenha os tokens sempre ativos e monitore os alertas no Discord.
                  </p>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
