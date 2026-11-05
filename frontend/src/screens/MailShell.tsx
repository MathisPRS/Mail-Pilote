import { Navigate, useParams } from "react-router-dom";
import { useMediaQuery, WIDE_QUERY } from "../hooks/useMediaQuery";
import MailList from "./MailList";
import Reader from "./Reader";

/**
 * Vue liste + lecture. Routes (voir App.tsx) :
 *   /box/:account/:folder              liste
 *   /box/:account/:folder/mail/:id     lecture (la liste reste visible dès 900 px)
 *   /mail/:id                          lecture seule (liste = toutes les boîtes / réception)
 */
export default function MailShell() {
  const params = useParams();
  const wide = useMediaQuery(WIDE_QUERY);
  const account = params.account ?? "all";
  const folder = params.folder ?? "inbox";
  const idText = params.id ?? /^mail\/(\d+)$/.exec(params["*"] ?? "")?.[1];
  const mailId = idText === undefined ? null : Number(idText);
  if (mailId !== null && !Number.isInteger(mailId)) return <Navigate to="/" replace />;
  const listUrl = params.account ? `/box/${account}/${folder}` : "/";

  const list = <MailList key={`${account}/${folder}`} account={account} folder={folder} activeId={mailId} />;

  if (!wide) {
    return mailId === null ? list : <Reader key={mailId} id={mailId} backTo={listUrl} />;
  }
  return (
    <div className="split">
      <section className="split-list">{list}</section>
      <section className="split-reader">
        {mailId === null ? <p className="empty">Sélectionne un mail pour le lire</p> : <Reader key={mailId} id={mailId} backTo={null} />}
      </section>
    </div>
  );
}
