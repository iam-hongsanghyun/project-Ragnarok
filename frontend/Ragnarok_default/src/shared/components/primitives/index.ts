/**
 * UI primitives — canonical structural components.
 *
 * Every view in Ragnarok is built from a small set of primitives that bundle
 * the shared className conventions in one place. New views MUST use these
 * primitives rather than inventing their own className soup; existing views
 * have been migrated over.
 *
 * Available primitives:
 *   ViewPanel      — outer container for a view (replaces .view / .*-view).
 *   ViewPaneHeader — top section: bordered strip across the full width.
 *                    Replaces .view-toolbar / .analytics-outer-header /
 *                    the ad-hoc Build step-strip wrapper.
 *   LeftRail       — left (or right) rail with title slot + scroll body.
 *                    Replaces .view-rail / .analytics-view-rail /
 *                    .settings-section-nav.
 *   TopTab         — sub-tab navigation pill row.
 *                    Replaces .subnav + manual .subnav-btn rendering.
 *
 * The primitives are thin wrappers: they render the canonical className
 * tree and pass children through. They do not impose layout choices that
 * a view might need to override (e.g., ResizablePanels still wraps them
 * at the view level when the rail is resizable).
 */
export { ViewPanel } from './ViewPanel';
export { ViewPaneHeader } from './ViewPaneHeader';
export { LeftRail } from './LeftRail';
export { TopTab } from './TopTab';
export type { TopTabItem } from './TopTab';
