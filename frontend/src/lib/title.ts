import { useEffect } from "react";

/** The browser tab and share sheet name the page, not just the app. */
export function useTitle(title: string | null | undefined) {
  useEffect(() => {
    if (title) document.title = `${title} · FINN`;
  }, [title]);
}
