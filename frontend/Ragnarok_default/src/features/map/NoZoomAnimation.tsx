import { useEffect } from 'react';
import { useMap } from 'react-leaflet';

/**
 * Force Leaflet's zoom animation off on the live map instance.
 *
 * The `zoomAnimation={false}` prop on <MapContainer> only applies when the map
 * is first created. react-leaflet keeps a single map instance for the
 * component's lifetime (and preserves it across hot-reloads), so a map created
 * earlier can still have animation enabled. An in-flight zoom animation that
 * resolves after its panel collapses or the map is torn down crashes in
 * `_onZoomTransitionEnd` (`Cannot read properties of undefined (reading
 * '_leaflet_pos')`), because that handler calls `_move()` against panes that no
 * longer exist.
 *
 * Disabling it imperatively guarantees `_animatingZoom` never becomes true, so
 * `_onZoomTransitionEnd` always early-returns and the crash cannot occur — even
 * on a map instance that was created before this fix (e.g. preserved by HMR).
 */
export function NoZoomAnimation() {
  const map = useMap();
  useEffect(() => {
    map.options.zoomAnimation = false;
    (map as unknown as { _zoomAnimated: boolean })._zoomAnimated = false;
  }, [map]);
  return null;
}
