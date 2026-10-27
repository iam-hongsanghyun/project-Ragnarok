/**
 * Who owns the working model when the app loads: the server session or the browser?
 *
 * The session is the source of truth, and it may be shared (an agent builds in it
 * while this UI sits in an iframe). A fresh browser starts with an empty default
 * model, so on load it must ADOPT the session's model, never push its own over it.
 * Local state is pushed only when the session is empty, or after the user loads a
 * model on purpose.
 */
import type { WorkbookModel } from 'lib/types';

/** True when the session holds a model worth adopting: any sheet with rows. */
export function sessionHasModel(model: WorkbookModel | null | undefined): model is WorkbookModel {
  return !!model && Object.values(model).some((rows) => Array.isArray(rows) && rows.length > 0);
}

/** How long after adopting the session's model the browser waits for the effects the adoption
 *  itself triggers (config sheets written back into its mirror) before it counts resyncs as the user's. */
export const ADOPTION_SETTLE_MS = 150;

export interface StaticResyncState {
  /** The resync request counter (it bumps whenever a structural edit wants a push). */
  tick: number;
  /** The boot check of the session has finished (adopted it, or found it empty). */
  bootChecked: boolean;
  /** The counter value when the session's model was adopted (0 = nothing adopted). */
  adoptedAtTick: number;
}

/**
 * Whether a requested static resync may be sent to the session.
 *
 * Requests made before the boot check, or before the session's model was adopted,
 * came from the default empty model: sending them would wipe the session's model.
 */
export function mayPushStaticResync({ tick, bootChecked, adoptedAtTick }: StaticResyncState): boolean {
  if (tick === 0 || !bootChecked) return false;
  return tick > adoptedAtTick;
}
