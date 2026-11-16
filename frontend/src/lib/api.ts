// Single typed entry point to the FINN API.
import useSWR, { type SWRConfiguration } from "swr";

export const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PASSCODE_KEY = "finn.passcode";
const ACCOUNT_KEY = "finn.account";
const SANDBOX_KEY = "finn.sandbox";

/** "Bring your own network": this browser's private sandbox account, if it has one. */
export function getSandbox(): string | null {
  try {
    return localStorage.getItem(SANDBOX_KEY);
  } catch {
    return null;
  }
}

export function setSandbox(value: string | null) {
  try {
    if (value) localStorage.setItem(SANDBOX_KEY, value);
    else localStorage.removeItem(SANDBOX_KEY);
  } catch {
    /* lasts for this page only */
  }
}

/** N-7: which demo account's network the API returns. A demo switch, not sign-in. */
export function getAccount(): string {
  try {
    return localStorage.getItem(ACCOUNT_KEY) ?? "demo";
  } catch {
    return "demo";
  }
}

export function setAccount(value: string) {
  try {
    localStorage.setItem(ACCOUNT_KEY, value);
  } catch {
    /* lasts for this page only */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getPasscode(): string {
  try {
    return localStorage.getItem(PASSCODE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setPasscode(value: string) {
  try {
    localStorage.setItem(PASSCODE_KEY, value);
  } catch {
    /* storage unavailable: passcode lasts for this page only */
  }
}

// Offline: the last good answer for Today's endpoints is kept per account, so the morning
// brief still opens on the metro. Only these small, read-only paths are kept.
const OFFLINE_PATHS = ["/digest", "/people/meetings/prep", "/portfolio", "/alerts/rules"];
const offlineKey = (path: string) => `finn.offline.${getAccount()}.${path}`;
const keepsOffline = (path: string, init: RequestInit) =>
  (!init.method || init.method === "GET") && OFFLINE_PATHS.some((p) => path.startsWith(p));

export type OfflineEvent = CustomEvent<{ at: number }>;

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Finn-Passcode": getPasscode(),
        "X-Finn-User": getAccount(),
        ...init.headers,
      },
    });
  } catch (e) {
    // network down: serve the saved copy if there is one, and say so
    if (keepsOffline(path, init)) {
      try {
        const saved = JSON.parse(localStorage.getItem(offlineKey(path)) ?? "null");
        if (saved) {
          window.dispatchEvent(new CustomEvent("finn:offline", { detail: { at: saved.at } }));
          return saved.data as T;
        }
      } catch {
        /* storage unavailable */
      }
    }
    throw e;
  }
  if (res.ok && keepsOffline(path, init)) {
    const data = (await res.json()) as T;
    try {
      localStorage.setItem(offlineKey(path), JSON.stringify({ at: Date.now(), data }));
    } catch {
      /* storage full or unavailable: offline copy is a convenience */
    }
    window.dispatchEvent(new Event("finn:online"));
    return data;
  }
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event("finn:unauthorized"));
    }
    if (res.status === 400 && getAccount().startsWith("u_")) {
      // the sandbox expired (7 days) or was deleted: fall back to the demo network
      setSandbox(null);
      setAccount("demo");
    }
    throw new ApiError(res.status, await res.text());
  }
  return res.json() as Promise<T>;
}

export function useApi<T>(path: string | null, config?: SWRConfiguration<T>) {
  return useSWR<T>(path, (p: string) => api<T>(p), {
    revalidateOnFocus: false,
    keepPreviousData: true,
    ...config,
  });
}

/** Server-sent events over fetch (EventSource cannot send the passcode header). */
export async function stream(
  path: string,
  on: (event: string, data: unknown) => void,
  signal?: AbortSignal,
) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "X-Finn-Passcode": getPasscode(), Accept: "text/event-stream" },
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, await res.text());
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) on(event, JSON.parse(data.join("\n")));
    }
  }
}

// ------------------------------------------------------------------ network
export type Contact = {
  id: string;
  name: string;
  headline: string | null;
  current: string | null;
  is_contact: boolean;
  relationship?: string | null;
  strength?: number;
  last_contact?: string | null;
  context?: string | null;
  themes?: string[];
};

export type Link = {
  kind: string;
  org?: string | null;
  detail: string;
  confidence: "confirmed" | "possible";
  /** declared: the investor recorded it · inferred: two career records overlap */
  basis?: "declared" | "inferred";
  strength: number;
};

export type Paths = {
  target: Contact;
  direct: Link[];
  via: { contact: Contact; link: Link; other_links: Link[]; strength: number }[];
  same_name?: SameName[];
};

/** FR-NET-05: a contact who shares the person's name. Never asserted unless you confirm. */
export type SameName = { contact: Contact; status: "possible" | "likely" | "confirmed"; agrees: string[] };

export type Helper = {
  contact: Contact;
  score: number;
  why: string;
  reasons: string[];
  /** Works at the company now: may hold unpublished price-sensitive information */
  insider?: boolean;
};

export type Nudge = {
  contact: Contact;
  days_since_contact: number;
  event: { id: string; symbol: string; ts: string; category: string; title: string };
  reason: string;
};

export type Account = { account: string; investor: string; contacts: number; accounts: string[] };

export type PersonProfile = {
  id: string;
  name: string;
  headline: string | null;
  current: string | null;
  is_contact: boolean;
  bio: string | null;
  themes: string[];
  roles: { company: string; symbol: string | null; title: string | null; start: number | null; end: number | null; span: string }[];
  education: { school: string; program?: string | null; start?: number | null; end?: number | null }[];
  relationship: { type: string; strength: number; last_contact: string | null; context?: string | null } | null;
  overlaps_with_you: Link[];
  paths?: Paths;
  knows?: { person: Contact; context: string | null }[];
  can_help_on?: { symbol: string; rank: number; score: number; why: string }[];
};

// ------------------------------------------------------------------ push
export type Alert = {
  id: string;
  kind: "volume" | "price" | "category";
  symbol: string;
  ts: string;
  reason: string;
  value: number;
  price_change_pct?: number | null;
  announcement_id?: string;
  title?: string;
};

export type FilingItem = {
  id: string;
  symbol: string;
  ts: string;
  category: string;
  title: string;
  pdf_url: string | null;
};

export type ResultsRow = {
  metric: "revenue" | "ebitda" | "pbt" | "pat";
  value: number | null;
  prev: number | null;
  year_ago: number | null;
  qoq: number | null;
  yoy: number | null;
  /** Set instead of a % when the base is a loss or zero (e.g. "turned profitable") */
  qoq_note?: string | null;
  yoy_note?: string | null;
};

export type ResultsCard = {
  period: string;
  basis: string;
  unit: string;
  is_lender: boolean;
  revenue_label: string;
  ebitda_margin: number | null;
  rows: ResultsRow[];
  cross_check: { status: "match" | "pat_basis" | "differs" | "unavailable"; diffs?: Record<string, number> };
  source: string;
};

export type CardPerson = {
  id: string | null;
  name: string;
  role: string;
  direction: "incoming" | "outgoing" | "reappointed" | string;
  bio: string | null;
  source: string;
  prior: string[];
  education: string[];
  paths: Paths;
};

export type Card = {
  id: string;
  symbol: string;
  company: string;
  ts: string;
  category: string;
  kind: "results" | "management_change" | "material_event" | "filing";
  /** PLAN v2 principle 5: the step this card leads to, chosen in code. */
  next_action?: { label: string; href: string; why: string };
  materiality: number;
  title: string;
  pdf_url: string | null;
  related: FilingItem[];
  alerts: Alert[];
  in_portfolio: boolean;
  /** FINN couldn't place this filing in a category, so it is shown rather than folded */
  unsure?: boolean;
  /** PU-4: Important or Notable (Routine is the folded group), with the reason */
  level?: "important" | "notable";
  level_reason?: string;
  results?: ResultsCard | null;
  people?: CardPerson[];
  helpers: Helper[];
  priority: number;
};

export type Digest = {
  window: { name: string | null; start: string; end: string };
  alerts: Alert[];
  cards: Card[];
  routine: { count: number; items: FilingItem[] };
  nudges: Nudge[];
  /** Q-3: how old the data is; prices are stale once a finished session is missing */
  freshness?: {
    prices_as_of: string | null;
    filings_as_of: string | null;
    sessions_behind: number | null;
    stale: boolean;
  };
  counts: { filings: number; cards: number; routine: number; alerts: number };
};

export type AlertRules = {
  volume_multiple: number;
  price_abs_pct: number;
  categories: string[];
  enabled: { volume: boolean; price: boolean; category: boolean };
  all_categories?: string[];
};

// ------------------------------------------------------------------ pull
export type Cite = { doc: string; page: number | null };
export type Claim = { text: string; cites: Cite[] };
export type Verdict =
  | "delivered"
  | "partly"
  | "missed"
  | "revised"
  | "unclear"
  | "too_early"
  | "not_measurable";

export type PromiseItem = {
  promise_ids: string[];
  verdict: Verdict;
  quote: string;
  said_in: string;
  doc_id: string;
  page: number;
  target: string;
  horizon: string | null;
  deadline: string | null;
  actual: string;
  evidence: string[];
  note: string;
  guard: string | null;
  repeated_in: string[];
  /** number (point or range), direction, milestone (a dated deliverable) or not measurable */
  statement_type?: "number" | "direction" | "milestone" | "not_measurable";
  /** "code" when the verdict is arithmetic on reported numbers; "ai" when only the model could judge it */
  judged_by?: "code" | "ai";
  /** A cited management update that revised, delayed or withdrew the target */
  revised?: { from: string | null; to: string | null; in: string | null; update_id: string } | null;
};

export type DocRef = {
  id: string;
  kind: "transcript" | "annual_report";
  period: string;
  label: string;
  url: string;
  quarter: string | null;
  pages: number;
};

export type Flag = { id: string; tone: "positive" | "negative"; text: string };

export type Financials = {
  is_lender: boolean;
  basis: string;
  unit: string;
  source: string;
  snapshot: {
    fy: string | null;
    revenue: number | null;
    revenue_ttm: number | null;
    operating_profit: number | null;
    margin_pct: number | null;
    margin_label: string;
    pat: number | null;
    pat_ttm: number | null;
    roe_pct: number | null;
    roce_pct: number | null;
    debt_to_equity: number | null;
    market_cap_cr: number | null;
    pe: number | null;
    price: number | null;
  };
  trajectory: {
    annual: { period: string; revenue: number | null; operating_profit: number | null; margin_pct: number | null; pat: number | null }[];
    quarterly: {
      period: string;
      revenue: number | null;
      operating_profit: number | null;
      margin_pct: number | null;
      pat: number | null;
      revenue_yoy: number | null;
      pat_yoy: number | null;
    }[];
    cagr: Record<string, number | null>;
  };
  cash_quality: {
    annual: { period: string; cfo: number | null; fcf: number | null; pat: number | null; cfo_to_pat: number | null }[];
    cfo_to_pat_3y: number | null;
    fcf_3y: number | null;
  };
  balance_sheet: {
    annual: {
      period: string;
      borrowings: number | null;
      net_worth: number | null;
      debt_to_equity: number | null;
      debtor_days?: number | null;
      inventory_days?: number | null;
      payable_days?: number | null;
      working_capital_days?: number | null;
    }[];
    asset_quality?: { period: string; gross_npa_pct: number | null; net_npa_pct: number | null }[];
  };
  flags: Flag[];
};

export type Research = {
  symbol: string;
  company: string;
  generated_at: string;
  latest_quarter: string;
  documents: DocRef[];
  financials: Financials;
  promises: {
    items: PromiseItem[];
    credibility: string | null;
    counts: Partial<Record<Verdict, number>>;
    score: number | null;
  };
  guidance: { id: string; kind: string; quote: string; target: string; doc_id: string; page: number }[];
  business: {
    what_they_do: Claim | null;
    segments: { name: string; share: string | null; cites: Cite[] }[];
    customers_and_markets: Claim[];
    recent_developments: Claim[];
  } | null;
  bull_bear: { bull: Claim[]; bear: Claim[]; watch: Claim[] } | null;
  about: string | null;
  incomplete: string[];
  helpers: Helper[];
  /** task -> "provider/model" that wrote it; absent on views built before provenance. */
  models?: Record<string, string>;
  suggested_questions?: string[];
};

export type QaAnswer = {
  question: string;
  answerable: "yes" | "partly" | "no";
  points: Claim[];
  dropped: number;
  follow_ups: string[];
  searched: { doc: string; pages: number[] }[];
  model: string | null;
  seconds: number;
};

export type ResearchSummary = {
  symbol: string;
  company: string;
  generated_at: string;
  latest_quarter: string;
  counts: Partial<Record<Verdict, number>>;
  score: number | null;
  headline: string | null;
  incomplete: string[];
};

export type Company = { symbol: string; name: string; in_portfolio: number; in_research_set: number };
