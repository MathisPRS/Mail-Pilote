import { useState } from "react";
import { useNavigate } from "react-router-dom";
import MailRow from "../components/MailRow";
import RunBadge from "../components/RunBadge";
import { formatClock, formatSince, plural } from "../format";
import { useActivity, useMarkSeen } from "../hooks/useActivity";
import { useDismissOutside } from "../hooks/useLongPress";
import { useMailActions } from "../hooks/useMailActions";
import SettingsLayout, { Group } from "../settings/SettingsLayout";
import type { ActivityBatch, Message, MessageAction, Run } from "../types";

const ACTION_LABEL: Record<MessageAction, string> = {
  trash: "corbeille", archive: "archivés", move: "déplacés", important: "marqués importants",
  read: "lus", unread: "non lus",
};

const RUN_KIND_LABEL: Record<Run["kind"], string> = { full: "Tri complet", light: "Vérification rapide", sync: "Synchronisation" };

/** Liste de mails réutilisant MailRow : toucher = ouvrir, appui long = actions (comme la liste). */
function MailRows({ section, mails, expanded, setExpanded }: {
  section: string; mails: Message[]; expanded: string | null; setExpanded: (k: string | null) => void;
}) {
  const navigate = useNavigate();
  const { perform } = useMailActions();
  const act = async (id: number, action: "archive" | "important" | "trash") => {
    if (await perform({ ids: [id], action })) setExpanded(null);
  };
  return (
    <>
      {mails.map((m) => {
        const key = `${section}:${m.id}`;
        return (
          <MailRow
            key={key}
            mail={m}
            selecting={false}
            selected={false}
            expanded={expanded === key}
            active={false}
            onTap={() => { setExpanded(null); navigate(`/activity/mail/${m.id}`); }}
            onToggleActions={() => setExpanded(expanded === key ? null : key)}
            onArchive={() => void act(m.id, "archive")}
            onImportant={() => void act(m.id, "important")}
            onTrash={() => void act(m.id, "trash")}
          />
        );
      })}
    </>
  );
}

function BatchRow({ batch, expanded, setExpanded, onUndo }: {
  batch: ActivityBatch; expanded: string | null; setExpanded: (k: string | null) => void; onUndo: () => void;
}) {
  const key = `batch:${batch.batch_id}`;
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className="activity-batch-head">
        <button type="button" className="activity-batch" aria-expanded={open} onClick={() => setOpen(!open)}>
          <strong>{formatClock(batch.at)} · {plural(batch.count, "mail", "mails")} → {ACTION_LABEL[batch.action]}</strong>
          <span className="muted">{batch.source === "user" ? "par toi" : "par Mail Pilot"}</span>
        </button>
        {batch.undone ? (
          <span className="activity-done">Annulé</span>
        ) : (
          <button type="button" className="activity-undo" onClick={onUndo}>Annuler</button>
        )}
      </div>
      {open && (
        <div className="activity-batch-mails">
          <MailRows section={key} mails={batch.messages} expanded={expanded} setExpanded={setExpanded} />
        </div>
      )}
    </>
  );
}

/** Détail de « Pendant ton absence », mail par mail. */
export default function ActivityScreen() {
  const navigate = useNavigate();
  const { data, isPending, isError, refetch } = useActivity();
  const { undo } = useMailActions();
  const markSeen = useMarkSeen();
  const [expanded, setExpanded] = useState<string | null>(null);
  useDismissOutside(expanded !== null, ".mail-row.expanded", () => setExpanded(null));

  const seen = async () => {
    if (await markSeen()) navigate("/");
  };
  const mailSections: [string, string, Message[]][] = data
    ? [["important", "Importants", data.important], ["tt", "TT+", data.tt], ["alerts", "Alertes envoyées", data.alerts], ["ads", "Pubs et spams détectés", data.ads]]
    : [];

  return (
    <SettingsLayout title="Pendant ton absence" backLabel="Accueil" backTo="/">
      {isPending && <p className="muted pad">Chargement…</p>}
      {isError && (
        <p className="form-error" role="alert">
          Impossible de charger l'activité. <button type="button" className="link-btn" onClick={() => void refetch()}>Réessayer</button>
        </p>
      )}
      {data && (
        <>
          <p className="muted small activity-since">depuis {formatSince(data.since)}</p>
          {mailSections.map(([key, title, mails]) =>
            mails.length > 0 && (
              <Group key={key} title={title}>
                <MailRows section={key} mails={mails} expanded={expanded} setExpanded={setExpanded} />
              </Group>
            ),
          )}
          {data.actions.length > 0 && (
            <Group title="Actions">
              {data.actions.map((b) => (
                <BatchRow key={b.batch_id} batch={b} expanded={expanded} setExpanded={setExpanded} onUndo={() => void undo(b.batch_id)} />
              ))}
            </Group>
          )}
          {data.runs.length > 0 && (
            <Group title="Analyses">
              {data.runs.map((r) => (
                <div key={r.id ?? r.started_at} className="activity-run">
                  <strong>
                    {formatClock(r.started_at)} · {RUN_KIND_LABEL[r.kind]}
                    {r.status === "ok" && ` · ${r.kind === "sync" ? plural(r.mails_count, "nouveau mail", "nouveaux mails") : plural(r.mails_count, "mail", "mails")}`}
                  </strong>
                  {r.status === "running" ? <span className="run-badge">En cours</span> : <RunBadge run={r} />}
                </div>
              ))}
            </Group>
          )}
          <button type="button" className="btn btn-primary activity-seen" onClick={() => void seen()}>C'est vu</button>
        </>
      )}
    </SettingsLayout>
  );
}
