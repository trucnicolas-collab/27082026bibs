import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { X, Loader2, Store, CalendarDays, Users, CheckCircle2, AlertCircle } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Dialog "Infos magasin" — saisit toutes les méta-infos utilisées dans
 * l'export PowerPoint (slides 1, 4, 6, 9 et 10). Le dialog est obligatoire
 * la première fois (mode = "first-time" => pas de bouton fermer, sortie
 * possible uniquement après save). Sinon (édition), il peut être fermé.
 */
export default function StoreInfoDialog({ open, onClose, dataset, onSaved, firstTime = false }) {
    const [form, setForm] = useState(() => emptyForm(dataset));
    const [saving, setSaving] = useState(false);
    const [touched, setTouched] = useState(false);

    useEffect(() => {
        if (open) {
            setForm(emptyForm(dataset));
            setTouched(false);
        }
    }, [open, dataset]);

    const set = (k) => (e) => {
        const v = e?.target ? e.target.value : e;
        setForm((f) => ({ ...f, [k]: v }));
        setTouched(true);
    };

    // Champs OBLIGATOIRES pour pouvoir générer un PPT correct
    const required = ["store_name", "store_city", "store_code", "vt_start_date"];
    const missing = required.filter((k) => !String(form[k] || "").trim());
    const canSave = missing.length === 0;

    const submit = useCallback(async () => {
        if (!dataset?.upload_id) return;
        if (!canSave) {
            toast.error("Merci de remplir tous les champs obligatoires (*).");
            return;
        }
        setSaving(true);
        try {
            const payload = { ...form };
            // Si vt_end_date vide, le serveur prendra vt_start + 2 jours côté PPT
            const res = await axios.patch(
                `${API}/dataset/${dataset.upload_id}/store-info`,
                payload
            );
            toast.success("Informations magasin enregistrées");
            onSaved?.(res.data);
            onClose?.();
        } catch (err) {
            toast.error(`Erreur : ${err.response?.data?.detail || err.message}`);
        } finally {
            setSaving(false);
        }
    }, [form, dataset, canSave, onSaved, onClose]);

    if (!open) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" data-testid="store-info-overlay">
            <div className="bg-white rounded-lg shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col" data-testid="store-info-dialog">
                {/* Header */}
                <div className="px-5 py-3 border-b border-gray-200 flex items-center justify-between bg-[#056839] text-white rounded-t-lg">
                    <div className="flex items-center gap-2">
                        <Store className="w-5 h-5" />
                        <h2 className="text-base font-semibold" data-testid="store-info-title">
                            {firstTime ? "Informations magasin (étape obligatoire)" : "Informations magasin"}
                        </h2>
                    </div>
                    {!firstTime && (
                        <button
                            onClick={onClose}
                            data-testid="store-info-close"
                            className="p-1 hover:bg-white/20 rounded"
                            aria-label="Fermer"
                        >
                            <X className="w-5 h-5" />
                        </button>
                    )}
                </div>

                {/* Banner first-time */}
                {firstTime && (
                    <div className="px-5 py-2 bg-amber-50 border-b border-amber-200 flex items-start gap-2 text-xs text-amber-900">
                        <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                        <span>
                            Ces informations seront utilisées dans l'export PowerPoint (titre, dates,
                            tableau d'identification du magasin). Tu peux les modifier à tout moment
                            depuis le bouton « Infos magasin ».
                        </span>
                    </div>
                )}

                {/* Body */}
                <div className="px-5 py-4 overflow-y-auto flex-1 space-y-5">
                    {/* Section identité */}
                    <Section icon={<Store className="w-4 h-4" />} title="Identité du magasin">
                        <Field label="Nom du magasin" required value={form.store_name} onChange={set("store_name")} testid="store-name" placeholder="ex: Carrefour Massy" />
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <Field label="Ville" required value={form.store_city} onChange={set("store_city")} testid="store-city" placeholder="ex: Massy" />
                            <Field label="Code magasin" required value={form.store_code} onChange={set("store_code")} testid="store-code" placeholder="ex: HA4CG" />
                        </div>
                        <Field label="Adresse" value={form.store_address} onChange={set("store_address")} testid="store-address" placeholder="Adresse complète" />
                    </Section>

                    {/* Section VT */}
                    <Section icon={<CalendarDays className="w-4 h-4" />} title="Visite Technique (VT)">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <Field type="date" label="Date de début de VT" required value={form.vt_start_date} onChange={set("vt_start_date")} testid="vt-start" />
                            <Field type="date" label="Date de fin de VT" value={form.vt_end_date} onChange={set("vt_end_date")} testid="vt-end"
                                hint="Optionnel — si vide, j+2 par défaut" />
                        </div>
                    </Section>

                    {/* Section contacts & process */}
                    <Section icon={<Users className="w-4 h-4" />} title="Contacts & validation (optionnel)">
                        <Field label="Participants" value={form.participants} onChange={set("participants")} testid="participants" placeholder="Resp magasin + Resp Vusion + …" />
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <Field label="Responsable magasin présent" value={form.responsable_magasin} onChange={set("responsable_magasin")} testid="resp-magasin" />
                            <Field label="Responsable Vusion / Téléphone" value={form.responsable_vusion} onChange={set("responsable_vusion")} testid="resp-vusion" />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <Field label="Prestataire d'installation" value={form.prestataire_install} onChange={set("prestataire_install")} testid="prestataire" />
                            <Field label="Plan de prévention signé" value={form.plan_prevention_signe} onChange={set("plan_prevention_signe")} testid="plan-prevention" placeholder="Oui / Non" />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <Field label="Version du document" value={form.doc_version} onChange={set("doc_version")} testid="doc-version" placeholder="V1.0" />
                            <Field type="date" label="Date validation Carrefour" value={form.date_validation_carrefour} onChange={set("date_validation_carrefour")} testid="date-validation" />
                        </div>
                    </Section>
                </div>

                {/* Footer */}
                <div className="px-5 py-3 border-t border-gray-200 flex items-center justify-between gap-3 bg-gray-50 rounded-b-lg">
                    <div className="text-[11px] text-gray-500">
                        {missing.length > 0
                            ? <span className="text-red-600">Manquant : {missing.map(prettify).join(", ")}</span>
                            : <span className="text-emerald-700 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> Prêt à enregistrer</span>}
                    </div>
                    <div className="flex items-center gap-2">
                        {!firstTime && (
                            <button
                                onClick={onClose}
                                data-testid="store-info-cancel"
                                disabled={saving}
                                className="h-8 px-3 text-sm border border-gray-300 rounded hover:bg-gray-100 text-gray-700"
                            >
                                Annuler
                            </button>
                        )}
                        <button
                            onClick={submit}
                            data-testid="store-info-save"
                            disabled={!canSave || saving || (firstTime && !touched && false)}
                            className="h-8 px-4 text-sm bg-[#056839] text-white rounded hover:bg-[#04502b] disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                        >
                            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                            {firstTime ? "Continuer" : "Enregistrer"}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

function Section({ icon, title, children }) {
    return (
        <fieldset className="border border-gray-200 rounded-md p-3">
            <legend className="px-2 text-xs font-semibold text-gray-700 flex items-center gap-1.5">
                {icon} {title}
            </legend>
            <div className="space-y-3">
                {children}
            </div>
        </fieldset>
    );
}

function Field({ label, required, value, onChange, type = "text", placeholder, hint, testid }) {
    return (
        <label className="block">
            <span className="text-[11px] text-gray-700 font-medium">
                {label}{required && <span className="text-red-600"> *</span>}
            </span>
            <input
                type={type}
                value={value || ""}
                onChange={onChange}
                placeholder={placeholder}
                data-testid={`store-info-field-${testid}`}
                className="mt-0.5 w-full h-8 px-2 border border-gray-300 rounded text-sm focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
            />
            {hint && <span className="text-[10px] text-gray-400 mt-0.5 block">{hint}</span>}
        </label>
    );
}

function prettify(k) {
    return {
        store_name: "Nom",
        store_city: "Ville",
        store_code: "Code",
        vt_start_date: "Date début VT",
    }[k] || k;
}

function emptyForm(d) {
    return {
        store_name: d?.store_name || "",
        store_city: d?.store_city || "",
        store_code: d?.store_code || "",
        store_address: d?.store_address || "",
        vt_start_date: d?.vt_start_date || "",
        vt_end_date: d?.vt_end_date || "",
        participants: d?.participants || "",
        responsable_magasin: d?.responsable_magasin || "",
        responsable_vusion: d?.responsable_vusion || "",
        prestataire_install: d?.prestataire_install || "",
        plan_prevention_signe: d?.plan_prevention_signe || "",
        doc_version: d?.doc_version || "",
        date_validation_carrefour: d?.date_validation_carrefour || "",
    };
}
