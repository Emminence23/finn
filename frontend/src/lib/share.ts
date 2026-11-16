// Share as plain text: the phone's share sheet where there is one (WhatsApp, mail, notes),
// the clipboard otherwise. Text only, so it reads the same wherever it lands.

export type ShareResult = "shared" | "copied" | "cancelled" | "failed";

export async function shareText(title: string, lines: (string | null | undefined | false)[], url?: string | null): Promise<ShareResult> {
  const body = lines.filter(Boolean).join("\n");
  const text = url ? `${body}\n${url}` : body;
  const nav = typeof navigator !== "undefined" ? navigator : undefined;
  if (nav?.share && (!nav.canShare || nav.canShare({ title, text }))) {
    try {
      await nav.share({ title, text });
      return "shared";
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return "cancelled";
    }
  }
  try {
    await nav?.clipboard.writeText(text); // the first line already names it
    return "copied";
  } catch {
    return "failed";
  }
}
