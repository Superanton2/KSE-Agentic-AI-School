// Leaflet: підложка, райони, маркери Metro і «я». L — глобальний (vendor/leaflet/leaflet.js).
const KYIV_BOUNDS = [[50.213, 30.239], [50.591, 30.826]];
// CARTO dark_nolabels тепер вимагає API-ключ (тайли з водяним знаком), тож поки — безключова Esri Dark Gray Base.
const TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
const ATTRIBUTION = 'Esri, HERE, Garmin, © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Мітка магазину — червона шпилька, як у картах. Розмітка наша (не з мережі), колір — з CSS (--dest).
const PIN_SVG = '<svg viewBox="0 0 24 32" aria-hidden="true"><path class="pin-body" d="M12 .8C5.8.8.8 5.7.8 11.9c0 8.3 11.2 19.3 11.2 19.3s11.2-11 11.2-19.3C23.2 5.7 18.2.8 12 .8z"/><circle class="pin-dot" cx="12" cy="12" r="4.2"/></svg>';
const pinIcon = (selected) => L.divIcon({
  className: selected ? 'pin is-selected' : 'pin',
  html: PIN_SVG,
  iconSize: selected ? [34, 45] : [22, 29],
  iconAnchor: selected ? [17, 45] : [11, 29],
});

export function createMap(el) {
  // minZoom 10 і maxBounds — щоб не можна було відвести карту далеко від Києва.
  const map = L.map(el, {
    zoomControl: false, minZoom: 10, maxZoom: 17,
    maxBounds: L.latLngBounds(KYIV_BOUNDS).pad(0.35), maxBoundsViscosity: 0.8,
  });
  map.attributionControl.setPrefix(false);
  L.tileLayer(TILES, { attribution: ATTRIBUTION, maxNativeZoom: 16, maxZoom: 19 }).addTo(map);
  // Цілий zoom (дробовий дає шви між тайлами); на вузькому екрані fitBounds дав би 9 — це область, а не місто.
  map.setView(L.latLngBounds(KYIV_BOUNDS).getCenter(), Math.max(10, map.getBoundsZoom(KYIV_BOUNDS)));

  const c = { border: css('--border'), text: css('--text'), bg: css('--bg'), accent: css('--accent'), muted: css('--muted') };
  const storeLayer = L.layerGroup().addTo(map);
  const stores = new Map(); // id → L.marker
  let me = null, meAcc = null, start = null, selected = null;

  // Доступність мітки: роль, назва (OSM — недовірена, лише aria-label) і Enter/пробіл → вибір.
  // Викликати після кожного setIcon: Leaflet створює новий елемент.
  const a11y = (m) => {
    const el = m.getElement();
    if (!el) return;
    el.setAttribute('role', 'button');
    el.setAttribute('aria-label', m.storeLabel);
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); m.fire('click'); }
    });
  };

  return {
    map,

    setRaions(geojson) {
      // Окремий pane під маркерами: райони вантажаться пізніше за точку «я» і не мають її перекривати.
      if (!map.getPane('raions')) map.createPane('raions').style.zIndex = 350;
      L.geoJSON(geojson, { pane: 'raions', interactive: false, style: { color: c.border, opacity: 1, weight: 1, dashArray: '3 4', fill: false } }).addTo(map);
    },

    setStores(geojson, onSelect, label) {
      storeLayer.clearLayers();
      stores.clear();
      for (const f of geojson.features) {
        const p = f.properties;
        const m = L.marker([p.lat, p.lon], { icon: pinIcon(false), keyboard: true, riseOnHover: true })
          .on('click', () => onSelect(p.id))
          .addTo(storeLayer);
        m.storeLabel = label(p);
        a11y(m);
        stores.set(p.id, m);
      }
    },

    selectStore(id) {
      const restyle = (m, on) => {
        m.setIcon(pinIcon(on)).setZIndexOffset(on ? 1000 : 0);
        a11y(m);
      };
      if (selected && stores.has(selected)) restyle(stores.get(selected), false);
      selected = id;
      if (stores.has(id)) restyle(stores.get(id), true);
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

    // Точка старту з пошуку (якщо їдемо не з «моєї локації»): біла точка з темним обідком.
    setStart(latlng) {
      if (!latlng) { start?.remove(); start = null; return; }
      if (start) start.setLatLng(latlng);
      else start = L.circleMarker(latlng, { radius: 7, color: c.bg, weight: 3, fillColor: c.text, fillOpacity: 1, interactive: false }).addTo(map);
      start.bringToFront();
    },

    panTo(latlng) {
      map.setView(latlng, Math.max(map.getZoom(), 13));
    },

    // Показати «я» і магазин так, щоб їх не перекривали картка та панелі.
    fitTrip(a, b) {
      const wide = window.matchMedia('(min-width: 900px)').matches;
      const top = (document.querySelector('.top')?.getBoundingClientRect().bottom ?? 80) + 24; // пігулка + підказка
      const opts = wide
        ? { paddingTopLeft: [60, top], paddingBottomRight: [420, 100] }
        : { paddingTopLeft: [40, top], paddingBottomRight: [40, Math.min(360, window.innerHeight * 0.5)] };
      map.fitBounds(L.latLngBounds([a, b]), { ...opts, maxZoom: 15 });
    },
  };
}
