// (iter45→iter47) Plan magasin interactif — dessin de zones (SVG natif) et
// visualisation temps réel. Chaque zone est liée à un NUMÉRO DE NUIT (Nuit 1,
// Nuit 2…). Une palette 12 couleurs distingue les nuits ; plusieurs rectangles
// et/ou polygones peuvent représenter la même nuit. Support zoom molette + pan
// drag + pinch tactile.
import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import {
    Plus, Square, Pentagon, MousePointer2, Trash2, Save, X,
    MapPin, Eye, Loader2, PencilRuler, ZoomIn, ZoomOut, Maximize2,
} from "lucide-react";
import { toast } from "sonner";
import { compressImage } from "./api";

// (iter47) Palette 12 couleurs — 1 par nuit (cycle si > 12 nuits)
const NIGHT_COLORS = [
    "#10B981", "#3B82F6", "#F59E0B", "#A855F7", "#EF4444", "#0EA5E9",
    "#EC4899", "#22C55E", "#FACC15", "#6366F1", "#14B8A6", "#F97316",
];
const nightColor = (n) => {
    const k = Math.max(1, parseInt(n, 10) || 1);
    return NIGHT_COLORS[(k - 1) % NIGHT_COLORS.length];
};

export default function SuiviFloorplan({ state, actions, readOnly = false, onOpenAllee, phaseKind = "eeg" }) {
    const [plans, setPlans] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeFloor, setActiveFloor] = useState(0);
    const [tool, setTool] = useState("select");
    const [selectedZoneId, setSelectedZoneId] = useState(null);
    const [drawingPoly, setDrawingPoly] = useState([]);
    const [rectDraft, setRectDraft] = useState(null);
    // (iter47) Nuit active pour dessin — nouvelle zone créée avec cette nuit.
    const [drawNuit, setDrawNuit] = useState(1);
    const [nightFilter, setNightFilter] = useState("all");
    const [uploadingNew, setUploadingNew] = useState(false);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const [pendingNewLabel, setPendingNewLabel] = useState("");
    const [imgSize, setImgSize] = useState({ w: 1000, h: 700 });
    // (iter46) Zoom & pan — transform CSS appliqué au conteneur SVG
    const [zoom, setZoom] = useState(1);
    const [pan, setPan] = useState({ x: 0, y: 0 });
    const [panDrag, setPanDrag] = useState(null); // {startX, startY, panX, panY}
    const [pinch, setPinch] = useState(null); // {dist, midX, midY}
    const svgRef = useRef(null);
    const wrapperRef = useRef(null);
    const fileInputRef = useRef(null);

    const reload = useCallback(async () => {
        setLoading(true);
        const list = await actions.listFloorplans();
        // (iter48) Ne conserve que les plans du phasage courant (EEG ou CAM).
        // Les plans sans phase_kind sont considérés EEG (rétrocompatibilité).
        const filtered = (list || []).filter((p) => (p.phase_kind || "eeg") === phaseKind);
        setPlans(filtered);
        setLoading(false);
    }, [actions, phaseKind]);
    useEffect(() => { reload(); }, [reload]);

    const plan = plans[activeFloor] || null;

    // Détermine la taille naturelle de l'image du plan actif
    useEffect(() => {
        if (!plan) return;
        const img = new Image();
        img.onload = () => setImgSize({ w: img.naturalWidth, h: img.naturalHeight });
        img.src = plan.image_data_url;
    }, [plan]);

    // viewBox SVG basé sur la taille image → coordonnées normalisées via <svg viewBox>
    const vbW = imgSize.w, vbH = imgSize.h;

    // Reset zoom/pan quand on change d'étage
    useEffect(() => { setZoom(1); setPan({ x: 0, y: 0 }); }, [activeFloor]);

    // ---- Zoom molette (Ctrl+molette OU molette simple sur canvas) ----
    const onWheel = (e) => {
        if (!plan) return;
        e.preventDefault();
        const wrapper = wrapperRef.current;
        if (!wrapper) return;
        const rect = wrapper.getBoundingClientRect();
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;
        const delta = -e.deltaY;
        const factor = delta > 0 ? 1.15 : 1 / 1.15;
        const newZoom = Math.max(0.5, Math.min(6, zoom * factor));
        // Point sous le curseur en coord non-zoomées avant/après → ajuste le pan
        const kx = (cx - pan.x) / zoom;
        const ky = (cy - pan.y) / zoom;
        setPan({ x: cx - kx * newZoom, y: cy - ky * newZoom });
        setZoom(newZoom);
    };

    // ---- Pan par drag (bouton gauche en mode select, OU 2 doigts en mobile) ----
    const startPan = (e) => {
        // Uniquement en mode Sélectionner + clic gauche
        if (readOnly ? false : tool !== "select") return false;
        if (e.button && e.button !== 0) return false;
        const pt = e.touches ? e.touches[0] : e;
        setPanDrag({ startX: pt.clientX, startY: pt.clientY, panX: pan.x, panY: pan.y });
        return true;
    };
    const movePan = (e) => {
        if (!panDrag) return;
        const pt = e.touches ? e.touches[0] : e;
        setPan({ x: panDrag.panX + (pt.clientX - panDrag.startX),
                 y: panDrag.panY + (pt.clientY - panDrag.startY) });
    };
    const endPan = () => setPanDrag(null);

    // ---- Pinch to zoom (2 doigts sur tablette / mobile) ----
    const onTouchStart = (e) => {
        if (e.touches.length === 2) {
            const t1 = e.touches[0], t2 = e.touches[1];
            const dx = t2.clientX - t1.clientX, dy = t2.clientY - t1.clientY;
            const dist = Math.hypot(dx, dy);
            const wrapper = wrapperRef.current;
            const rect = wrapper?.getBoundingClientRect();
            setPinch({
                dist,
                midX: ((t1.clientX + t2.clientX) / 2) - (rect?.left || 0),
                midY: ((t1.clientY + t2.clientY) / 2) - (rect?.top || 0),
            });
        } else if (e.touches.length === 1) {
            startPan(e);
        }
    };
    const onTouchMove = (e) => {
        if (e.touches.length === 2 && pinch) {
            const t1 = e.touches[0], t2 = e.touches[1];
            const dx = t2.clientX - t1.clientX, dy = t2.clientY - t1.clientY;
            const dist = Math.hypot(dx, dy);
            const factor = dist / (pinch.dist || 1);
            const newZoom = Math.max(0.5, Math.min(6, zoom * factor));
            const kx = (pinch.midX - pan.x) / zoom;
            const ky = (pinch.midY - pan.y) / zoom;
            setPan({ x: pinch.midX - kx * newZoom, y: pinch.midY - ky * newZoom });
            setZoom(newZoom);
            setPinch({ ...pinch, dist });
        } else if (e.touches.length === 1) {
            movePan(e);
        }
    };
    const onTouchEnd = () => { setPinch(null); endPan(); };

    const resetZoom = () => { setZoom(1); setPan({ x: 0, y: 0 }); };

    // Convertit coords écran → 0..1
    const clientToNorm = (evt) => {
        const svg = svgRef.current;
        if (!svg) return { nx: 0, ny: 0 };
        const pt = svg.createSVGPoint();
        pt.x = evt.clientX ?? evt.touches?.[0]?.clientX ?? 0;
        pt.y = evt.clientY ?? evt.touches?.[0]?.clientY ?? 0;
        const ctm = svg.getScreenCTM();
        if (!ctm) return { nx: 0, ny: 0 };
        const svgPt = pt.matrixTransform(ctm.inverse());
        return {
            nx: Math.max(0, Math.min(1, svgPt.x / vbW)),
            ny: Math.max(0, Math.min(1, svgPt.y / vbH)),
        };
    };

    // (iter47) statusFilter retiré (les zones sont par NUIT, plus par allée)
    // Supprime aussi alleeByUid — plus utilisé
    const nightsAvailable = useMemo(() => {
        // Nuits présentes dans les allées + nuits déjà utilisées sur ce plan
        const s = new Set((state?.allees || []).map((a) => a.nuit_eff).filter(Boolean));
        (plan?.zones || []).forEach((z) => { if (z.nuit) s.add(parseInt(z.nuit, 10)); });
        return Array.from(s).sort((a, b) => a - b);
    }, [state, plan]);

    const visibleZones = useMemo(() => {
        if (!plan) return [];
        return (plan.zones || []).filter((z) => {
            if (nightFilter === "all") return true;
            return String(z.nuit) === String(nightFilter);
        });
    }, [plan, nightFilter]);

    // ---- Interactions ----
    const handleSvgMouseDown = (e) => {
        if (readOnly || !plan) return;
        if (tool !== "rect") return;
        const { nx, ny } = clientToNorm(e);
        setRectDraft({ x1: nx, y1: ny, x2: nx, y2: ny });
    };
    const handleSvgMouseMove = (e) => {
        if (!rectDraft) return;
        const { nx, ny } = clientToNorm(e);
        setRectDraft({ ...rectDraft, x2: nx, y2: ny });
    };
    const handleSvgMouseUp = () => {
        if (!rectDraft) return;
        const { x1, y1, x2, y2 } = rectDraft;
        const w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
        if (w > 0.01 && h > 0.01) {
            const zone = {
                id: `z-${Date.now()}`, nuit: drawNuit, kind: "rect",
                coords: [[Math.min(x1, x2), Math.min(y1, y2), w, h]],
            };
            setPlans((ps) => ps.map((p, i) => (i === activeFloor
                ? { ...p, zones: [...(p.zones || []), zone] } : p)));
            setSelectedZoneId(zone.id);
            setDirty(true);
            setTool("select");
        }
        setRectDraft(null);
    };
    const handleSvgClick = (e) => {
        if (readOnly || !plan) return;
        if (tool !== "polygon") {
            if (e.target === svgRef.current) setSelectedZoneId(null);
            return;
        }
        const { nx, ny } = clientToNorm(e);
        setDrawingPoly((prev) => [...prev, [nx, ny]]);
    };
    const finishPolygon = () => {
        if (drawingPoly.length < 3) { toast.error("Un polygone doit avoir au moins 3 points"); return; }
        const zone = { id: `z-${Date.now()}`, nuit: drawNuit, kind: "polygon", coords: drawingPoly };
        setPlans((ps) => ps.map((p, i) => (i === activeFloor
            ? { ...p, zones: [...(p.zones || []), zone] } : p)));
        setDrawingPoly([]);
        setSelectedZoneId(zone.id);
        setDirty(true);
        setTool("select");
    };
    const updateZone = (zid, patch) => {
        setPlans((ps) => ps.map((p, i) => (i === activeFloor
            ? { ...p, zones: (p.zones || []).map((z) => (z.id === zid ? { ...z, ...patch } : z)) }
            : p)));
        setDirty(true);
    };
    const deleteZone = (zid) => {
        setPlans((ps) => ps.map((p, i) => (i === activeFloor
            ? { ...p, zones: (p.zones || []).filter((z) => z.id !== zid) } : p)));
        setSelectedZoneId(null);
        setDirty(true);
    };
    const saveCurrent = async () => {
        if (!plan) return;
        setSaving(true);
        const updated = await actions.updateFloorplan(plan.id, {
            label: plan.label, zones: plan.zones || [], image_data_url: undefined,
        });
        setSaving(false);
        if (updated) {
            setDirty(false);
            toast.success("Plan enregistré");
            setPlans((ps) => ps.map((p, i) => (i === activeFloor ? { ...p, ...updated } : p)));
        }
    };
    const onPickImage = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        setUploadingNew(true);
        try {
            const blob = await compressImage(file, 2000, 0.82);
            const dataUrl = await new Promise((r, j) => {
                const fr = new FileReader();
                fr.onload = () => r(fr.result);
                fr.onerror = () => j(new Error("read error"));
                fr.readAsDataURL(blob);
            });
            const label = (pendingNewLabel || `Étage ${plans.length + 1}`).trim() || `Étage ${plans.length + 1}`;
            const created = await actions.createFloorplan(label, dataUrl, [], phaseKind);
            if (created) {
                setPlans((ps) => [...ps, created]);
                setActiveFloor(plans.length);
                setPendingNewLabel("");
            }
        } catch (err) {
            toast.error("Chargement du plan impossible : " + (err?.message || err));
        } finally { setUploadingNew(false); }
    };
    const deleteCurrentPlan = async () => {
        if (!plan) return;
        if (!window.confirm(`Supprimer le plan « ${plan.label} » ? Les zones associées seront perdues.`)) return;
        const ok = await actions.deleteFloorplan(plan.id);
        if (ok) {
            setPlans(plans.filter((p) => p.id !== plan.id));
            setActiveFloor(Math.max(0, activeFloor - 1));
            setDirty(false);
        }
    };

    const selectedZone = plan?.zones?.find((z) => z.id === selectedZoneId) || null;

    // ─────────────────────────────────────────────────────────────
    if (loading) {
        return (
            <div className="py-16 flex justify-center" data-testid="floorplan-loading">
                <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
            </div>
        );
    }

    const cursor = tool === "rect" || tool === "polygon" ? "crosshair" : "default";

    return (
        <div className="text-slate-200" data-testid="suivi-floorplan">
            <header className="mb-4 flex items-center gap-3 flex-wrap">
                <div>
                    <h2 className="text-lg font-bold flex items-center gap-2">
                        <MapPin className="w-5 h-5 text-blue-400" />
                        Plan du magasin
                        <span className={`text-[10px] uppercase tracking-widest font-bold rounded-full px-2 py-0.5 border ${phaseKind === "cam"
                            ? "bg-purple-950/60 border-purple-700 text-purple-300"
                            : "bg-blue-950/60 border-blue-700 text-blue-300"}`}
                            data-testid="floorplan-phase-badge">
                            {phaseKind === "cam" ? "Caméras" : "EEG / Rails"}
                        </span>
                    </h2>
                    <p className="text-xs text-slate-400 mt-0.5">
                        {readOnly
                            ? "Visualisation en lecture seule — un code couleur par nuit."
                            : `Dessinez des zones et attribuez-leur une nuit : chaque nuit a sa couleur. Ce plan est spécifique au phasage ${phaseKind === "cam" ? "Caméras" : "EEG / Rails"}.`}
                    </p>
                </div>
                {readOnly && (
                    <span className="ml-auto flex items-center gap-1 text-xs bg-slate-800 border border-slate-700 rounded-full px-2 py-0.5 text-slate-300">
                        <Eye className="w-3 h-3" /> Lecture seule
                    </span>
                )}
            </header>

            <div className="flex items-center gap-2 flex-wrap mb-3">
                {plans.map((p, i) => (
                    <button
                        key={p.id}
                        onClick={() => { setActiveFloor(i); setSelectedZoneId(null); setDrawingPoly([]); }}
                        data-testid={`floor-tab-${i}`}
                        className={`px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${activeFloor === i
                            ? "bg-blue-600 border-blue-500 text-white"
                            : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"}`}
                    >
                        {p.label}
                    </button>
                ))}
                {!readOnly && (
                    <div className="flex items-center gap-1.5">
                        <input
                            type="text"
                            placeholder="Nom (RDC, Étage 1…)"
                            value={pendingNewLabel}
                            onChange={(e) => setPendingNewLabel(e.target.value)}
                            data-testid="floorplan-new-label"
                            className="px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded-md text-slate-200 w-32"
                        />
                        <button
                            onClick={() => fileInputRef.current?.click()}
                            disabled={uploadingNew}
                            data-testid="floorplan-new-upload"
                            className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50"
                        >
                            {uploadingNew ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                            Nouveau plan
                        </button>
                        <input
                            ref={fileInputRef} type="file" accept="image/png,image/jpeg" className="hidden"
                            onChange={onPickImage} data-testid="floorplan-file-input"
                        />
                    </div>
                )}
            </div>

            {plans.length === 0 ? (
                <EmptyState readOnly={readOnly} />
            ) : (
                <div className="flex flex-col lg:flex-row gap-3">
                    <div className="flex-1 min-w-0">
                        {!readOnly && (
                            <Toolbar
                                tool={tool} setTool={setTool}
                                drawNuit={drawNuit} setDrawNuit={setDrawNuit}
                                nightsAvailable={nightsAvailable}
                                dirty={dirty} saving={saving} onSave={saveCurrent}
                                drawingPoly={drawingPoly} onFinishPoly={finishPolygon}
                                onCancelPoly={() => setDrawingPoly([])}
                                onDeletePlan={deleteCurrentPlan}
                            />
                        )}
                        <FilterBar
                            nights={nightsAvailable}
                            nightFilter={nightFilter} setNightFilter={setNightFilter}
                        />
                        <div
                            ref={wrapperRef}
                            className="mt-2 bg-slate-900 border border-slate-700 rounded-lg overflow-hidden relative select-none"
                            data-testid="floorplan-canvas"
                            onWheel={onWheel}
                            onMouseDown={(e) => {
                                if (tool === "select" && e.target?.tagName === "svg") startPan(e);
                            }}
                            onMouseMove={movePan}
                            onMouseUp={endPan}
                            onMouseLeave={endPan}
                            onTouchStart={onTouchStart}
                            onTouchMove={onTouchMove}
                            onTouchEnd={onTouchEnd}
                            style={{ touchAction: "none" }}
                        >
                            {plan && (
                                <>
                                    <div
                                        style={{
                                            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                                            transformOrigin: "0 0",
                                            transition: panDrag || pinch ? "none" : "transform 0.1s ease-out",
                                            width: "100%",
                                        }}
                                    >
                                        <svg
                                            ref={svgRef}
                                            viewBox={`0 0 ${vbW} ${vbH}`}
                                            preserveAspectRatio="xMidYMid meet"
                                            onMouseDown={handleSvgMouseDown}
                                            onMouseMove={handleSvgMouseMove}
                                            onMouseUp={handleSvgMouseUp}
                                            onClick={handleSvgClick}
                                            style={{ width: "100%", display: "block", cursor, touchAction: "none" }}
                                        >
                                            <image
                                                href={plan.image_data_url}
                                                x={0} y={0} width={vbW} height={vbH}
                                                style={{ userSelect: "none" }}
                                            />
                                            {visibleZones.map((z) => (
                                                <ZoneShape
                                                    key={z.id} zone={z}
                                                    vbW={vbW} vbH={vbH}
                                                    selected={z.id === selectedZoneId}
                                                    onSelect={(e) => {
                                                        e.stopPropagation?.();
                                                        if (readOnly) {
                                                            // En viewer, un clic ne fait rien (pas d'allée liée)
                                                        } else if (tool === "select") {
                                                            setSelectedZoneId(z.id);
                                                        }
                                                    }}
                                                />
                                            ))}
                                            {rectDraft && (
                                                <rect
                                                    x={Math.min(rectDraft.x1, rectDraft.x2) * vbW}
                                                    y={Math.min(rectDraft.y1, rectDraft.y2) * vbH}
                                                    width={Math.abs(rectDraft.x2 - rectDraft.x1) * vbW}
                                                    height={Math.abs(rectDraft.y2 - rectDraft.y1) * vbH}
                                                    fill="rgba(59,130,246,0.25)" stroke="#3B82F6"
                                                    strokeWidth={vbW * 0.002} strokeDasharray="8 4"
                                                />
                                            )}
                                            {drawingPoly.length > 0 && (
                                                <PolygonDraft points={drawingPoly} vbW={vbW} vbH={vbH} />
                                            )}
                                        </svg>
                                    </div>
                                    <ZoomControls zoom={zoom} onReset={resetZoom}
                                                  onZoomIn={() => setZoom((z) => Math.min(6, z * 1.25))}
                                                  onZoomOut={() => setZoom((z) => Math.max(0.5, z / 1.25))} />
                                </>
                            )}
                        </div>
                        <Legend plan={plan} />
                    </div>

                    {!readOnly && (
                        <aside className="lg:w-56 bg-slate-800/60 border border-slate-700 rounded-lg p-3 h-fit lg:sticky lg:top-4">
                            <h3 className="text-xs font-bold text-slate-300 mb-2">
                                {selectedZone ? "Zone sélectionnée" : `${plan?.zones?.length || 0} zone(s) sur ce plan`}
                            </h3>
                            {selectedZone ? (
                                <ZoneInspector
                                    zone={selectedZone}
                                    nightsAvailable={nightsAvailable}
                                    onChange={(patch) => updateZone(selectedZone.id, patch)}
                                    onDelete={() => deleteZone(selectedZone.id)}
                                />
                            ) : (
                                <p className="text-xs text-slate-500">
                                    Cliquez sur une zone pour l&apos;éditer, ou dessinez-en une nouvelle avec les outils.
                                </p>
                            )}
                        </aside>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── Zone drawn in SVG ───────────────────────────────────────────
function ZoneShape({ zone, vbW, vbH, selected, onSelect }) {
    const nuitLabel = `Nuit ${zone.nuit || 1}`;
    const color = nightColor(zone.nuit);
    const fill = color;
    const opacity = 0.42;
    const stroke = selected ? "#FBBF24" : color;
    const strokeW = (selected ? 3 : 2) * (vbW * 0.001);
    const textStyle = {
        fontSize: Math.max(11, vbW * 0.013),
        fontWeight: 700,
        fill: "#F8FAFC",
        paintOrder: "stroke",
        stroke: "rgba(0,0,0,0.9)",
        strokeWidth: 3,
        pointerEvents: "none",
        userSelect: "none",
    };
    if (zone.kind === "rect") {
        const [nx, ny, nw, nh] = zone.coords[0] || [0, 0, 0.1, 0.1];
        const x = nx * vbW, y = ny * vbH, w = nw * vbW, h = nh * vbH;
        return (
            <g onClick={onSelect} onMouseDown={(e) => e.stopPropagation()} style={{ cursor: "pointer" }}>
                <rect x={x} y={y} width={w} height={h} fill={fill} fillOpacity={opacity}
                      stroke={stroke} strokeWidth={strokeW} rx={4} />
                <text x={x + 6} y={y + Math.max(16, vbW * 0.02)} style={textStyle}>{nuitLabel}</text>
            </g>
        );
    }
    // polygon
    const pts = zone.coords.map(([nx, ny]) => `${nx * vbW},${ny * vbH}`).join(" ");
    const cx = zone.coords.reduce((s, [nx]) => s + nx, 0) / zone.coords.length * vbW;
    const cy = zone.coords.reduce((s, [, ny]) => s + ny, 0) / zone.coords.length * vbH;
    return (
        <g onClick={onSelect} onMouseDown={(e) => e.stopPropagation()} style={{ cursor: "pointer" }}>
            <polygon points={pts} fill={fill} fillOpacity={opacity} stroke={stroke} strokeWidth={strokeW} />
            <text x={cx} y={cy} textAnchor="middle" style={textStyle}>{nuitLabel}</text>
        </g>
    );
}

function PolygonDraft({ points, vbW, vbH }) {
    const strokeW = vbW * 0.002;
    return (
        <>
            <polyline
                points={points.map(([nx, ny]) => `${nx * vbW},${ny * vbH}`).join(" ")}
                fill="none" stroke="#3B82F6" strokeWidth={strokeW} strokeDasharray="8 4"
            />
            {points.map(([nx, ny], i) => (
                <circle key={i} cx={nx * vbW} cy={ny * vbH} r={vbW * 0.005}
                        fill="#3B82F6" stroke="#fff" strokeWidth={strokeW * 0.7} />
            ))}
        </>
    );
}

function Toolbar({ tool, setTool, drawNuit, setDrawNuit, nightsAvailable,
                  dirty, saving, onSave, drawingPoly, onFinishPoly, onCancelPoly, onDeletePlan }) {
    const btn = (id, label, Icon, testid) => (
        <button
            onClick={() => setTool(id)}
            data-testid={testid}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-semibold border transition-colors ${tool === id
                ? "bg-blue-600 border-blue-500 text-white"
                : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"}`}
        >
            <Icon className="w-3.5 h-3.5" />{label}
        </button>
    );
    const drawing = tool === "rect" || tool === "polygon";
    const maxNuit = Math.max(1, ...(nightsAvailable || []));
    const nuitOptions = [];
    for (let n = 1; n <= maxNuit + 1; n++) nuitOptions.push(n);
    return (
        <div className="flex items-center gap-1.5 flex-wrap">
            {btn("select", "Sélectionner", MousePointer2, "floorplan-tool-select")}
            {btn("rect", "Rectangle", Square, "floorplan-tool-rect")}
            {btn("polygon", "Polygone", Pentagon, "floorplan-tool-polygon")}
            {drawing && (
                <label className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800 border border-slate-700 text-xs">
                    <span className="w-3 h-3 rounded-sm border border-slate-500"
                          style={{ background: nightColor(drawNuit) }} />
                    <span className="text-slate-400">Dessine pour :</span>
                    <select
                        value={drawNuit}
                        onChange={(e) => setDrawNuit(parseInt(e.target.value, 10) || 1)}
                        data-testid="floorplan-draw-nuit"
                        className="bg-slate-900 border border-slate-700 rounded px-1 py-0.5 text-slate-200"
                    >
                        {nuitOptions.map((n) => <option key={n} value={n}>Nuit {n}</option>)}
                    </select>
                </label>
            )}
            {drawingPoly.length >= 3 && (
                <button
                    onClick={onFinishPoly} data-testid="floorplan-poly-finish"
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-semibold border bg-emerald-600 border-emerald-500 text-white hover:bg-emerald-500"
                >
                    <PencilRuler className="w-3.5 h-3.5" /> Terminer le polygone
                </button>
            )}
            {drawingPoly.length > 0 && (
                <button
                    onClick={onCancelPoly}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs bg-slate-800 border border-slate-700 text-slate-400 hover:bg-slate-700"
                >
                    <X className="w-3.5 h-3.5" />Annuler
                </button>
            )}
            <div className="ml-auto flex items-center gap-1.5">
                {dirty && <span className="text-xs text-amber-400">● modifications non enregistrées</span>}
                <button
                    onClick={onSave} disabled={!dirty || saving} data-testid="floorplan-save"
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-semibold border bg-blue-600 border-blue-500 text-white hover:bg-blue-500 disabled:opacity-40"
                >
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                    Enregistrer
                </button>
                <button
                    onClick={onDeletePlan} data-testid="floorplan-delete"
                    className="flex items-center gap-1 px-2 py-1.5 rounded-md text-xs bg-red-950 border border-red-800 text-red-300 hover:bg-red-900"
                    title="Supprimer ce plan"
                >
                    <Trash2 className="w-3.5 h-3.5" />
                </button>
            </div>
        </div>
    );
}

function FilterBar({ nights, nightFilter, setNightFilter }) {
    const opt = "px-2 py-1 rounded-md text-xs bg-slate-800 border border-slate-700 text-slate-300";
    return (
        <div className="flex items-center gap-2 flex-wrap text-xs mt-2">
            <span className="text-slate-500">Filtres :</span>
            <select value={nightFilter} onChange={(e) => setNightFilter(e.target.value)}
                    className={opt} data-testid="floorplan-filter-night">
                <option value="all">Toutes les nuits</option>
                {nights.map((n) => <option key={n} value={n}>Nuit {n}</option>)}
            </select>
        </div>
    );
}

function ZoneInspector({ zone, nightsAvailable, onChange, onDelete }) {
    // Palette compacte pour visualiser la couleur de nuit choisie
    const swatch = (
        <span className="inline-block w-4 h-4 rounded-sm border border-slate-500"
              style={{ background: nightColor(zone.nuit) }} />
    );
    // Nuits proposées : celles utilisées côté allées + 1..max — évite les nuits vides
    const maxNuit = Math.max(1, ...(nightsAvailable || []), (zone.nuit || 1));
    const options = [];
    for (let n = 1; n <= maxNuit + 1; n++) options.push(n);
    return (
        <div className="space-y-2 text-xs">
            <label className="block">
                <span className="text-slate-400 flex items-center gap-2">Nuit associée {swatch}</span>
                <select
                    value={zone.nuit || 1}
                    onChange={(e) => onChange({ nuit: parseInt(e.target.value, 10) || 1 })}
                    data-testid="zone-nuit-select"
                    className="mt-1 w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded-md text-slate-200"
                >
                    {options.map((n) => (
                        <option key={n} value={n}>Nuit {n}</option>
                    ))}
                </select>
            </label>
            <div className="flex items-center gap-2 text-slate-500">
                <span>Type : {zone.kind === "rect" ? "Rectangle" : "Polygone"}</span>
                <span>· {zone.kind === "rect" ? "1 rectangle" : `${zone.coords.length} points`}</span>
            </div>
            <button
                onClick={onDelete} data-testid="zone-delete"
                className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs bg-red-950 border border-red-800 text-red-300 hover:bg-red-900"
            >
                <Trash2 className="w-3.5 h-3.5" /> Supprimer cette zone
            </button>
        </div>
    );
}

function Legend({ plan }) {
    // (iter47) Légende dynamique : liste les nuits présentes sur le plan avec leur couleur.
    const nightsOnPlan = useMemo(() => {
        const s = new Set();
        (plan?.zones || []).forEach((z) => { if (z.nuit) s.add(parseInt(z.nuit, 10)); });
        return Array.from(s).sort((a, b) => a - b);
    }, [plan]);
    if (nightsOnPlan.length === 0) return null;
    return (
        <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-400 flex-wrap" data-testid="floorplan-legend">
            <span className="text-slate-500">Nuits sur ce plan :</span>
            {nightsOnPlan.map((n) => (
                <span key={n} className="flex items-center gap-1">
                    <span className="w-3 h-3 rounded-sm" style={{ background: nightColor(n), opacity: 0.7 }} />
                    Nuit {n}
                </span>
            ))}
        </div>
    );
}

function EmptyState({ readOnly }) {
    return (
        <div className="py-24 text-center bg-slate-900/40 border border-dashed border-slate-700 rounded-lg flex flex-col items-center justify-center" style={{ minHeight: "min(60vh, 600px)" }} data-testid="floorplan-empty">
            <MapPin className="w-10 h-10 text-slate-500 mb-3" />
            <p className="text-sm text-slate-400">Aucun plan n&apos;a encore été chargé pour ce magasin.</p>
            {!readOnly && (
                <p className="text-xs text-slate-500 mt-2">
                    Chargez une image PNG ou JPEG (max 4 Mo) avec le bouton « Nouveau plan » ci-dessus.
                </p>
            )}
        </div>
    );
}

// (iter46) Contrôles zoom / reset flottants dans le coin inférieur droit du plan
function ZoomControls({ zoom, onReset, onZoomIn, onZoomOut }) {
    const btn = "w-8 h-8 flex items-center justify-center rounded-md bg-slate-800/90 border border-slate-600 text-slate-200 hover:bg-slate-700 backdrop-blur";
    return (
        <div className="absolute bottom-3 right-3 flex flex-col gap-1.5" data-testid="floorplan-zoom-controls">
            <button onClick={onZoomIn} className={btn} title="Zoom +" data-testid="floorplan-zoom-in">
                <ZoomIn className="w-4 h-4" />
            </button>
            <button onClick={onZoomOut} className={btn} title="Zoom −" data-testid="floorplan-zoom-out">
                <ZoomOut className="w-4 h-4" />
            </button>
            <button onClick={onReset} className={btn} title="Réinitialiser le zoom" data-testid="floorplan-zoom-reset">
                <Maximize2 className="w-4 h-4" />
            </button>
            <span className="text-[10px] text-slate-400 text-center bg-slate-800/70 rounded px-1 py-0.5 border border-slate-700" data-testid="floorplan-zoom-level">
                {Math.round(zoom * 100)}%
            </span>
        </div>
    );
}
