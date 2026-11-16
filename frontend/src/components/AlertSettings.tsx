"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { api, type AlertRules, useApi } from "@/lib/api";
import { CATEGORY_LABEL } from "@/lib/fmt";
import { Segmented, Sheet } from "./ui";
import { NumberSlider } from "./NumberSlider";

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
          <div>
            <Row
              label="Volume"
              hint={`Compared with the average of the previous ${draft.volume_window} sessions`}
              enabled={draft.enabled.volume}
              onToggle={(v) => setDraft({ ...draft, enabled: { ...draft.enabled, volume: v } })}
            />
            <div className={clsx("mt-3 space-y-3", !draft.enabled.volume && "pointer-events-none opacity-40")}>
              <Segmented
                label="Which volume"
                value={draft.volume_mode}
                onChange={(v) => setDraft({ ...draft, volume_mode: v })}
                options={[
                  { value: "high", label: "Heavy" },
                  { value: "low", label: "Quiet" },
                  { value: "either", label: "Either" },
                ]}
              />
              {draft.volume_mode !== "low" && (
                <Field label="Heavy: at least">
                  <NumberSlider
                    label="Heavy volume, multiple of average"
                    value={draft.volume_multiple}
                    min={1}
                    max={5}
                    hardMax={100}
                    unit="×"
                    onChange={(v) => setDraft({ ...draft, volume_multiple: v })}
                  />
                </Field>
              )}
              {draft.volume_mode !== "high" && (
                <Field label="Quiet: at most">
                  <NumberSlider
                    label="Quiet volume, multiple of average"
                    value={draft.volume_low_multiple}
                    min={0.01}
                    max={1}
                    unit="×"
                    onChange={(v) => setDraft({ ...draft, volume_low_multiple: v })}
                  />
                </Field>
              )}
              <Field label="Average over">
                <NumberSlider
                  label="Sessions in the volume average"
                  value={draft.volume_window}
                  min={2}
                  max={60}
                  hardMax={250}
                  step={1}
                  decimals={0}
                  unit=" days"
                  onChange={(v) => setDraft({ ...draft, volume_window: Math.round(v) })}
                />
              </Field>
            </div>
          </div>

          <div>
            <Row
              label="Price move"
              hint="The day's close against the previous close"
              enabled={draft.enabled.price}
              onToggle={(v) => setDraft({ ...draft, enabled: { ...draft.enabled, price: v } })}
            />
            <div className={clsx("mt-3 space-y-3", !draft.enabled.price && "pointer-events-none opacity-40")}>
              <Segmented
                label="Direction"
                value={draft.price_direction}
                onChange={(v) => setDraft({ ...draft, price_direction: v })}
                options={[
                  { value: "up", label: "Up" },
                  { value: "down", label: "Down" },
                  { value: "either", label: "Either" },
                ]}
              />
              <Field label="By at least">
                <NumberSlider
                  label="Price move, percent"
                  value={draft.price_abs_pct}
                  min={0}
                  max={15}
                  hardMax={100}
                  unit="%"
                  prefix={draft.price_direction === "up" ? "+" : draft.price_direction === "down" ? "−" : "±"}
                  onChange={(v) => setDraft({ ...draft, price_abs_pct: v })}
                />
              </Field>
            </div>
          </div>

          {draft.enabled.volume && draft.enabled.price && (
            <div className="rounded-xl bg-surface-2 p-3">
              <p className="text-[14px] font-medium">Volume and price together</p>
              <div className="mt-2">
                <Segmented
                  label="Combine volume and price"
                  value={draft.combine}
                  onChange={(v) => setDraft({ ...draft, combine: v })}
                  options={[
                    { value: "any", label: "Either one (OR)" },
                    { value: "all", label: "Both (AND)" },
                  ]}
                />
              </div>
              <p className="mt-2 text-[12px] leading-snug text-ink-2">{describe(draft)}</p>
            </div>
          )}

          <div>
            <Row
              label="Material filings"
              hint="Filing types that should always reach you"
              enabled={draft.enabled.category}
              onToggle={(v) => setDraft({ ...draft, enabled: { ...draft.enabled, category: v } })}
            />
            <div className={clsx("mt-3", !draft.enabled.category && "pointer-events-none opacity-40")}>
              <Field label="Materiality at least">
                <NumberSlider
                  label="Filing materiality, out of 100"
                  value={draft.min_materiality}
                  min={0}
                  max={100}
                  step={1}
                  decimals={0}
                  unit="/100"
                  onChange={(v) => setDraft({ ...draft, min_materiality: Math.round(v) })}
                />
              </Field>
            </div>
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-[12px] text-ink-3">{label}</p>
      {children}
    </div>
  );
}

/** The rule in words, so AND and OR are never ambiguous. */
function describe(r: AlertRules): string {
  const vol =
    r.volume_mode === "high"
      ? `volume is at least ${r.volume_multiple}× its average`
      : r.volume_mode === "low"
        ? `volume is at most ${r.volume_low_multiple}× its average`
        : `volume is at least ${r.volume_multiple}× or at most ${r.volume_low_multiple}× its average`;
  const dir = r.price_direction === "up" ? "rises" : r.price_direction === "down" ? "falls" : "moves";
  const price = `the price ${dir} ${r.price_abs_pct}% or more`;
  return r.combine === "all"
    ? `Alert only on a day when ${vol} and ${price}.`
    : `Alert when ${vol}, or when ${price}. Either is enough.`;
}
