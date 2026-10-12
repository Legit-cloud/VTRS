"use client";

import { useEffect, useState } from "react";

const KEY = "vtrs.warroom.theme";

/**
 * The War Room is dark by default for wall screens and night shifts, light on request. The
 * class goes on <html> so the sidebar and top bar follow, and is removed when leaving.
 */
export function useWarRoomTheme(): { dark: boolean; toggle: () => void } {
  const [dark, setDark] = useState(() => {
    if (typeof window === "undefined") return true;
    try {
      return window.localStorage.getItem(KEY) !== "light";
    } catch {
      return true;
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("war-room", dark);
    return () => root.classList.remove("war-room");
  }, [dark]);

  return {
    dark,
    toggle: () =>
      setDark((current) => {
        const next = !current;
        try {
          window.localStorage.setItem(KEY, next ? "dark" : "light");
        } catch {
          // ignore
        }
        return next;
      }),
  };
}
