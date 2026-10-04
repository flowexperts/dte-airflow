/**
 * Target for every `createPortal`. Portals escape `.dte-root`, and the design
 * tokens (`--surface`, `--border`, …) are scoped to it — portaling straight
 * into `document.body` renders dialogs and popovers with no background.
 */
let host: HTMLElement | null = null;

export function portalHost(): HTMLElement {
  if (!host || !host.isConnected) {
    host = document.createElement("div");
    host.className = "dte-root";
    document.body.appendChild(host);
  }
  return host;
}
