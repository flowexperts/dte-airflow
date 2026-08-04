"use client";

import { useEffect } from "react";
import Cal, { getCalApi } from "@calcom/embed-react";

const NAMESPACE = "dte-demo-call";
const CAL_LINK = "bhavaniravi/dte-demo-call";

export function CalEmbed() {
  useEffect(() => {
    (async () => {
      const cal = await getCalApi({ namespace: NAMESPACE });
      cal("ui", {
        hideEventTypeDetails: false,
        layout: "month_view",
        cssVarsPerTheme: {
          dark: {
            "cal-brand": "#e8441a",
            "cal-bg": "#141210",
            "cal-bg-emphasis": "#1a1714",
            "cal-border": "#2a2720",
            "cal-text": "#f2ede4",
            "cal-text-muted": "#b8b0a4",
          },
          light: {
            "cal-brand": "#c4381a",
          },
        },
      });
    })();
  }, []);

  return (
    <Cal
      namespace={NAMESPACE}
      calLink={CAL_LINK}
      style={{ width: "100%", height: "100%", overflow: "scroll" }}
      config={{ layout: "month_view", theme: "dark" }}
    />
  );
}
