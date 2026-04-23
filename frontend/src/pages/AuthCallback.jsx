import React, { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";

export default function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = location.hash || "";
    const match = hash.match(/session_id=([^&]+)/);
    const sessionId = match ? decodeURIComponent(match[1]) : null;
    if (!sessionId) { navigate("/login", { replace: true }); return; }

    (async () => {
      try {
        const { data } = await api.post("/auth/session", { session_id: sessionId });
        setUser(data.user);
        navigate("/dashboard", { replace: true, state: { user: data.user } });
      } catch (_e) {
        navigate("/login", { replace: true });
      }
    })();
  }, [location.hash, navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="font-mono text-xs uppercase tracking-[0.2em] text-neutral-500">
        autenticando<span className="ai-cursor"></span>
      </div>
    </div>
  );
}
