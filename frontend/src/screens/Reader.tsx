import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, apiGet } from "../api";
import Icon from "../components/Icon";
import { CATEGORY_TAGS, formatFull } from "../format";
import type { MessageDetail } from "../types";

const FRAME_CSS =
  "body{margin:12px;font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111317;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%}";

const frameDoc = (html: string) =>
  `<!doctype html><html><head><meta charset="utf-8"><style>${FRAME_CSS}</style></head><body>${html}</body></html>`;

export default function Reader({ id, backTo }: { id: number; backTo: string | null }) {
  const qc = useQueryClient();
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["message", id],
    queryFn: () => apiGet<MessageDetail>(`/api/messages/${id}`),
  });

  // Ouvrir un mail le marque comme lu : on rafraîchit les listes et les compteurs.
  const loadedId = data?.id;
  useEffect(() => {
    if (loadedId === undefined) return;
    for (const k of ["messages", "boxes", "folders"]) void qc.invalidateQueries({ queryKey: [k] });
  }, [loadedId, qc]);

  const tag = data?.category ? CATEGORY_TAGS[data.category] : undefined;

  return (
    <article className="reader">
      {backTo && (
        <Link to={backTo} className="text-btn back reader-back">
          <Icon name="back" size={20} width={2.2} />
          Retour
        </Link>
      )}
      {isPending && <p className="muted pad">Chargement…</p>}
      {error && (
        <div className="pad">
          <p className="form-error" role="alert">{error instanceof ApiError ? error.detail : "Impossible de récupérer ce mail"}</p>
          <button type="button" className="btn" onClick={() => void refetch()}>Réessayer</button>
        </div>
      )}
      {data && (
        <>
          {data.summary && (
            <section className="reader-summary" aria-label="Résumé de Claude">
              <span className="reader-summary-title">Résumé de Claude</span>
              <p>{data.summary}</p>
            </section>
          )}
          <h1 className="reader-subject">{data.subject}</h1>
          <div className="reader-meta">
            <span><strong>{data.from_name || data.from_addr}</strong> <span className="muted">&lt;{data.from_addr}&gt;</span></span>
            <span className="muted small">{formatFull(data.sent_at)}</span>
            {tag && <span className={`tag tag-${data.category}`}>{tag}</span>}
          </div>
          {data.body_html ? (
            <iframe className="reader-frame" title="Contenu du mail" sandbox="" srcDoc={frameDoc(data.body_html)} />
          ) : (
            <pre className="reader-text">{data.body_text ?? ""}</pre>
          )}
          {data.attachments.length > 0 && (
            <section className="reader-attachments">
              <h2>Pièces jointes</h2>
              <ul>
                {data.attachments.map((name, i) => (
                  <li key={`${i}-${name}`}><Icon name="paperclip" size={16} stroke="#5F6672" />{name}</li>
                ))}
              </ul>
            </section>
          )}
          {data.open_url && <a className="btn btn-primary open-app" href={data.open_url}>Ouvrir l'app</a>}
        </>
      )}
    </article>
  );
}
