import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getAuthStatus } from "./api";
import Home from "./screens/Home";
import Login from "./screens/Login";
import MailShell from "./screens/MailShell";

/** Garde : exige une session ouverte, sinon /login. Les écrans futurs se rangent sous cette route. */
function RequireAuth() {
  const status = useQuery({ queryKey: ["auth-status"], queryFn: getAuthStatus });
  if (status.isPending) return <main className="auth-page"><p className="muted">Chargement…</p></main>;
  if (status.isError || !status.data.setup_done || !status.data.authenticated) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

/** Placeholder : l'écran Réglages arrive avec la tâche 14. */
function SettingsPlaceholder() {
  return (
    <main className="page">
      <h1>Réglages</h1>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Home />} />
        <Route path="/box/:account/:folder/*" element={<MailShell />} />
        <Route path="/mail/:id" element={<MailShell />} />
        <Route path="/settings" element={<SettingsPlaceholder />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
