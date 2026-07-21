// (iter45) Plan magasin interactif — dessin de zones (SVG, sans dépendance externe)
// et visualisation temps réel du statut de chaque allée (vert = validée, orange = à
// finaliser, rouge = bloquée, bleu = en cours, gris = à faire). Supporte plusieurs
// étages, rectangles + polygones, upload image PNG/JPEG, et mode lecture seule.
import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import {
    Plus, Square, Pentagon, MousePointer2, Trash2, Save, X,
    MapPin, Eye, Loader2, PencilRuler,
} from "lucide-react";
import { toast } from "sonner";
import { compressImage } from "./api";

const STATUS_COLORS = {
    validee: "#10B981",     // green
    a_finaliser: "#F59E0B", // orange
    bloquee: "#EF4444",     // red
    non_faite: "#7C3AED",   // violet
    a_faire: "#64748B",     // slate
};
const zoneFillFor = (status, hasReel) => {
    if (status === "a_faire" && hasReel) return "#3B82F6"; // blue = en cours
    return STATUS_COLORS[status] || STATUS_COLORS.a_faire;
};

export default function SuiviFloorplan({ state, actions, readOnly = false, onOpenAllee }) {
    const [plans, setPlans] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeFloor, setActiveFloor] = useState(0);
    const [tool, setTool] = useState("select");
    const [selectedZoneId, setSelectedZoneId] = useState(null);
    const [drawingPoly, setDrawingPoly] = useState([]);
    const [rectDraft, setRectDraft] = useState(null);
    const [nightFilter, setNightFilter] = useState("all");
    const [statusFilter, setStatusFilter] = useState("all");
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const [uploadingNew, setUploadingNew] = useState(false);
    const [pendingNewLabel, setPendingNewLabel] = useState("");
    const [imgSize, setImgSize] = useState({ w: 1000, h: 700 });
    const svgRef = useRef(null);
    const fileInputRef = useRef(null);

    const reload = useCallback(async () => {
        setLoading(true);
        const list = await actions.listFloorplans();
        setPlans(list);
        setLoading(false);
    }, [actions]);
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

    const alleeByUid = useMemo(() => {
        const m = {};
        (state?.allees || []).forEach((a) => { m[a.uid] = a; });
        return m;
    }, [state]);
    const nightsAvailable = useMemo(() => {
        const s = new Set((state?.allees || []).map((a) => a.nuit_eff).filter(Boolean));
        return Array.from(s).sort((a, b) => a - b);
    }, [state]);

    const visibleZones = useMemo(() => {
        if (!plan) return [];
        return (plan.zones || []).filter((z) => {
            const a = alleeByUid[z.allee_uid];
            if (!a) return true;
            if (nightFilter !== "all" && String(a.nuit_eff) !== String(nightFilter)) return false;
            if (statusFilter !== "all" && a.status !== statusFilter) return false;
            return true;
        });
    }, [plan, alleeByUid, nightFilter, statusFilter]);

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
                id: `z-${Date.now()}`, allee_uid: "", kind: "rect",
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
        const zone = { id: `z-${Date.now()}`, allee_uid: "", kind: "polygon", coords: drawingPoly };
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
            const created = await actions.createFloorplan(label, dataUrl, []);
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
                    </h2>
                    <p className="text-xs text-slate-400 mt-0.5">
                        {readOnly
                            ? "Visualisation en lecture seule — les couleurs se mettent à jour en temps réel."
                            : "Dessinez des zones (rectangles ou polygones), reliez-les aux allées : les couleurs suivent le statut du terrain."}
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
                <div className="flex flex-col lg:flex-row gap-4">
                    <div className="flex-1 min-w-0">
                        {!readOnly && (
                            <Toolbar
                                tool={tool} setTool={setTool}
                                dirty={dirty} saving={saving} onSave={saveCurrent}
                                drawingPoly={drawingPoly} onFinishPoly={finishPolygon}
                                onCancelPoly={() => setDrawingPoly([])}
                                onDeletePlan={deleteCurrentPlan}
                            />
                        )}
                        <FilterBar
                            nights={nightsAvailable}
                            nightFilter={nightFilter} setNightFilter={setNightFilter}
                            statusFilter={statusFilter} setStatusFilter={setStatusFilter}
                        />
                        <div
                            className="mt-2 bg-slate-900 border border-slate-700 rounded-lg overflow-hidden"
                            data-testid="floorplan-canvas"
                        >
                            {plan && (
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
                                            allee={alleeByUid[z.allee_uid]}
                                            vbW={vbW} vbH={vbH}
                                            selected={z.id === selectedZoneId}
                                            onSelect={(e) => {
                                                e.stopPropagation?.();
                                                if (readOnly) {
                                                    if (onOpenAllee && z.allee_uid) onOpenAllee(z.allee_uid);
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
                            )}
                        </div>
                        <Legend />
                    </div>

                    {!readOnly && (
                        <aside className="lg:w-72 bg-slate-800/60 border border-slate-700 rounded-lg p-3">
                            <h3 className="text-xs font-bold text-slate-300 mb-2">
                                {selectedZone ? "Zone sélectionnée" : `${plan?.zones?.length || 0} zone(s) sur ce plan`}
                            </h3>
                            {selectedZone ? (
                                <ZoneInspector
                                    zone={selectedZone}
                                    allees={state?.allees || []}
                                    onChange={(patch) => updateZone(selectedZone.id, patch)}
                                    onDelete={() => deleteZone(selectedZone.id)}
                                />
                            ) : (
                                <p className="text-xs text-slate-500">
                                    Cliquez sur une zone pour l'éditer, ou dessinez-en une nouvelle avec les outils.
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
function ZoneShape({ zone, allee, vbW, vbH, selected, onSelect }) {
    const status = allee?.status || "a_faire";
    const hasReel = !!allee?.has_reel;
    const fill = zoneFillFor(status, hasReel);
    const opacity = allee ? 0.5 : 0.25;
    const stroke = selected ? "#FBBF24" : (allee ? fill : "#94A3B8");
    const strokeW = (selected ? 3 : 2) * (vbW * 0.001);
    const label = allee ? `${allee.secteur ? allee.secteur + " · " : ""}${allee.allee}` : "⚠ Non lié";
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
                <text x={x + 6} y={y + Math.max(16, vbW * 0.02)} style={textStyle}>{label}</text>
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
            <text x={cx} y={cy} textAnchor="middle" style={textStyle}>{label}</text>
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

function Toolbar({ tool, setTool, dirty, saving, onSave, drawingPoly, onFinishPoly, onCancelPoly, onDeletePlan }) {
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
    return (
        <div className="flex items-center gap-1.5 flex-wrap">
            {btn("select", "Sélectionner", MousePointer2, "floorplan-tool-select")}
            {btn("rect", "Rectangle", Square, "floorplan-tool-rect")}
            {btn("polygon", "Polygone", Pentagon, "floorplan-tool-polygon")}
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

function FilterBar({ nights, nightFilter, setNightFilter, statusFilter, setStatusFilter }) {
    const opt = "px-2 py-1 rounded-md text-xs bg-slate-800 border border-slate-700 text-slate-300";
    return (
        <div className="flex items-center gap-2 flex-wrap text-xs mt-2">
            <span className="text-slate-500">Filtres :</span>
            <select value={nightFilter} onChange={(e) => setNightFilter(e.target.value)}
                    className={opt} data-testid="floorplan-filter-night">
                <option value="all">Toutes les nuits</option>
                {nights.map((n) => <option key={n} value={n}>Nuit {n}</option>)}
            </select>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                    className={opt} data-testid="floorplan-filter-status">
                <option value="all">Tous statuts</option>
                <option value="a_faire">À faire</option>
                <option value="validee">Validées</option>
                <option value="a_finaliser">À finaliser</option>
                <option value="bloquee">Bloquées</option>
                <option value="non_faite">Non faite</option>
            </select>
        </div>
    );
}

function ZoneInspector({ zone, allees, onChange, onDelete }) {
    const opts = useMemo(() => {
        const grouped = {};
        (allees || []).forEach((a) => {
            const g = a.secteur || "—";
            (grouped[g] = grouped[g] || []).push(a);
        });
        return grouped;
    }, [allees]);
    return (
        <div className="space-y-2 text-xs">
            <label className="block">
                <span className="text-slate-400">Allée liée</span>
                <select
                    value={zone.allee_uid || ""}
                    onChange={(e) => onChange({ allee_uid: e.target.value })}
                    data-testid="zone-allee-select"
                    className="mt-1 w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded-md text-slate-200"
                >
                    <option value="">— Sélectionner —</option>
                    {Object.keys(opts).sort().map((sec) => (
                        <optgroup key={sec} label={sec}>
                            {opts[sec].sort((a, b) => String(a.allee).localeCompare(String(b.allee)))
                                .map((a) => (
                                    <option key={a.uid} value={a.uid}>
                                        {a.allee} — {a.rayon || "?"} (Nuit {a.nuit_eff})
                                    </option>
                                ))}
                        </optgroup>
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

function Legend() {
    const items = [
        { c: STATUS_COLORS.validee, l: "Validée" },
        { c: "#3B82F6", l: "En cours" },
        { c: STATUS_COLORS.a_finaliser, l: "À finaliser" },
        { c: STATUS_COLORS.bloquee, l: "Bloquée" },
        { c: STATUS_COLORS.non_faite, l: "Non faite" },
        { c: STATUS_COLORS.a_faire, l: "À faire" },
    ];
    return (
        <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-400 flex-wrap">
            {items.map((it) => (
                <span key={it.l} className="flex items-center gap-1">
                    <span className="w-3 h-3 rounded-sm" style={{ background: it.c, opacity: 0.6 }} />
                    {it.l}
                </span>
            ))}
        </div>
    );
}

function EmptyState({ readOnly }) {
    return (
        <div className="py-16 text-center bg-slate-900/40 border border-dashed border-slate-700 rounded-lg" data-testid="floorplan-empty">
            <MapPin className="w-8 h-8 mx-auto text-slate-500 mb-2" />
            <p className="text-sm text-slate-400">Aucun plan n'a encore été chargé pour ce magasin.</p>
            {!readOnly && (
                <p className="text-xs text-slate-500 mt-2">
                    Chargez une image PNG ou JPEG (max 4 Mo) avec le bouton « Nouveau plan » ci-dessus.
                </p>
            )}
        </div>
    );
}
