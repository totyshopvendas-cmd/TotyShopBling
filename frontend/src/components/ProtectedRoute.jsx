import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center font-mono text-xs tracking-wider uppercase text-neutral-500">
        carregando<span className="ai-cursor"></span>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}
