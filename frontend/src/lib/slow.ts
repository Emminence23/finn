import { useEffect, useState } from "react";

/** True once something has been loading for `ms` (8 s by default): time to say what's
 *  happening and offer a retry, instead of grey blocks with no end. */
export function useSlow(loading: boolean, ms = 8000): boolean {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!loading) {
      setSlow(false);
      return;
    }
    const t = setTimeout(() => setSlow(true), ms);
    return () => clearTimeout(t);
  }, [loading, ms]);
  return slow;
}
