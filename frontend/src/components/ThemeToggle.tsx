"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

import { THEME_KEY as KEY } from "@/lib/theme";

function effective(): "light" | "dark" {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Light / dark. Starts from the phone's setting; a tap pins the other one. */
export function ThemeToggle({ className }: { className?: string }) {
  const [mode, setMode] = useState<"light" | "dark" | null>(null);
  useEffect(() => setMode(effective()), []);
  const flip = () => {
    const next = effective() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    const meta = document.querySelector('meta[name="theme-color"]:not([media])') ?? document.createElement("meta");
    meta.setAttribute("name", "theme-color");
    meta.setAttribute("content", next === "dark" ? "#121211" : "#f6f5f1");
    if (!meta.parentNode) document.head.appendChild(meta);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* this visit only */
    }
    setMode(next);
  };
  const dark = mode === "dark";
  return (
    <button
      onClick={flip}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      className={className}
    >
      {dark ? <Sun size={17} /> : <Moon size={17} />}
    </button>
  );
}
