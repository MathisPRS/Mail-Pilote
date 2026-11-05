import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Icon from "../components/Icon";

interface Props {
  title: string;
  backLabel: string;
  /** Chemin parent ; absent = retour à l'écran précédent (« / » s'il n'y en a pas). */
  backTo?: string;
  children: ReactNode;
}

/** Cadre commun des écrans de réglages : barre « ‹ Parent · Titre », colonne centrée (560 px) dès 900 px. */
export default function SettingsLayout({ title, backLabel, backTo, children }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const back = () => {
    if (backTo) navigate(backTo);
    else if (location.key !== "default") navigate(-1);
    else navigate("/");
  };
  return (
    <main className="settings">
      <header className="settings-bar">
        <button type="button" className="text-btn back" onClick={back}>
          <Icon name="back" />
          {backLabel}
        </button>
        <h1>{title}</h1>
        <span />
      </header>
      <div className="settings-body">{children}</div>
    </main>
  );
}

export function Group({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="settings-group">
      {title && <h2 className="settings-label">{title}</h2>}
      <div className="settings-card">{children}</div>
    </section>
  );
}
