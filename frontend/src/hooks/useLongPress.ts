import { useCallback, useEffect, useRef } from "react";
import type { MouseEvent, PointerEvent } from "react";

/** Durée d'appui avant que la rangée d'actions s'ouvre. */
export const LONG_PRESS_MS = 600;
/** Au-delà de ce déplacement (px) le geste est un défilement, pas un appui long. */
export const LONG_PRESS_MOVE_PX = 10;

/**
 * Appui long (tactile ou souris) et clic droit. Le click qui suit un appui long est annulé pour ne
 * pas ouvrir le mail ; l'appui est abandonné si le doigt bouge de plus de 10 px ou si le navigateur
 * annule le geste (pointercancel).
 */
export function useLongPress(onLongPress: () => void, enabled = true) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const start = useRef({ x: 0, y: 0 });
  const fired = useRef(false);
  const callback = useRef(onLongPress);
  callback.current = onLongPress;

  const clear = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  useEffect(() => clear, [clear]);

  const fire = useCallback(() => {
    clear();
    fired.current = true;
    navigator.vibrate?.(10);
    callback.current();
  }, [clear]);

  const onPointerDown = (e: PointerEvent) => {
    fired.current = false;
    if (!enabled || (e.pointerType === "mouse" && e.button !== 0)) return;
    start.current = { x: e.clientX ?? 0, y: e.clientY ?? 0 };
    clear();
    timer.current = setTimeout(fire, LONG_PRESS_MS);
  };
  const onPointerMove = (e: PointerEvent) => {
    if (timer.current === null) return;
    if (Math.hypot((e.clientX ?? 0) - start.current.x, (e.clientY ?? 0) - start.current.y) > LONG_PRESS_MOVE_PX) clear();
  };
  const onContextMenu = (e: MouseEvent) => {
    if (!enabled) return;
    e.preventDefault(); // pas de menu natif (clic droit, appui long Android)
    if (!fired.current) fire();
  };
  const onClickCapture = (e: MouseEvent) => {
    if (fired.current && e.detail !== 0) {
      fired.current = false;
      e.preventDefault();
      e.stopPropagation();
    }
  };
  return { onPointerDown, onPointerMove, onPointerUp: clear, onPointerCancel: clear, onContextMenu, onClickCapture };
}

/** Appelle `onOutside` quand on touche en dehors des éléments `inside` (ex. la rangée d'actions ouverte). */
export function useDismissOutside(active: boolean, inside: string, onOutside: () => void) {
  const cb = useRef(onOutside);
  cb.current = onOutside;
  useEffect(() => {
    if (!active) return;
    const handler = (e: Event) => {
      if (!(e.target instanceof Element) || !e.target.closest(inside)) cb.current();
    };
    document.addEventListener("pointerdown", handler);
    return () => document.removeEventListener("pointerdown", handler);
  }, [active, inside]);
}
