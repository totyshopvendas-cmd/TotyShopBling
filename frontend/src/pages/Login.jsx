import React, { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { toast } from "sonner";

export default function Login() {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/dashboard" replace />;

  const handleGoogle = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password, name);
      }
      toast.success(mode === "login" ? "Bem-vindo de volta!" : "Conta criada com sucesso!");
      navigate("/dashboard");
    } catch (err) {
      const msg = err?.response?.data?.detail || "Erro na autenticação";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2" data-testid="login-page">
      {/* LEFT: form */}
      <div className="flex flex-col justify-center px-8 lg:px-20 py-16 bg-white">
        <div className="max-w-sm mx-auto w-full">
          <div className="flex items-center gap-2 mb-12">
            <div className="w-8 h-8 bg-[#002FA7] flex items-center justify-center">
              <span className="text-white font-heading font-bold">B</span>
            </div>
            <span className="font-heading font-semibold tracking-tight text-lg">BlingDrop</span>
          </div>

          <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500 mb-2">
            {mode === "login" ? "// acesso" : "// nova conta"}
          </div>
          <h1 className="font-heading text-4xl tracking-tighter font-medium mb-3 text-[#0A0A0A]">
            {mode === "login" ? "Entre no painel" : "Crie sua conta"}
          </h1>
          <p className="text-sm text-neutral-500 mb-10 leading-relaxed">
            Gestão de catálogo JohnDrop → Bling com SEO otimizado para Amazon, Shopee e Kwai Shop.
          </p>

          <button
            type="button"
            onClick={handleGoogle}
            data-testid="google-login-button"
            className="w-full border border-[#E5E5E5] hover:border-[#0A0A0A] px-4 py-3 flex items-center justify-center gap-3 transition-colors mb-4"
          >
            <svg width="18" height="18" viewBox="0 0 48 48">
              <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32 29.3 35 24 35c-6.1 0-11-4.9-11-11s4.9-11 11-11c2.8 0 5.3 1 7.2 2.7l5.7-5.7C33.3 7 28.9 5 24 5 13.5 5 5 13.5 5 24s8.5 19 19 19 19-8.5 19-19c0-1.2-.1-2.5-.4-3.5z"/>
              <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 16.2 19 13 24 13c2.8 0 5.3 1 7.2 2.7l5.7-5.7C33.3 7 28.9 5 24 5 16.3 5 9.7 9 6.3 14.7z"/>
              <path fill="#4CAF50" d="M24 43c4.8 0 9.2-1.8 12.5-4.9l-5.8-4.9C28.7 34.6 26.4 35 24 35c-5.3 0-9.7-3-11.3-8l-6.5 5C9.6 38.9 16.2 43 24 43z"/>
              <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.2-4.3 5.6l5.8 4.9C40 35.9 43 30.5 43 24c0-1.2-.1-2.5-.4-3.5z"/>
            </svg>
            <span className="font-medium text-sm">Entrar com Google</span>
          </button>

          <div className="flex items-center gap-3 my-4">
            <div className="flex-1 h-px bg-[#E5E5E5]" />
            <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-400">ou</span>
            <div className="flex-1 h-px bg-[#E5E5E5]" />
          </div>

          <form onSubmit={onSubmit} className="space-y-3">
            {mode === "register" && (
              <div>
                <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">Nome</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  data-testid="register-name-input"
                  className="w-full bg-[#F7F7F7] border-b-2 border-transparent hover:border-[#E5E5E5] focus:border-[#002FA7] focus:outline-none px-3 py-2 text-sm transition-colors"
                />
              </div>
            )}
            <div>
              <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">E-mail</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                data-testid="login-email-input"
                className="w-full bg-[#F7F7F7] border-b-2 border-transparent hover:border-[#E5E5E5] focus:border-[#002FA7] focus:outline-none px-3 py-2 text-sm transition-colors"
              />
            </div>
            <div>
              <label className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 block mb-1">Senha</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                data-testid="login-password-input"
                className="w-full bg-[#F7F7F7] border-b-2 border-transparent hover:border-[#E5E5E5] focus:border-[#002FA7] focus:outline-none px-3 py-2 text-sm transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              data-testid="login-submit-button"
              className="w-full bg-[#002FA7] hover:bg-[#00227A] disabled:opacity-60 text-white px-4 py-3 font-medium text-sm transition-colors"
            >
              {submitting ? "Processando..." : mode === "login" ? "Entrar" : "Criar conta"}
            </button>
          </form>

          <button
            onClick={() => setMode(mode === "login" ? "register" : "login")}
            className="mt-6 text-xs text-neutral-500 hover:text-[#002FA7] transition-colors"
            data-testid="toggle-auth-mode"
          >
            {mode === "login" ? "Não tem conta? Cadastre-se →" : "Já tenho conta →"}
          </button>
        </div>
      </div>

      {/* RIGHT: image */}
      <div
        className="hidden lg:block relative bg-neutral-100"
        style={{
          backgroundImage: `url(https://images.pexels.com/photos/3137072/pexels-photo-3137072.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940)`,
          backgroundSize: "cover",
          backgroundPosition: "center",
          filter: "grayscale(1)",
        }}
      >
        <div className="absolute inset-0 bg-black/30" />
        <div className="absolute bottom-10 left-10 right-10 text-white">
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] mb-3 opacity-80">
            // dropshipping brasil
          </div>
          <p className="font-heading text-3xl tracking-tighter font-medium leading-tight max-w-md">
            Do catálogo JohnDrop<br/>ao checkout, sem ruptura.
          </p>
        </div>
      </div>
    </div>
  );
}
