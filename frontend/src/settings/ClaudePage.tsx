import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiGet, apiSend } from "../api";
import Sheet from "../components/Sheet";
import { formatClock, parseDate, plural } from "../format";
import type { ClaudeStatus, OkDetail } from "../types";
import SettingsLayout, { Group } from "./SettingsLayout";

const LIFETIME_DAYS = 365;
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
  const s = status.data;
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
        <p className="settings-note">Tu es prévenu 7 jours avant l'expiration du login Claude.</p>
      </Group>
      {reconnecting && <TokenSheet onClose={() => setReconnecting(false)} />}
    </SettingsLayout>
  );
}

function TokenSheet({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const [token, setToken] = useState("");
  const [result, setResult] = useState<OkDetail | null>(null);

  const save = useMutation({
    mutationFn: (value: string) => apiSend<OkDetail>("POST", "/api/claude/token", { token: value }),
    onSuccess: (r) => {
      setResult(r);
      if (r.ok) {
        void client.invalidateQueries({ queryKey: ["claude-status"] });
        void client.invalidateQueries({ queryKey: ["runs"] });
      }
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
    <Sheet label="Reconnecter Claude" onClose={onClose}>
      <form className="sheet-form" onSubmit={submit}>
        <p className="sheet-title">Reconnecter Claude</p>
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
        {result?.ok ? (
          <button type="button" className="btn btn-primary" onClick={onClose}>Fermer</button>
        ) : (
          <>
            <button type="submit" className="btn btn-primary" disabled={!token.trim() || save.isPending}>
              {save.isPending ? "Test en cours…" : "Tester et enregistrer"}
            </button>
            <button type="button" className="text-btn" onClick={onClose}>Annuler</button>
          </>
        )}
      </form>
    </Sheet>
  );
}
