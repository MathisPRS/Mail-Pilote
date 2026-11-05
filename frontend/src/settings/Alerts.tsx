import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiGet, apiSend } from "../api";
import Toggle from "../components/Toggle";
import { useToast } from "../components/Toast";
import { subscribeToPush } from "../push";
import type { AlertSettings, AlertSettingsUpdate, OkDetail } from "../types";
import SettingsLayout, { Group } from "./SettingsLayout";
import { useDraft } from "./useDraft";

type Kind = "notify_tt" | "notify_important" | "notify_action" | "notify_summary";
const KINDS: [Kind, string][] = [
  ["notify_tt", "Ouverture d'un TT+"],
  ["notify_important", "Mail important"],
  ["notify_action", "Mail à traiter"],
  ["notify_summary", "Résumé après chaque analyse"],
];

const msg = (e: unknown) => (e instanceof ApiError ? e.detail : "Une erreur est survenue");

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="settings-row static">
      <span className="row-label">{label}</span>
      {children}
    </div>
  );
}

export default function Alerts() {
  const client = useQueryClient();
  const toast = useToast();
  const server = useQuery({ queryKey: ["settings", "alerts"], queryFn: () => apiGet<AlertSettings>("/api/settings/alerts") });
  const [draft, setDraft] = useDraft(server.data);
  const [token, setToken] = useState("");
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pushMessage, setPushMessage] = useState<string | null>(null);
  const [subscribing, setSubscribing] = useState(false);

  const update = (patch: Partial<AlertSettings>) => {
    setError(null);
    setDirty(true);
    setDraft((d) => (d ? { ...d, ...patch } : d));
  };

  const save = useMutation({
    mutationFn: (body: AlertSettingsUpdate) => apiSend<AlertSettings>("PUT", "/api/settings/alerts", body),
    onSuccess: (saved) => {
      setDraft(saved);
      setToken("");
      setDirty(false);
      client.setQueryData(["settings", "alerts"], saved);
      toast("Réglages enregistrés");
    },
    onError: (e) => setError(msg(e)),
  });

  const test = useMutation({
    mutationFn: () => apiSend<OkDetail>("POST", "/api/alerts/test", { channel: "gotify" }),
    onSuccess: (r) => toast(r.detail),
    onError: (e) => toast(msg(e)),
  });

  const onWebpush = async (on: boolean) => {
    setPushMessage(null);
    if (!on) { update({ webpush: false }); return; }
    setSubscribing(true);
    const result = await subscribeToPush();
    setSubscribing(false);
    if (result.ok) { update({ webpush: true }); return; }
    if (result.reason === "denied") toast(result.message);
    else setPushMessage(result.message);
  };

  const submit = () => {
    if (!draft) return;
    const { gotify_token_set: _set, ...rest } = draft;
    const body: AlertSettingsUpdate = { ...rest, gotify_url: draft.gotify ? (draft.gotify_url ?? "").trim() || null : draft.gotify_url };
    if (token.trim()) body.gotify_token = token.trim();
    save.mutate(body);
  };

  return (
    <SettingsLayout title="Alertes" backLabel="Profil" backTo="/settings">
      {server.isError && <p className="form-error" role="alert">Impossible de charger les alertes.</p>}
      {draft && (
        <>
          <section className="settings-group">
            <h2 className="settings-label">Canaux</h2>
            <div className="settings-card">
              <Row label="Notification iPhone">
                <Toggle label="Notification iPhone" checked={draft.webpush} disabled={subscribing} onChange={(v) => void onWebpush(v)} />
              </Row>
              {pushMessage && <p className="settings-inline-note" role="alert">{pushMessage}</p>}
              <Row label="Gotify">
                <Toggle label="Gotify" checked={draft.gotify} onChange={(v) => update({ gotify: v })} />
              </Row>
              {draft.gotify && (
                <div className="field-row">
                  <input placeholder="URL du serveur (ex. https://gotify.mon-nas.local)" aria-label="URL du serveur Gotify" inputMode="url" autoComplete="off" autoCapitalize="none"
                    value={draft.gotify_url ?? ""} onChange={(e) => update({ gotify_url: e.target.value })} />
                  <input type="password" aria-label="Jeton de l'application Gotify" autoComplete="off"
                    placeholder={draft.gotify_token_set ? "Jeton enregistré (laisse vide pour le garder)" : "Jeton de l'application"}
                    value={token} onChange={(e) => { setToken(e.target.value); setDirty(true); }} />
                  <button type="button" className="btn" disabled={dirty || !draft.gotify_token_set || test.isPending} onClick={() => test.mutate()}>
                    Envoyer une notification de test
                  </button>
                  {(dirty || !draft.gotify_token_set) && <p className="muted small">Enregistre d'abord les réglages pour envoyer un test.</p>}
                </div>
              )}
            </div>
          </section>
          <Group title="M'alerter pour">
            {KINDS.map(([key, label]) => (
              <Row key={key} label={label}>
                <Toggle label={label} checked={draft[key]} onChange={(v) => update({ [key]: v })} />
              </Row>
            ))}
          </Group>
          <Group title="Heures de silence">
            <Row label="Activer">
              <Toggle label="Heures de silence" checked={draft.quiet_enabled} onChange={(v) => update({ quiet_enabled: v })} />
            </Row>
            {draft.quiet_enabled && (
              <>
                <div className="settings-row static quiet-times">
                  <span>De</span>
                  <input type="time" aria-label="Début" value={draft.quiet_from} onChange={(e) => update({ quiet_from: e.target.value })} />
                  <span>à</span>
                  <input type="time" aria-label="Fin" value={draft.quiet_to} onChange={(e) => update({ quiet_to: e.target.value })} />
                </div>
                <Row label="Les alertes TT+ passent quand même">
                  <Toggle label="Les alertes TT+ passent quand même" checked={draft.quiet_tt_bypass} onChange={(v) => update({ quiet_tt_bypass: v })} />
                </Row>
              </>
            )}
          </Group>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button type="button" className="btn btn-primary" disabled={save.isPending} onClick={submit}>Enregistrer</button>
        </>
      )}
    </SettingsLayout>
  );
}
