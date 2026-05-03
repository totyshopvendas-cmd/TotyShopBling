import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { LayoutDashboard, Package, RefreshCw, Plug, LogOut, Calculator, Download, CheckSquare } from "lucide-react";

const NavItem = ({ to, icon: Icon, children, testId }) => (
  <NavLink
    to={to}
    data-testid={testId}
    className={({ isActive }) =>
      `flex items-center gap-3 px-4 py-2.5 border-l-2 font-mono text-xs tracking-wider uppercase transition-colors ${
        isActive
          ? "border-[#002FA7] bg-[#F7F7F7] text-[#0A0A0A]"
          : "border-transparent text-neutral-500 hover:text-[#0A0A0A] hover:bg-[#F7F7F7]"
      }`
    }
  >
    <Icon size={16} />
    <span>{children}</span>
  </NavLink>
);

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const onLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-white flex">
      {/* Sidebar */}
      <aside className="w-60 border-r border-[#E5E5E5] bg-white flex flex-col" data-testid="app-sidebar">
        <div className="h-16 border-b border-[#E5E5E5] flex items-center px-5">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-[#002FA7] flex items-center justify-center">
              <span className="text-white font-heading font-bold text-sm">B</span>
            </div>
            <span className="font-heading font-semibold tracking-tight text-[#0A0A0A]">
              BlingDrop
            </span>
          </div>
        </div>

        <nav className="flex-1 py-4 flex flex-col gap-0.5">
          <NavItem to="/dashboard" icon={LayoutDashboard} testId="sidebar-nav-dashboard">
            Dashboard
          </NavItem>
          <NavItem to="/products" icon={Package} testId="sidebar-nav-products">
            Produtos
          </NavItem>
          <NavItem to="/johndrop-catalog" icon={Download} testId="sidebar-nav-jd-catalog">
            Catálogo JohnDrop
          </NavItem>
          <NavItem to="/pricing" icon={Calculator} testId="sidebar-nav-pricing">
            Calculadora
          </NavItem>
          <NavItem to="/integrations" icon={Plug} testId="sidebar-nav-integrations">
            Integrações
          </NavItem>
        </nav>

        <div className="border-t border-[#E5E5E5] p-4 space-y-2">
          <div className="flex items-center gap-2 min-w-0">
            {user?.picture ? (
              <img src={user.picture} alt="" className="w-8 h-8 object-cover" />
            ) : (
              <div className="w-8 h-8 bg-[#EBEBEB] flex items-center justify-center font-heading text-xs">
                {(user?.name || "U").slice(0,1).toUpperCase()}
              </div>
            )}
            <div className="min-w-0">
              <div className="text-xs font-medium truncate" data-testid="user-name">{user?.name}</div>
              <div className="text-[10px] text-neutral-500 truncate font-mono">{user?.email}</div>
            </div>
          </div>
          <button
            onClick={onLogout}
            data-testid="logout-button"
            className="w-full flex items-center gap-2 justify-center border border-[#E5E5E5] hover:border-[#0A0A0A] px-3 py-1.5 text-xs font-mono uppercase tracking-wider transition-colors"
          >
            <LogOut size={12} /> Sair
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 bg-white">{children}</main>
    </div>
  );
}

export const PageHeader = ({ overline, title, description, actions }) => (
  <header className="border-b border-[#E5E5E5] bg-white px-8 py-6" data-testid="page-header">
    <div className="flex items-start justify-between gap-4">
      <div>
        {overline && (
          <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-neutral-500 mb-1">
            {overline}
          </div>
        )}
        <h1 className="font-heading text-3xl tracking-tighter font-medium text-[#0A0A0A]">{title}</h1>
        {description && <p className="text-sm text-neutral-500 mt-1 max-w-2xl">{description}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  </header>
);
