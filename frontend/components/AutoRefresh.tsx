"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/** Re-fetches the server components on an interval. Motivated motion only:
 *  the countdown tells the operator the reading is live and when it updates. */
export default function AutoRefresh({ seconds = 30 }: { seconds?: number }) {
  const router = useRouter();
  const [remaining, setRemaining] = useState(seconds);

  useEffect(() => {
    const tick = setInterval(() => {
      setRemaining((value) => {
        if (value <= 1) {
          router.refresh();
          return seconds;
        }
        return value - 1;
      });
    }, 1000);
    return () => clearInterval(tick);
  }, [router, seconds]);

  return (
    <span className="num text-[11px] text-faint" aria-live="off">
      refresh {remaining}s
    </span>
  );
}
