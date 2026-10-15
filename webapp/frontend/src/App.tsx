import { Routes, Route, Link, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import SpaceWizard from "./pages/SpaceWizard";
import Workbench from "./pages/Workbench";
import Analytics from "./pages/Analytics";
import History from "./pages/History";
import DescriptorLab from "./pages/DescriptorLab";

export default function App() {
  const loc = useLocation();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <Link to="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white font-bold">
              e
            </div>
            <span className="font-semibold text-slate-800">edbo 贝叶斯优化平台</span>
          </Link>
          {loc.pathname !== "/" && (
            <Link to="/" className="text-sm text-slate-500 hover:text-brand-600">
              ← 返回项目列表
            </Link>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/projects/:id/space" element={<SpaceWizard />} />
          <Route path="/projects/:id/rebuild" element={<SpaceWizard rebuild />} />
          <Route path="/projects/:id" element={<Workbench />} />
          <Route path="/projects/:id/history" element={<History />} />
          <Route path="/projects/:id/analytics" element={<Analytics />} />
          <Route path="/projects/:id/descriptors" element={<DescriptorLab />} />
        </Routes>
      </main>
    </div>
  );
}
