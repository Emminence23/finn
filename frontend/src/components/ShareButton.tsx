"use client";

import { useState } from "react";
import { Check, Share2 } from "lucide-react";
import clsx from "clsx";
import { shareText } from "@/lib/share";

/** Icon button that shares (or copies) text built on tap. */
export function ShareButton({
  build,
  label = "Share",
  withText = false,
  className,
}: {
  build: () => { title: string; lines: (string | null | undefined | false)[]; url?: string | null };
  label?: string;
  withText?: boolean;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const onClick = async () => {
    const { title, lines, url } = build();
    const r = await shareText(title, lines, url);
    if (r === "copied" || r === "failed") {
      setState(r);
      setTimeout(() => setState("idle"), 1800);
    }
  };
  return (
    <button onClick={onClick} aria-label={label} className={clsx("inline-flex shrink-0 items-center gap-1 active:opacity-70", className)}>
      {state === "copied" ? <Check size={13} className="text-good" /> : <Share2 size={13} />}
      {/* On cards the tick is the feedback, so the footer never reflows; the words go to screen readers */}
      <span role="status" className={withText ? undefined : "sr-only"}>
        {state === "copied" ? "Copied" : state === "failed" ? "Couldn't copy" : withText ? label : ""}
      </span>
    </button>
  );
}
