import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getMe } from "../api";
import { isRunning, useLatestRuns } from "../hooks/useLatestRuns";
import Icon from "./Icon";

/** Bouton éclair ; une pastille bleue animée signale qu'une analyse tourne. */
export function ActionsButton({ onClick, subtle = false }: { onClick: () => void; subtle?: boolean }) {
  const running = isRunning(useLatestRuns().data);
  return (
    <button
      type="button"
      className={`round-btn${subtle ? " subtle" : ""}`}
      aria-label={running ? "Actions, analyse en cours" : "Actions manuelles"}
      aria-haspopup="dialog"
      onClick={onClick}
    >
      <Icon name="zap" />
      {running && <span className="run-dot" aria-hidden="true" />}
    </button>
  );
}

/** Avatar : ouvre /settings (Réglages). */
export function ProfileButton() {
  const navigate = useNavigate();
  const me = useQuery({ queryKey: ["me"], queryFn: getMe });
  const letter = (me.data?.display_name || me.data?.username || "M").trim().charAt(0).toUpperCase();
  return (
    <button type="button" className="round-btn avatar" aria-label="Profil et réglages" onClick={() => navigate("/settings")}>
      {letter}
    </button>
  );
}
