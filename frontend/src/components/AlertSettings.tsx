"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { api, type AlertRules, useApi } from "@/lib/api";
import { CATEGORY_LABEL } from "@/lib/fmt";
import { Sheet } from "./ui";

/** FR-ALERT-04: thresholds are the investor's, not ours. */
export function AlertSettings({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { data, mutate } = useApi<AlertRules>(open ? "/alert-rules" : null);
  const [draft, setDraft] = useState<AlertRules | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (data) setDraft(data);
  }, [data]);

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      const { all_categories: _all, ...body } = draft;
      void _all;
      const next = await api<AlertRules>("/alert-rules", { method: "PUT", body: JSON.stringify(body) });
      await mutate({ ...next, all_categories: draft.all_categories }, false);
      onSaved();
      onClose();
    } finally {
      setSaving(false);
    }
  }

  const all = draft?.all_categories ?? [];
  return (
    <Sheet open={open} onClose={onClose} title="Alerts">
      {!draft ? (
        <div className="skeleton my-4 h-40" />
      ) : (
        <div className="space-y-6 pb-2">
          <Slider
            label="Unusual volume"
            hint="Fire when the day's volume is above this multiple of its 20-day average"
            value={draft.volume_multiple}
            min={1.5}
            max={5}
            step={0.1}
            format={(v) => `${v.toFixed(1)}×`}
            enabled={draft.enabled.volume}
            onToggle={(v) => setDraft({ ...draft, enabled: { ...draft.enabled, volume: v } })}
            onChange={(v) => setDraft({ ...draft, volume_multiple: v })}
          />
          <Slider
            label="Big price move"
            hint="Fire when the stock closes up or down more than this in a day"
            value={draft.price_abs_pct}
            min={2}
            max={12}
            step={0.5}
            format={(v) => `±${v.toFixed(1)}%`}
            enabled={draft.enabled.price}
            onToggle={(v) => setDraft({ ...draft, enabled: { ...draft.enabled, price: v } })}
            onChange={(v) => setDraft({ ...draft, price_abs_pct: v })}
          />
          <div>
            <Row
              label="Material filings"
              hint="Filing types that should always reach you"
              enabled={draft.enabled.category}
              onToggle={(v) => setDraft({ ...draft, enabled: { ...draft.enabled, category: v } })}
            />
            <div className={clsx("mt-3 flex flex-wrap gap-2", !draft.enabled.category && "opacity-40")}>
              {all
                .filter((c) => c !== "unclassified")
                .map((c) => {
                  const on = draft.categories.includes(c);
                  return (
                    <button
                      key={c}
                      aria-pressed={on}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          categories: on ? draft.categories.filter((x) => x !== c) : [...draft.categories, c],
                        })
                      }
                      className={clsx(
                        "rounded-full border px-3 py-1 text-[13px]",
                        on ? "border-ink bg-ink text-surface" : "border-line text-ink-2",
                      )}
                    >
                      {CATEGORY_LABEL[c] ?? c}
                    </button>
                  );
                })}
            </div>
          </div>
          <button
            onClick={save}
            disabled={saving}
            className="w-full rounded-xl bg-ink py-3 text-[15px] font-medium text-surface disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </Sheet>
  );
}

function Row({ label, hint, enabled, onToggle }: { label: string; hint: string; enabled: boolean; onToggle: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-[15px] font-medium">{label}</p>
        <p className="text-[12px] leading-snug text-ink-3">{hint}</p>
      </div>
      <button
        role="switch"
        aria-checked={enabled}
        aria-label={label}
        onClick={() => onToggle(!enabled)}
        className={clsx("relative mt-1 h-6 w-10 shrink-0 rounded-full transition-colors", enabled ? "bg-good" : "bg-line")}
      >
        <span className={clsx("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all", enabled ? "left-[18px]" : "left-0.5")} />
      </button>
    </div>
  );
}

function Slider(props: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <Row label={props.label} hint={props.hint} enabled={props.enabled} onToggle={props.onToggle} />
      <div className={clsx("mt-3 flex items-center gap-3", !props.enabled && "opacity-40")}>
        <input
          type="range"
          min={props.min}
          max={props.max}
          step={props.step}
          value={props.value}
          disabled={!props.enabled}
          onChange={(e) => props.onChange(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
          aria-label={`${props.label} threshold`}
        />
        <span className="tnum w-14 text-right text-[15px] font-semibold">{props.format(props.value)}</span>
      </div>
    </div>
  );
}
