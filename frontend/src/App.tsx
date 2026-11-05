import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getAuthStatus } from "./api";
import { RunWatcher } from "./hooks/useLatestRuns";
import Home from "./screens/Home";
import Login from "./screens/Login";
import MailShell from "./screens/MailShell";
import Alerts from "./settings/Alerts";
import AddBox from "./settings/AddBox";
import Boxes from "./settings/Boxes";
import ClaudePage from "./settings/ClaudePage";
import Profile from "./settings/Profile";
import Schedule from "./settings/Schedule";

/** Garde : exige une session ouverte, sinon /login. Les écrans futurs se rangent sous cette route. */
function RequireAuth() {
  const status = useQuery({ queryKey: ["auth-status"], queryFn: getAuthStatus });
  if (status.isPending) return <main className="auth-page"><p className="muted">Chargement…</p></main>;
  if (status.isError || !status.data.setup_done || !status.data.authenticated) {
    return <Navigate to="/login" replace />;
  }
  return (
    <>
      <RunWatcher />
      <Outlet />
    </>
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
        <Route path="/settings" element={<Profile />} />
        <Route path="/settings/boxes" element={<Boxes />} />
        <Route path="/settings/boxes/new" element={<AddBox />} />
        <Route path="/settings/claude" element={<ClaudePage />} />
        <Route path="/settings/schedule" element={<Schedule />} />
        <Route path="/settings/alerts" element={<Alerts />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
