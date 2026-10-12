// Leaflet: підложка, райони, маркери Metro і «я». L — глобальний (vendor/leaflet/leaflet.js).
const KYIV_BOUNDS = [[50.213, 30.239], [50.591, 30.826]];
// CARTO dark_nolabels тепер вимагає API-ключ (тайли з водяним знаком), тож поки — безключова Esri Dark Gray Base.
const TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
const ATTRIBUTION = 'Esri, HERE, Garmin, © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function createMap(el) {
  const map = L.map(el, { zoomControl: false, minZoom: 9, maxZoom: 17 });
  map.attributionControl.setPrefix(false);
  L.tileLayer(TILES, { attribution: ATTRIBUTION, maxNativeZoom: 16, maxZoom: 19 }).addTo(map);
  map.fitBounds(KYIV_BOUNDS, { padding: [8, 8] });

  const c = { border: css('--border'), text: css('--text'), bg: css('--bg'), accent: css('--accent'), muted: css('--muted') };
  const storeLayer = L.layerGroup().addTo(map);
  const stores = new Map(); // id → circleMarker
  let me = null, meAcc = null, selected = null;

  const storeStyle = (on) => on
    ? { radius: 9, color: c.accent, weight: 4, fillColor: c.bg, fillOpacity: 1 } // кільце — щоб не плутати з точкою «я»
    : { radius: 6, color: c.bg, weight: 2, fillColor: c.text, fillOpacity: 1 };

  return {
    map,

    setRaions(geojson) {
      L.geoJSON(geojson, { interactive: false, style: { color: c.border, opacity: 1, weight: 1, dashArray: '3 4', fill: false } }).addTo(map);
    },

    setStores(geojson, onSelect, label) {
      storeLayer.clearLayers();
      stores.clear();
      for (const f of geojson.features) {
        const p = f.properties;
        const m = L.circleMarker([p.lat, p.lon], { ...storeStyle(false), bubblingMouseEvents: false })
          .on('click', () => onSelect(p.id))
          .addTo(storeLayer);
        // Назви з OSM — недовірені: лише textContent / aria-label, не HTML.
        m.getElement()?.setAttribute('aria-label', label(p));
        m.getElement()?.setAttribute('role', 'button');
        m.getElement()?.setAttribute('tabindex', '0');
        m.getElement()?.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') onSelect(p.id); });
        stores.set(p.id, m);
      }
    },

    selectStore(id) {
      if (selected) stores.get(selected)?.setStyle(storeStyle(false)).setRadius(6);
      selected = id;
      const m = stores.get(id);
      if (m) m.setStyle(storeStyle(true)).setRadius(9).bringToFront();
    },

    setMe(latlng, accuracy) {
      if (!me) {
        meAcc = L.circle(latlng, { radius: accuracy || 0, interactive: false, stroke: false, fillColor: c.accent, fillOpacity: 0.15 }).addTo(map);
        me = L.circleMarker(latlng, { radius: 7, color: c.text, weight: 2, fillColor: c.accent, fillOpacity: 1, interactive: false }).addTo(map);
      } else {
        me.setLatLng(latlng);
        meAcc.setLatLng(latlng).setRadius(accuracy || 0);
      }
    },

    // Показати «я» і магазин так, щоб їх не перекривали картка та панелі.
    fitTrip(a, b) {
      const wide = window.matchMedia('(min-width: 900px)').matches;
      const opts = wide
        ? { paddingTopLeft: [60, 80], paddingBottomRight: [420, 100] }
        : { paddingTopLeft: [40, 90], paddingBottomRight: [40, Math.min(360, window.innerHeight * 0.5)] };
      map.fitBounds(L.latLngBounds([a, b]), { ...opts, maxZoom: 15 });
    },
  };
}
