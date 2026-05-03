import React, { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { toast } from "sonner";

export default function BlingCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const processed = useRef(false);
  const [status, setStatus] = useState("Conectando com Bling...");

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    const state = params.get("state");
    const error = params.get("error");

    if (error) {
      toast.error(`Bling: ${params.get("error_description") || error}`);
      navigate("/integrations", { replace: true });
      return;
    }
    if (!code || !state) {
      toast.error("Parâmetros inválidos do callback Bling");
      navigate("/integrations", { replace: true });
      return;
    }

    (async () => {
      try {
        setStatus("Trocando código por token...");
        await api.post("/bling/callback", { code, state });
        toast.success("Bling conectada com sucesso!");
        setTimeout(() => navigate("/bling-catalog", { replace: true }), 500);
      } catch (err) {
        const msg = err?.response?.data?.detail || "Falha na autorização";
        toast.error(msg);
        navigate("/integrations", { replace: true });
      }
    })();
  }, [location.search, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="font-mono text-xs uppercase tracking-[0.2em] text-neutral-500">
        {status}<span className="ai-cursor"></span>
      </div>
    </div>
  );
}
