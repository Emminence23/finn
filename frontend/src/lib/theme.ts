export const THEME_KEY = "finn.theme";

/** Runs before first paint (inline in layout.tsx), so a pinned theme never flashes. */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
