import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getAuthStatus } from "./api";
import Login from "./screens/Login";

/** Garde : exige une session ouverte, sinon /login. Les écrans futurs se rangent sous cette route. */
function RequireAuth() {
  const status = useQuery({ queryKey: ["auth-status"], queryFn: getAuthStatus });
  if (status.isPending) return <main className="auth-page"><p className="muted">Chargement…</p></main>;
  if (status.isError || !status.data.setup_done || !status.data.authenticated) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

function Home() {
  return (
    <main className="page">
      <h1>Accueil</h1>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Home />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
