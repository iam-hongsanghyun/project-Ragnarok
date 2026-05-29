import { useEffect, useRef } from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import { useMap } from 'react-leaflet';

export function FitToBounds({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap();
  const fitted = useRef(false);

  useEffect(() => {
    if (bounds && !fitted.current) {
      map.fitBounds(bounds, { padding: [30, 30] });
      fitted.current = true;
    }
  }, [bounds, map]);

  return null;
}
