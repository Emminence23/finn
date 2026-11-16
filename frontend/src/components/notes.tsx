"use client";

import { useState } from "react";
import { Lock, Trash2 } from "lucide-react";
import { type Helper, api, useApi } from "@/lib/api";
import { day } from "@/lib/fmt";
import { firstName } from "./network";

type Note = { id: number; text: string; created_at: string; contact: { id: string; name: string } | null };

/** What contacts told you, kept apart from evidence: its own dashed panel, never mixed into
 *  the research view, never sent to the AI and never cited by Ask FINN. */
export function ContactNotes({ symbol, helpers }: { symbol: string; helpers: Helper[] }) {
  const { data, mutate } = useApi<{ notes: Note[] }>(`/notes?symbol=${symbol}`);
  const [text, setText] = useState("");
  const [who, setWho] = useState(helpers[0]?.contact.id ?? "");
  const [busy, setBusy] = useState(false);
  const notes = data?.notes ?? [];

  const add = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api("/notes", { method: "POST", body: JSON.stringify({ symbol, text, contact: who || null }) });
      setText("");
      await mutate();
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: number) => {
    await api(`/notes/${id}`, { method: "DELETE" }).catch(() => null);
    await mutate();
  };

  return (
    <div className="mx-3 rounded-2xl border border-dashed border-line bg-bg px-4 py-3">
      <p className="flex items-center gap-1.5 text-[11px] leading-snug text-ink-3">
        <Lock size={12} /> Off the record. Not evidence: private to you, never sent to the AI, never cited.
      </p>
      {notes.length > 0 && (
        <ul className="mt-2 space-y-2">
          {notes.map((n) => (
            <li key={n.id} className="flex gap-2 text-[13px] leading-snug">
              <div className="min-w-0 flex-1">
                <p className="text-ink">{n.text}</p>
                <p className="text-[11px] text-ink-3">
                  {n.contact ? `${firstName(n.contact.name)} told you` : "Your note"} · {day(n.created_at)}
                </p>
              </div>
              <button onClick={() => remove(n.id)} aria-label="Delete note" className="shrink-0 p-1 text-ink-3 active:opacity-60">
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2.5 space-y-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={600}
          rows={2}
          placeholder="What did they tell you?"
          aria-label="New note"
          className="w-full resize-none rounded-xl border border-line bg-surface px-3 py-2 text-[14px] outline-none placeholder:text-ink-3 focus:border-accent"
        />
        <div className="flex items-center gap-2">
          <select
            value={who}
            onChange={(e) => setWho(e.target.value)}
            aria-label="Who said it"
            className="min-w-0 flex-1 rounded-full border border-line bg-surface px-3 py-1.5 text-[13px]"
          >
            {helpers.map((h) => (
              <option key={h.contact.id} value={h.contact.id}>
                From {h.contact.name}
              </option>
            ))}
            <option value="">My own note</option>
          </select>
          <button
            onClick={add}
            disabled={busy || !text.trim()}
            className="shrink-0 rounded-full bg-ink px-4 py-1.5 text-[13px] font-medium text-bg disabled:opacity-40"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
