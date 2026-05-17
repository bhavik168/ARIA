import { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import type { MapMarkers } from "../types";

const TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string) || "";

// Capitol Hill, Seattle — incident scenario coordinates
const INC:  [number, number] = [-122.3194, 47.6147];
const UNIT: [number, number] = [-122.3255, 47.6179]; // Station 10
const HOSP: [number, number] = [-122.3168, 47.6079]; // Swedish Medical Center

const ROUTE_FC = {
  type: "FeatureCollection" as const,
  features: [{
    type: "Feature" as const,
    properties: {},
    geometry: { type: "LineString" as const, coordinates: [UNIT, [-122.3255, 47.6147], INC] },
  }],
};
const TRANSPORT_FC = {
  type: "FeatureCollection" as const,
  features: [{
    type: "Feature" as const,
    properties: {},
    geometry: { type: "LineString" as const, coordinates: [INC, [-122.3168, 47.6147], HOSP] },
  }],
};

interface LiveMapProps {
  markers: MapMarkers;
  showRoute: boolean;
  showHospital: boolean;
}

// ── Mapbox GL JS implementation ──────────────────────────────────────────────

function MapboxLiveMap({ markers, showRoute, showHospital }: LiveMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef       = useRef<mapboxgl.Map | null>(null);
  const unitRef      = useRef<mapboxgl.Marker | null>(null);
  const hospRef      = useRef<mapboxgl.Marker | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  // Init map once
  useEffect(() => {
    if (!containerRef.current) return;
    mapboxgl.accessToken = TOKEN;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: INC,
      zoom: 14.5,
      attributionControl: false,
    });
    mapRef.current = map;

    map.on("load", () => {
      // Route source + layers (visible toggled reactively)
      map.addSource("route", { type: "geojson", data: ROUTE_FC });
      map.addLayer({
        id: "route-glow",
        type: "line",
        source: "route",
        paint: { "line-color": "#0e7490", "line-width": 10, "line-opacity": 0 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#0e7490", "line-width": 3.5, "line-opacity": 0 },
      });

      // Transport (incident → hospital) source + layer
      map.addSource("transport", { type: "geojson", data: TRANSPORT_FC });
      map.addLayer({
        id: "transport-line",
        type: "line",
        source: "transport",
        paint: {
          "line-color": "#16a34a",
          "line-width": 2,
          "line-opacity": 0,
          "line-dasharray": [3, 5],
        },
      });

      // Incident marker — calm breath ring + red core
      const incEl = document.createElement("div");
      incEl.style.cssText =
        "width:44px;height:44px;border-radius:50%;background:rgba(239,68,68,0.18);" +
        "display:flex;align-items:center;justify-content:center;" +
        "animation:breath 4s ease-in-out infinite;";
      const core = document.createElement("div");
      core.style.cssText =
        "width:16px;height:16px;border-radius:50%;background:#dc2626;" +
        "border:2.5px solid #fff;box-shadow:0 0 0 3px rgba(220,38,38,0.25);";
      incEl.appendChild(core);
      new mapboxgl.Marker({ element: incEl, anchor: "center" }).setLngLat(INC).addTo(map);

      setMapLoaded(true);
    });

    return () => {
      map.remove();
      mapRef.current = null;
      unitRef.current = null;
      hospRef.current = null;
    };
  }, []);

  // React to marker/layer changes after map is loaded
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;

    // Unit MED-1 marker
    if (markers.unit && !unitRef.current) {
      const el = document.createElement("div");
      el.style.cssText =
        "padding:4px 8px;background:#0f172a;border:2px solid #2563eb;" +
        "border-radius:4px;color:#60a5fa;font-family:'JetBrains Mono',monospace;" +
        "font-size:10px;font-weight:700;letter-spacing:0.05em;white-space:nowrap;";
      el.textContent = "MED-1";
      unitRef.current = new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat(UNIT)
        .addTo(map);
    }

    // Route layers
    if (map.getLayer("route-line")) {
      map.setPaintProperty("route-line", "line-opacity", showRoute ? 0.95 : 0);
      map.setPaintProperty("route-glow", "line-opacity", showRoute ? 0.12 : 0);
    }

    // Hospital marker
    if (showHospital && !hospRef.current) {
      const el = document.createElement("div");
      el.style.cssText =
        "width:28px;height:28px;background:#0f172a;border:2px solid #16a34a;" +
        "border-radius:4px;display:flex;align-items:center;justify-content:center;";
      el.innerHTML =
        '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
        '<rect x="1" y="5" width="12" height="4" fill="#16a34a"/>' +
        '<rect x="5" y="1" width="4" height="12" fill="#16a34a"/>' +
        "</svg>";
      hospRef.current = new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat(HOSP)
        .addTo(map);
    }
    if (map.getLayer("transport-line")) {
      map.setPaintProperty("transport-line", "line-opacity", showHospital ? 0.5 : 0);
    }
  }, [mapLoaded, markers, showRoute, showHospital]);

  return (
    <div style={{ position: "relative", width: "100%", height: 320, borderRadius: 6, overflow: "hidden" }}>
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />

      {/* Map overlay chips — light theme */}
      <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6, fontSize: 9.5, letterSpacing: "0.1em", pointerEvents: "none" }}>
        {(["LIGHT-V11", "47.6147°N · -122.3194°W"] as const).map((label) => (
          <span
            key={label}
            className="mono"
            style={{ padding: "3px 7px", background: "rgba(255,255,255,0.9)", border: "1px solid var(--border-dim)", borderRadius: 3, color: "var(--text-secondary)" }}
          >
            {label}
          </span>
        ))}
      </div>

      {/* Map legend */}
      <div style={{ position: "absolute", bottom: 8, left: 8, display: "flex", flexDirection: "column", gap: 3, fontSize: 10, background: "rgba(255,255,255,0.9)", border: "1px solid var(--border-dim)", borderRadius: 3, padding: "5px 8px", color: "var(--text-secondary)", pointerEvents: "none" }}>
        <div><span className="dot" style={{ color: "#dc2626", marginRight: 6 }} />Incident</div>
        {markers.unit && <div><span className="dot" style={{ color: "#2563eb", marginRight: 6 }} />Ambulance</div>}
        {showHospital && <div><span className="dot" style={{ color: "#16a34a", marginRight: 6 }} />Hospital</div>}
      </div>

      {/* Auto-fit badge */}
      {markers.unit && (
        <div className="mono" style={{ position: "absolute", top: 8, right: 8, padding: "3px 7px", background: "rgba(6,182,212,0.18)", border: "1px solid rgba(6,182,212,0.5)", borderRadius: 3, fontSize: 9.5, color: "#0369a1", letterSpacing: "0.1em", pointerEvents: "none" }}>
          AUTO-FIT
        </div>
      )}
    </div>
  );
}

// ── SVG fallback (no token configured) ──────────────────────────────────────

const incident  = { x: 480, y: 250 };
const unitMed1  = { x: 220, y: 380 };
const hospital  = { x: 660, y: 130 };
const routePath = `M ${unitMed1.x} ${unitMed1.y} L 360 380 L 360 250 L ${incident.x} ${incident.y}`;
const transportPath = `M ${incident.x} ${incident.y} L 580 250 L 580 130 L ${hospital.x} ${hospital.y}`;

function SvgLiveMap({ markers, showRoute, showHospital }: LiveMapProps) {
  return (
    <div style={{ position: "relative", width: "100%", height: 320, background: "var(--bg-deep)", border: "1px solid var(--border-dim)", borderRadius: 6, overflow: "hidden" }}>
      <div className="map-grid" style={{ position: "absolute", inset: 0 }} />

      <svg viewBox="0 0 800 500" preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
        <g stroke="#cdd5e1" strokeWidth="22" strokeLinecap="square" fill="none">
          <path d="M 0 250 L 800 250" /><path d="M 360 0 L 360 500" />
          <path d="M 580 0 L 580 500" /><path d="M 0 130 L 800 130" /><path d="M 0 380 L 800 380" />
        </g>
        <g stroke="#e0e5ee" strokeWidth="16" strokeLinecap="square" fill="none">
          <path d="M 0 250 L 800 250" /><path d="M 360 0 L 360 500" />
          <path d="M 580 0 L 580 500" /><path d="M 0 130 L 800 130" /><path d="M 0 380 L 800 380" />
        </g>
        <g stroke="#e8ecf3" strokeWidth="3" fill="none">
          <path d="M 100 0 L 100 500" /><path d="M 220 0 L 220 500" />
          <path d="M 470 0 L 470 500" /><path d="M 700 0 L 700 500" />
          <path d="M 0 60 L 800 60" /><path d="M 0 190 L 800 190" />
          <path d="M 0 320 L 800 320" /><path d="M 0 440 L 800 440" />
        </g>

        <g fill="#475569" fontFamily="JetBrains Mono, monospace" fontSize="10" letterSpacing="1">
          <text x="20" y="245" opacity="0.7">E PIKE ST</text>
          <text x="370" y="80" opacity="0.7">12TH AVE</text>
          <text x="590" y="80" opacity="0.7">BROADWAY</text>
          <text x="20" y="375" opacity="0.7">E PINE ST</text>
        </g>

        {showRoute && (
          <>
            <path d={routePath} fill="none" stroke="#0e7490" strokeWidth="10" strokeLinecap="round" strokeLinejoin="round" opacity="0.12" />
            <path d={routePath} fill="none" stroke="#0e7490" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.95" className="route-dash" />
          </>
        )}
        {showHospital && (
          <path d={transportPath} fill="none" stroke="#16a34a" strokeWidth="2" strokeDasharray="3 5" opacity="0.5" />
        )}

        <g transform={`translate(${incident.x}, ${incident.y})`}>
          <circle r="22" fill="rgba(239,68,68,0.18)" className="breath" style={{ transformOrigin: "center" }} />
          <circle r="8" fill="#dc2626" stroke="#ffffff" strokeWidth="2" />
          <circle r="3" fill="#fff" />
        </g>

        {markers.unit && (
          <g transform={`translate(${unitMed1.x}, ${unitMed1.y})`}>
            <rect x="-14" y="-10" width="28" height="20" rx="3" fill="#0a0d12" stroke="#2563eb" strokeWidth="2" />
            <text x="0" y="3" textAnchor="middle" fontFamily="JetBrains Mono, monospace" fontWeight="700" fontSize="9" fill="#1d4ed8">MED-1</text>
          </g>
        )}
        {showHospital && (
          <g transform={`translate(${hospital.x}, ${hospital.y})`}>
            <rect x="-12" y="-12" width="24" height="24" rx="3" fill="#0a0d12" stroke="#16a34a" strokeWidth="2" />
            <rect x="-6" y="-2" width="12" height="4" fill="#16a34a" />
            <rect x="-2" y="-6" width="4" height="12" fill="#16a34a" />
          </g>
        )}
      </svg>

      <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6, fontSize: 9.5, letterSpacing: "0.1em" }}>
        {(["LIGHT-V11", "47.6147°N · -122.3194°W"] as const).map((label) => (
          <span key={label} className="mono" style={{ padding: "3px 7px", background: "rgba(255,255,255,0.9)", border: "1px solid var(--border-dim)", borderRadius: 3, color: "var(--text-secondary)" }}>{label}</span>
        ))}
      </div>

      <div style={{ position: "absolute", bottom: 8, left: 8, display: "flex", flexDirection: "column", gap: 3, fontSize: 10, background: "rgba(255,255,255,0.9)", border: "1px solid var(--border-dim)", borderRadius: 3, padding: "5px 8px", color: "var(--text-secondary)" }}>
        <div><span className="dot" style={{ color: "#dc2626", marginRight: 6 }} />Incident</div>
        {markers.unit && <div><span className="dot" style={{ color: "#2563eb", marginRight: 6 }} />Ambulance</div>}
        {showHospital && <div><span className="dot" style={{ color: "#16a34a", marginRight: 6 }} />Hospital</div>}
      </div>

      <div style={{ position: "absolute", top: 8, right: 8, display: "flex", flexDirection: "column", border: "1px solid var(--border-dim)", borderRadius: 4, overflow: "hidden", background: "rgba(255,255,255,0.9)" }}>
        <button className="btn" style={{ width: 26, height: 26, color: "var(--text-secondary)", borderBottom: "1px solid var(--border-dim)", fontSize: 14 }}>+</button>
        <button className="btn" style={{ width: 26, height: 26, color: "var(--text-secondary)", fontSize: 14 }}>−</button>
      </div>

      {markers.unit && (
        <div className="mono" style={{ position: "absolute", top: 8, right: 44, padding: "3px 7px", background: "rgba(6,182,212,0.18)", border: "1px solid rgba(6,182,212,0.5)", borderRadius: 3, fontSize: 9.5, color: "#0369a1", letterSpacing: "0.1em" }}>
          AUTO-FIT
        </div>
      )}
    </div>
  );
}

// ── Public export — picks Mapbox or SVG based on token ─────────────────────

export default function LiveMap(props: LiveMapProps) {
  return TOKEN ? <MapboxLiveMap {...props} /> : <SvgLiveMap {...props} />;
}
