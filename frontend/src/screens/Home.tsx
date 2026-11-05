import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../api";
import BoxCard from "../components/BoxCard";
import { ActionsButton, ProfileButton } from "../components/HeaderButtons";
import Icon from "../components/Icon";
import { formatClock, parseDate } from "../format";
import { isRunning, useLatestRuns } from "../hooks/useLatestRuns";
import ActionsSheet from "../sheets/ActionsSheet";
import type { BoxSummary, ClaudeStatus, LatestRuns } from "../types";

function ClaudeState() {
  const status = useQuery({ queryKey: ["claude-status"], queryFn: () => apiGet<ClaudeStatus>("/api/claude/status") });
  const runs = useLatestRuns();
  if (status.isPending) return <span className="claude-state" />;
  if (status.data && !status.data.connected) {
    return (
      <span className="claude-state warn"><span className="dot" style={{ background: "#C2410C" }} />Claude déconnecté</span>
    );
  }
  if (isRunning(runs.data)) {
    return (
      <span className="claude-state" role="status">
        <span className="dot" style={{ background: "#1F6FEB" }} />Analyse en cours…
      </span>
    );
  }
  const finished = [runs.data?.full?.finished_at, runs.data?.light?.finished_at]
    .filter((x): x is string => !!x)
    .sort((a, b) => parseDate(b).getTime() - parseDate(a).getTime())[0];
  return (
    <span className="claude-state">
      <span className="dot" style={{ background: "#16A34A" }} />
      {finished ? `Claude · analysé à ${formatClock(finished)}` : "Claude · pas encore d'analyse"}
    </span>
  );
}

function nextRun(runs?: LatestRuns): string | null {
  const times = [runs?.next_full_at, runs?.next_light_at].filter((x): x is string => !!x);
  if (times.length === 0) return null;
  return times.sort((a, b) => parseDate(a).getTime() - parseDate(b).getTime())[0];
}

export default function Home() {
  const navigate = useNavigate();
  const [sheet, setSheet] = useState(false);
  const boxes = useQuery({ queryKey: ["boxes"], queryFn: () => apiGet<BoxSummary[]>("/api/boxes/summary") });
  const runs = useLatestRuns();
  const next = nextRun(runs.data);

  return (
    <main className="home">
      <header className="home-header">
        <div className="bar">
          <ClaudeState />
          <div className="bar-actions">
            <ActionsButton onClick={() => setSheet(true)} />
            <ProfileButton />
          </div>
        </div>
        <h1 className="big-title">Mes boîtes</h1>
        {next && <span className="muted small">Prochaine analyse à {formatClock(next)}</span>}
      </header>
      <div className="home-body">
        {boxes.isPending && <p className="muted pad">Chargement…</p>}
        {boxes.isError && (
          <p className="form-error" role="alert">
            Impossible de charger les boîtes. <button type="button" className="link-btn" onClick={() => void boxes.refetch()}>Réessayer</button>
          </p>
        )}
        <div className="box-grid">
          {boxes.data?.map((b) => (
            <BoxCard key={b.id} box={b} onPick={() => navigate(`/box/${b.id}/inbox`)} />
          ))}
        </div>
        {boxes.data && (
          <button type="button" className="add-box" onClick={() => navigate("/settings/boxes/new")}>
            <Icon name="plus" size={16} stroke="currentColor" width={2.4} />
            Ajouter une boîte mail
          </button>
        )}
      </div>
      {sheet && <ActionsSheet account="all" onClose={() => setSheet(false)} />}
    </main>
  );
}
