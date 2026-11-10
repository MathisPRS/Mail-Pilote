import { useState } from "react";
import Icon from "../components/Icon";
import RunBadge from "../components/RunBadge";
import Sheet from "../components/Sheet";
import { formatClock, parseDate, plural } from "../format";
import { isRunning, useLatestRuns } from "../hooks/useLatestRuns";
import { useMailActions } from "../hooks/useMailActions";
import type { LatestRuns, Run, RunStep } from "../types";

const STEP_LABEL: Record<RunStep, string> = {
  sync: "Récupération des nouveaux mails",
  bodies: "Lecture du contenu des mails",
  classify: "Claude trie les mails",
  alerts: "Envoi des alertes",
};

function latestRun(runs?: LatestRuns): Run | null {
  const all = [runs?.light, runs?.full].filter((r): r is Run => !!r);
  if (all.length === 0) return null;
  const ts = (r: Run) => (r.started_at ? parseDate(r.started_at).getTime() : 0);
  return all.sort((a, b) => ts(b) - ts(a) || (b.id ?? 0) - (a.id ?? 0))[0];
}

function nextRun(runs?: LatestRuns): string | null {
  const times = [runs?.next_full_at, runs?.next_light_at].filter((x): x is string => !!x);
  if (times.length === 0) return null;
  return times.sort((a, b) => parseDate(a).getTime() - parseDate(b).getTime())[0];
}

function RunningStatus({ run }: { run: Run }) {
  const kind = run.kind === "full" ? "Analyse complète" : "Vérification rapide";
  const origin = run.trigger === "manual" ? "lancée manuellement" : "planifiée";
  const started = formatClock(run.started_at);
  const step = run.step ? STEP_LABEL[run.step] : "Démarrage…";
  const progress = run.step === "classify" && run.total > 0;
  return (
    <div className="run-status" role="status">
      <div className="run-line">
        <span className="run-spinner" aria-hidden="true" />
        <strong>{kind}</strong>
      </div>
      <span className="run-meta">{origin}{started ? ` · depuis ${started}` : ""}</span>
      <span>{progress ? `${step} · ${run.mails_count} / ${run.total}` : step}</span>
      {progress && (
        <div className="meter" role="progressbar" aria-label="Progression de l'analyse" aria-valuemin={0} aria-valuemax={run.total} aria-valuenow={run.mails_count}>
          <div style={{ width: `${Math.min(100, (run.mails_count / run.total) * 100)}%` }} />
        </div>
      )}
    </div>
  );
}

function FinishedStatus({ run }: { run: Run }) {
  const at = formatClock(run.finished_at ?? run.started_at);
  const head = `Dernière analyse · ${at} · ${plural(run.mails_count, "mail analysé", "mails analysés")}`;
  return (
    <div className="run-status">
      <span>{head}</span>
      <RunBadge run={run} />
    </div>
  );
}

/** « Lancer manuellement » : analyse complète et nettoyage des pubs/spams, avec le suivi de l'analyse. */
export default function ActionsSheet({ account, onClose }: { account: string; onClose: () => void }) {
  const { runAnalysis, cleanup } = useMailActions();
  const runs = useLatestRuns();
  const [cleaning, setCleaning] = useState(false);
  const running = isRunning(runs.data);
  const run = latestRun(runs.data);
  const current = running ? (runs.data?.light?.status === "running" ? runs.data.light : runs.data?.full) ?? run : run;
  const next = nextRun(runs.data);

  const clean = async () => {
    setCleaning(true);
    try {
      await cleanup(account);
    } finally {
      setCleaning(false);
    }
  };

  return (
    <Sheet label="Actions manuelles" onClose={onClose}>
      <div className="sheet-scroll">
        <span className="sheet-section first">Lancer manuellement</span>
        <button type="button" className="action-row" disabled={running} onClick={() => void runAnalysis()}>
          <span className="action-icon" style={{ background: "#1F6FEB" }}><Icon name="search" size={18} stroke="#fff" width={2} /></span>
          <span className="action-text">
            <strong>Lancer une analyse</strong>
            <span>{running ? "Analyse en cours…" : "Claude lit les nouveaux mails de toutes les boîtes"}</span>
          </span>
        </button>
        <button type="button" className="action-row" disabled={cleaning} onClick={() => void clean()}>
          <span className="action-icon" style={{ background: "#C2410C" }}><Icon name="trash" size={18} stroke="#fff" width={2} /></span>
          <span className="action-text">
            <strong>Nettoyer pubs et spams</strong>
            <span>{cleaning ? "Nettoyage en cours…" : "Déplace les pubs et spams de la réception vers la corbeille, annulable"}</span>
          </span>
        </button>
        <span className="sheet-section">Suivi</span>
        {runs.isPending && <span className="run-status muted small">Chargement…</span>}
        {!runs.isPending && current && (current.status === "running" ? <RunningStatus run={current} /> : <FinishedStatus run={current} />)}
        {!runs.isPending && !current && <span className="run-status muted">Aucune analyse pour l'instant</span>}
        {next && <span className="muted small run-next">Prochaine analyse à {formatClock(next)}</span>}
      </div>
    </Sheet>
  );
}
