/** Turns any failure into a specific, honest message: whose fault it is, what failed, and
 * what to do. The API sends {error: {code, message, detail, request_id}} (backend/app/errors.py);
 * anything else (a dropped connection, a timeout, a proxy page) is named here. */
import { ApiError } from "./api";

export type Explained = {
  /** one line for the person */
  title: string;
  /** what exactly failed, small print */
  detail?: string;
  /** worth trying again now */
  retry: boolean;
  code: string;
  requestId?: string;
};

type Body = { error?: { code: string; message: string; detail?: string | null; request_id?: string }; detail?: unknown };

function parse(text: string): Body | null {
  try {
    return JSON.parse(text) as Body;
  } catch {
    return null;
  }
}

export function explain(e: unknown): Explained {
  if (e instanceof DOMException && (e.name === "TimeoutError" || e.name === "AbortError")) {
    return {
      code: "timeout",
      title: "FINN took too long to answer, so the app stopped waiting.",
      detail: "The server may still be working on it (news searches and first reads of a company take up to two minutes). Ask again in a minute; a finished answer is saved.",
      retry: true,
    };
  }
  if (e instanceof ApiError) {
    const b = parse(e.message);
    if (b?.error) {
      const { code, message, detail, request_id } = b.error;
      return {
        code,
        title: message,
        detail: [detail, request_id && code === "internal" ? `Reference ${request_id}` : null].filter(Boolean).join(" · ") || undefined,
        retry: !["ai_quota", "daily_budget", "unauthorized", "bad_request"].includes(code),
        requestId: request_id,
      };
    }
    // not FINN's own answer: Render's proxy while the server starts or redeploys
    if (e.status === 502 || e.status === 503 || e.status === 504) {
      return {
        code: "server_starting",
        title: "FINN's server is restarting (a new version is going live, or it was asleep).",
        detail: `Hosting answered ${e.status} before FINN did. It is usually back within a minute.`,
        retry: true,
      };
    }
    if (e.status === 401) return { code: "unauthorized", title: "Enter the passcode first.", retry: false };
    const plain = typeof b?.detail === "string" ? b.detail : e.message.slice(0, 160);
    return { code: `http_${e.status}`, title: plain || `FINN answered with an error (${e.status}).`, retry: e.status >= 500 };
  }
  if (e instanceof TypeError) {
    // fetch() itself failed: no response at all
    const offline = typeof navigator !== "undefined" && navigator.onLine === false;
    return offline
      ? { code: "offline", title: "Your phone is offline.", detail: "Nothing was sent. Ask again once you're connected.", retry: true }
      : {
          code: "no_response",
          title: "The connection to FINN's server dropped before an answer came back.",
          detail: "The free server sleeps after 15 idle minutes and takes about 30 seconds to wake, and a phone locking or switching networks cuts a long request. Your question may still finish on the server; asking again picks up a saved answer.",
          retry: true,
        };
  }
  return { code: "unknown", title: "Something unexpected went wrong in the app.", detail: e instanceof Error ? e.message.slice(0, 200) : String(e), retry: true };
}

/** One line for places with room for a sentence only. */
export function explainLine(e: unknown): string {
  const x = explain(e);
  return x.detail && x.code !== "internal" ? `${x.title} ${x.detail}` : x.title;
}
