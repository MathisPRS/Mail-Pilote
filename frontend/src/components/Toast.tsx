import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

interface ToastOptions { actionLabel?: string; onAction?: () => void; durationMs?: number }
interface ToastState extends ToastOptions { message: string; key: number }

const ToastContext = createContext<(message: string, opts?: ToastOptions) => void>(() => {});

/** `const toast = useToast(); toast("Mail déplacé", { actionLabel: "Annuler", onAction })` */
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const counter = useRef(0);

  const show = useCallback((message: string, opts: ToastOptions = {}) => {
    clearTimeout(timer.current);
    setToast({ message, ...opts, key: ++counter.current });
    timer.current = setTimeout(() => setToast(null), opts.durationMs ?? 6000);
  }, []);

  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && (
        <div className="toast" role="status" key={toast.key}>
          <span>{toast.message}</span>
          {toast.actionLabel && (
            <button
              type="button"
              className="toast-action"
              onClick={() => {
                toast.onAction?.();
                setToast(null);
              }}
            >
              {toast.actionLabel}
            </button>
          )}
        </div>
      )}
    </ToastContext.Provider>
  );
}
