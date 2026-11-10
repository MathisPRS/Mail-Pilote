import { Navigate, useParams } from "react-router-dom";
import Reader from "./Reader";

/** Lecture d'un mail ouvert depuis « Pendant ton absence » : le retour revient sur /activity. */
export default function ActivityMail() {
  const id = Number(useParams().id);
  if (!Number.isInteger(id)) return <Navigate to="/activity" replace />;
  return <Reader key={id} id={id} backTo="/activity" />;
}
