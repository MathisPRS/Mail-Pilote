import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { useMailActions } from "../hooks/useMailActions";

/** « Lancer manuellement » : analyse complète et nettoyage des pubs/spams. */
export default function ActionsSheet({ account, onClose }: { account: string; onClose: () => void }) {
  const { runAnalysis, cleanup } = useMailActions();
  return (
    <Sheet label="Actions manuelles" onClose={onClose}>
      <span className="sheet-section first">Lancer manuellement</span>
      <button type="button" className="action-row" onClick={() => { onClose(); void runAnalysis(); }}>
        <span className="action-icon" style={{ background: "#1F6FEB" }}><Icon name="search" size={18} stroke="#fff" width={2} /></span>
        <span className="action-text">
          <strong>Lancer une analyse</strong>
          <span>Claude lit les nouveaux mails de toutes les boîtes</span>
        </span>
      </button>
      <button type="button" className="action-row" onClick={() => { onClose(); void cleanup(account); }}>
        <span className="action-icon" style={{ background: "#C2410C" }}><Icon name="trash" size={18} stroke="#fff" width={2} /></span>
        <span className="action-text">
          <strong>Nettoyer pubs et spams</strong>
          <span>Déplace les pubs et spams de la réception vers la corbeille, annulable</span>
        </span>
      </button>
    </Sheet>
  );
}
