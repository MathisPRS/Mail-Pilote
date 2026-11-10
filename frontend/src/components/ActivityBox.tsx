import { useNavigate } from "react-router-dom";
import { formatSince, plural } from "../format";
import { useActivity, useMarkSeen } from "../hooks/useActivity";
import Icon from "./Icon";
import type { ActivitySummary } from "../types";

/** Compteurs non nuls, dans l'ordre d'affichage (singulier / pluriel accordés). */
export function activityChips(s: ActivitySummary): string[] {
  const chips: [number, string, string][] = [
    [s.analysed, "mail trié", "mails triés"],
    [s.important, "important", "importants"],
    [s.tt, "TT+", "TT+"],
    [s.ads, "pub/spam", "pubs/spams"],
    [s.alerts, "alerte", "alertes"],
    [s.actions, "action", "actions"],
  ];
  return chips.filter(([n]) => n > 0).map(([n, one, many]) => plural(n, one, many));
}

/** « Pendant ton absence » : résumé de ce que l'appli a fait depuis la dernière visite (accueil). */
export default function ActivityBox() {
  const navigate = useNavigate();
  const { data } = useActivity();
  const markSeen = useMarkSeen();
  const chips = data ? activityChips(data.summary) : [];
  if (!data || chips.length === 0) return null;
  return (
    <div className="activity-wrap">
      <button type="button" className="activity-box" onClick={() => navigate("/activity")}>
        <span className="activity-title">
          <Icon name="clock" size={15} stroke="var(--accent)" width={2} />
          Pendant ton absence
        </span>
        <span className="muted small">depuis {formatSince(data.since)}</span>
        <span className="activity-chips">
          {chips.map((c) => <span key={c} className="activity-chip">{c}</span>)}
        </span>
      </button>
      <button type="button" className="activity-dismiss" aria-label="Masquer" onClick={() => void markSeen()}>
        <Icon name="close" size={16} width={2.2} />
      </button>
    </div>
  );
}
