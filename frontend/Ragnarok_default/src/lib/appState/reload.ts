/**
 * Reloads and moves the app makes itself.
 *
 * The page asks before it is left while it holds work (`beforeunload`, armed in App), so a stray back-swipe
 * or a closed tab does not lose the model. That question must never block a reload the app starts on its
 * own: applying a project's settings or connecting to another session would otherwise stop and wait for a
 * person, and an agent working over MCP would sit there until someone clicked. These helpers mark the
 * unload as the app's, and the guard lets it through.
 */
let leaving = false;

/** Reload the page without the leave-site question. */
export function reloadPage(): void {
  leaving = true;
  window.location.reload();
}

/** Go to `url` without the leave-site question. */
export function goTo(url: string): void {
  leaving = true;
  window.location.assign(url);
}

/** True when the app itself started the unload (the guard must not ask). */
export function isAppLeaving(): boolean {
  return leaving;
}
