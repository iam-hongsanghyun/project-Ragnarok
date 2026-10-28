/**
 * The one basemap every Leaflet map in the app uses.
 *
 * Esri "Canvas / World Light Gray Base": a keyless raster layer, light and low-contrast so the network overlay
 * carries the colour. It replaces the CARTO `basemaps.cartocdn.com` raster tiles, which now answer every request with
 * an "API KEY REQUIRED" image unless a CARTO key is attached (checked 2026-10-29). Note the tile path is
 * `{z}/{y}/{x}` (row before column), unlike the OSM `{z}/{x}/{y}` scheme.
 *
 * The layer has no place names (a deliberate choice: the map shows the model, not a road atlas). Its detail is not uniform:
 * from zoom 14 outside cities the service answers with a "Map data not yet available" tile (checked on rural Korea,
 * 2026-10-29), so tiles are requested up to zoom 13 only and Leaflet stretches them beyond that.
 */
export const BASEMAP_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}';
export const BASEMAP_ATTRIBUTION = 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ';
export const BASEMAP_MAX_NATIVE_ZOOM = 13;
