import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiGet, apiSend } from "../api";
import Sheet from "../components/Sheet";
import { useToast } from "../components/Toast";
import { formatClock, parseDate, plural } from "../format";
import type { ClaudeLoginStart, ClaudeStatus, OkDetail } from "../types";
import SettingsLayout, { Group } from "./SettingsLayout";

const LIFETIME_DAYS = 365;
const WARN_CHOICES = [1, 3, 7, 14, 30];
const TZ = "Europe/Paris";

function lastOkText(iso: string): string {
  const d = parseDate(iso);
  const day = (x: Date) => x.toLocaleDateString("fr-CA", { timeZone: TZ });
  const when = day(d) === day(new Date()) ? "aujourd'hui" : `le ${d.toLocaleDateString("fr-FR", { timeZone: TZ })}`;
  return `dernier appel réussi ${when} à ${formatClock(iso)}`;
}

export default function ClaudePage() {
  const [reconnecting, setReconnecting] = useState(false);
  const status = useQuery({ queryKey: ["claude-status"], queryFn: () => apiGet<ClaudeStatus>("/api/claude/status") });
  const client = useQueryClient();
  const toast = useToast();
  const s = status.data;
  const warn = useMutation({
    mutationFn: (warn_days: number) => apiSend<{ warn_days: number }>("PUT", "/api/claude/settings", { warn_days }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["claude-status"] }); toast("Réglages enregistrés"); },
    onError: (e) => toast(e instanceof ApiError ? e.detail : "Une erreur est survenue"),
  });
  const days = s?.days_left ?? null;
  const progress = days === null ? 0 : Math.max(0, Math.min(1, days / LIFETIME_DAYS));
  const details: string[] = [];
  if (s?.expires_at) details.push(`Le ${parseDate(s.expires_at).toLocaleDateString("fr-FR", { timeZone: TZ })}`);
  if (s?.last_ok_at) details.push(lastOkText(s.last_ok_at));

  return (
    <SettingsLayout title="Claude" backLabel="Profil" backTo="/settings">
      <div className="settings-card claude-card">
        <div className="claude-head">
          <span className="user-name">Claude</span>
          {s && <span className={`pill ${s.connected ? "ok" : "err"}`}>{s.connected ? "Connecté" : "Déconnecté"}</span>}
        </div>
        {s && !s.connected && s.last_error && <p className="form-error">{s.last_error}</p>}
        {days !== null && (
          <div className="claude-expiry">
            <div className="claude-expiry-line">
              <span>Expiration du login</span>
              <span className="muted">{days > 0 ? `dans ${plural(days, "jour", "jours")}` : "expiré"}</span>
            </div>
            <div className="meter" role="progressbar" aria-label="Durée de validité restante" aria-valuemin={0} aria-valuemax={LIFETIME_DAYS} aria-valuenow={Math.max(0, days)}>
              <div style={{ width: `${progress * 100}%` }} />
            </div>
          </div>
        )}
        {details.length > 0 && <span className="muted small">{details.join(" · ")}</span>}
        <button type="button" className="btn" onClick={() => setReconnecting(true)}>Reconnecter</button>
      </div>
      <Group>
        <div className="settings-row static">
          <label className="row-label" htmlFor="warn-days">Me prévenir avant l'expiration</label>
          <select id="warn-days" className="select" aria-label="Me prévenir avant l'expiration" value={String(s?.warn_days ?? 7)} disabled={!s || warn.isPending}
            onChange={(e) => warn.mutate(Number(e.target.value))}>
            {WARN_CHOICES.map((n) => <option key={n} value={n}>{n === 1 ? "1 jour avant" : `${n} jours avant`}</option>)}
          </select>
        </div>
      </Group>
      {reconnecting && <ReconnectSheet onClose={() => setReconnecting(false)} />}
    </SettingsLayout>
  );
}

const START_ERROR = "Impossible de démarrer la connexion à Claude";

/** Connexion à l'abonnement Claude pilotée par le serveur (`claude setup-token`) : lien officiel, puis code. */
function ReconnectSheet({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [tokenSaved, setTokenSaved] = useState(false);
  const launched = useRef(false);
  const finished = useRef(false); // plus de session à annuler côté serveur

  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["claude-status"] });
    void client.invalidateQueries({ queryKey: ["runs"] });
  };

  const start = useMutation({
    mutationFn: () => apiSend<ClaudeLoginStart>("POST", "/api/claude/login/start"),
    onMutate: () => { finished.current = false; setUrl(null); setError(null); setCode(""); },
    onSuccess: (r) => setUrl(r.url),
    onError: (e) => setError(e instanceof ApiError ? e.detail : START_ERROR),
  });

  const complete = useMutation({
    mutationFn: (value: string) => apiSend<OkDetail>("POST", "/api/claude/login/complete", { code: value }),
    onSuccess: (r) => {
      finished.current = true; // la session serveur est terminée, réussie ou non
      if (r.ok) {
        refresh();
        toast("Claude est connecté");
        onClose();
        return;
      }
      setUrl(null);
      setError(r.detail);
    },
    onError: (e) => {
      finished.current = true;
      setUrl(null);
      setError(e instanceof ApiError ? e.detail : "Une erreur est survenue");
    },
  });

  useEffect(() => {
    if (launched.current) return; // StrictMode : une seule session
    launched.current = true;
    start.mutate();
  }, [start]);

  const close = () => {
    if (!finished.current) void apiSend<void>("POST", "/api/claude/login/cancel").catch(() => {});
    onClose();
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const value = code.trim();
    if (!value) return;
    setCode("");
    complete.mutate(value);
  };

  return (
    <Sheet label="Reconnecter Claude" onClose={close}>
      <div className="sheet-form">
        <p className="sheet-title">Reconnecter Claude</p>
        <p className="muted small">Relance la connexion à ton abonnement Claude, sans terminal.</p>
        {start.isPending && <p className="muted" role="status">Préparation de la connexion…</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        {error && !start.isPending && (
          <button type="button" className="btn" onClick={() => start.mutate()}>Recommencer</button>
        )}
        {url && (
          <>
            <ol className="steps">
              <li>
                <p>Connecte-toi avec ton compte Claude (abonnement Max). Claude t'affichera un code.</p>
                <a className="btn btn-primary link-btn" href={url} target="_blank" rel="noopener noreferrer">Se connecter à Claude</a>
              </li>
              <li>
                <form className="sheet-form" onSubmit={submit}>
                  <div className="field">
                    <label htmlFor="claude-code">Code affiché par Claude</label>
                    <input id="claude-code" type="text" autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                      value={code} onChange={(e) => setCode(e.target.value)} />
                  </div>
                  <button type="submit" className="btn btn-primary" disabled={!code.trim() || complete.isPending}>
                    {complete.isPending ? "Connexion en cours…" : "Valider"}
                  </button>
                </form>
              </li>
            </ol>
          </>
        )}
        <button type="button" className="text-btn" aria-expanded={advanced} onClick={() => setAdvanced((v) => !v)}>
          Autre méthode (avancé)
        </button>
        {advanced && <TokenForm onSaved={() => { setTokenSaved(true); refresh(); }} />}
        <button type="button" className="text-btn" onClick={close}>{tokenSaved ? "Fermer" : "Annuler"}</button>
      </div>
    </Sheet>
  );
}

/** Ancienne méthode : coller un code obtenu avec `claude setup-token` sur un ordinateur. */
function TokenForm({ onSaved }: { onSaved: () => void }) {
  const [token, setToken] = useState("");
  const [result, setResult] = useState<OkDetail | null>(null);

  const save = useMutation({
    mutationFn: (value: string) => apiSend<OkDetail>("POST", "/api/claude/token", { token: value }),
    onSuccess: (r) => {
      setResult(r);
      if (r.ok) onSaved();
    },
    onError: (e) => setResult({ ok: false, detail: e instanceof ApiError ? e.detail : "Une erreur est survenue" }),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const value = token.trim();
    if (!value) return;
    setToken(""); // le jeton ne reste jamais dans l'état après l'envoi
    setResult(null);
    save.mutate(value);
  };

  return (
    <form className="sheet-form" onSubmit={submit}>
      <ol className="steps">
        <li>Sur un ordinateur, lance <code>claude setup-token</code> dans un terminal.</li>
        <li>Connecte-toi avec ton compte Claude.</li>
        <li>Colle ici le jeton affiché.</li>
      </ol>
      <div className="field">
        <label htmlFor="claude-token">Jeton Claude</label>
        <textarea id="claude-token" rows={3} autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} value={token} onChange={(e) => setToken(e.target.value)} />
      </div>
      {result && <p className={result.ok ? "form-ok" : "form-error"} role="status">{result.detail}</p>}
      {!result?.ok && (
        <button type="submit" className="btn" disabled={!token.trim() || save.isPending}>
          {save.isPending ? "Test en cours…" : "Tester et enregistrer"}
        </button>
      )}
    </form>
  );
}
