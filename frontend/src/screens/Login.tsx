import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, authLogin, authSetup, getAuthStatus } from "../api";

const MIN_PASSWORD = 12;

function messageFor(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return "Trop de tentatives, réessaie dans 15 minutes.";
    if (e.status === 409) return "Le compte est déjà créé. Recharge la page pour te connecter.";
    return e.detail;
  }
  return "Impossible de joindre le serveur.";
}

export default function Login() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["auth-status"], queryFn: getAuthStatus });
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status.isPending) return <main className="auth-page"><p className="muted">Chargement…</p></main>;
  if (status.isError) {
    return <main className="auth-page"><p className="form-error" role="alert">Impossible de joindre le serveur.</p></main>;
  }
  const setup = !status.data.setup_done;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (setup) {
      if (password.length < MIN_PASSWORD) return setError(`Le mot de passe doit contenir au moins ${MIN_PASSWORD} caractères.`);
      if (password !== confirm) return setError("Les mots de passe ne correspondent pas.");
    }
    setBusy(true);
    try {
      if (setup) await authSetup({ display_name: displayName.trim(), username: username.trim(), password });
      await authLogin({ username: username.trim(), password });
      await queryClient.invalidateQueries({ queryKey: ["auth-status"] });
      navigate("/", { replace: true });
    } catch (err) {
      setError(messageFor(err));
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="card auth-card" onSubmit={onSubmit} noValidate>
        <img className="auth-logo" src="/icon-192.png" alt="" width={56} height={56} />
        <h1>{setup ? "Créer ton compte" : "Mail Pilot"}</h1>
        <p className="muted">{setup ? "Première utilisation : crée l'accès à ton application." : "Connecte-toi pour accéder à tes mails."}</p>

        {setup && (
          <div className="field">
            <label htmlFor="display_name">Nom affiché</label>
            <input id="display_name" autoComplete="name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
        )}
        <div className="field">
          <label htmlFor="username">Identifiant</label>
          <input id="username" autoComplete="username" autoCapitalize="none" autoCorrect="off" required value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="password">Mot de passe</label>
          <input id="password" type="password" autoComplete={setup ? "new-password" : "current-password"} required value={password} onChange={(e) => setPassword(e.target.value)} />
          {setup && <small className="hint">{MIN_PASSWORD} caractères minimum.</small>}
        </div>
        {setup && (
          <div className="field">
            <label htmlFor="confirm">Confirmer</label>
            <input id="confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </div>
        )}

        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {setup ? "Créer le compte" : "Se connecter"}
        </button>
      </form>
    </main>
  );
}
