import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getMe } from "../api";
import Icon from "./Icon";

export function ActionsButton({ onClick, subtle = false }: { onClick: () => void; subtle?: boolean }) {
  return (
    <button type="button" className={`round-btn${subtle ? " subtle" : ""}`} aria-label="Actions manuelles" aria-haspopup="dialog" onClick={onClick}>
      <Icon name="zap" />
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
