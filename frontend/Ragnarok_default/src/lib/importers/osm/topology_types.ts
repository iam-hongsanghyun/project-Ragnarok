/**
 * Parsed Overpass shapes shared between the two topology pipelines
 * (`convert.ts` = raw, `topology_pypsa_earth.ts` = cleaned).
 */

export interface Substation {
  osmId: number;
  osmType: string;
  lat: number;
  lon: number;
  voltagesKv: number[];
  tags: Record<string, string>;
}

export interface Line {
  osmId: number;
  geometry: Array<[number, number]>; // [lat, lon]
  lengthKm: number;
  voltageKv: number;
  frequencyHz: number;
  circuits: number;
  isCable: boolean;
  tags: Record<string, string>;
}

export interface Parsed {
  substations: Substation[];
  lines: Line[];
}
