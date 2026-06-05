// Jours fériés français — calcul auto pour n'importe quelle année.
// Inclut les fériés fixes + variables (Pâques + dérivés).

/** Dimanche de Pâques (algorithme grégorien anonyme). */
function easterSunday(year) {
    const a = year % 19;
    const b = Math.floor(year / 100);
    const c = year % 100;
    const d = Math.floor(b / 4);
    const e = b % 4;
    const f = Math.floor((b + 8) / 25);
    const g = Math.floor((b - f + 1) / 3);
    const h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4);
    const k = c % 4;
    const l = (32 + 2 * e + 2 * i - h - k) % 7;
    const m = Math.floor((a + 11 * h + 22 * l) / 451);
    const month = Math.floor((h + l - 7 * m + 114) / 31);
    const day = ((h + l - 7 * m + 114) % 31) + 1;
    return new Date(year, month - 1, day);
}

function addDays(date, n) {
    const d = new Date(date);
    d.setDate(d.getDate() + n);
    return d;
}

function isoOf(date) {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
}

/** Retourne tous les jours fériés français pour une année (objet {iso: nom}). */
export function frenchHolidays(year) {
    const easter = easterSunday(year);
    const result = {};
    const add = (date, name) => { result[isoOf(date)] = name; };

    // Fixes
    add(new Date(year, 0, 1), "Jour de l'an");
    add(new Date(year, 4, 1), "Fête du travail");
    add(new Date(year, 4, 8), "Victoire 1945");
    add(new Date(year, 6, 14), "Fête nationale");
    add(new Date(year, 7, 15), "Assomption");
    add(new Date(year, 10, 1), "Toussaint");
    add(new Date(year, 10, 11), "Armistice");
    add(new Date(year, 11, 25), "Noël");

    // Variables (basés sur Pâques)
    add(addDays(easter, 1), "Lundi de Pâques");
    add(addDays(easter, 39), "Ascension");
    add(addDays(easter, 50), "Lundi de Pentecôte");

    return result;
}

/** Retourne le nom du férié si la date est un jour férié FR, sinon null. */
export function holidayName(date) {
    const map = frenchHolidays(date.getFullYear());
    return map[isoOf(date)] || null;
}

/** Pour un Lundi donné, retourne {dayIdx: holidayName} pour les jours Lun/Mar/Mer/Jeu fériés. */
export function weekHolidays(monday) {
    const out = {};
    for (let i = 0; i < 4; i++) {
        const d = addDays(monday, i);
        const name = holidayName(d);
        if (name) out[i] = name;
    }
    return out;
}

/** Application de la règle "on ne travaille pas la nuit qui finit sur férié + celle qui couvre férié".
 *  Retourne la liste des dayIdx (0=Lun..3=Jeu) à TRAVAILLER pour cette semaine.
 *  - Aucun férié sur Lun-Jeu → [0,1,2,3] (4 nuits)
 *  - Férié Lun → [1,2,3]    (3 nuits, on saute la nuit Lun)
 *  - Férié Mar → [2,3]      (2 nuits, on saute nuit Lun + nuit Mar)
 *  - Férié Mer → [0,3]      (2 nuits, on saute nuit Mar + nuit Mer)
 *  - Férié Jeu → [0,1]      (2 nuits, on saute nuit Mer + nuit Jeu)
 *  - Férié Ven → [0,1,2]    (3 nuits, on saute nuit Jeu)
 *  Si plusieurs fériés dans la semaine → on accumule les jours à exclure.
 */
export function workingDaysWithHolidays(monday) {
    const wh = weekHolidays(monday);
    // Vérifie aussi Vendredi (impact possible sur Jeudi soir)
    const friHoliday = holidayName(addDays(monday, 4));
    const excluded = new Set();
    Object.keys(wh).forEach((k) => {
        const i = Number(k);
        // Nuit dont la fin tombe sur le férié → nuit (i-1) jamais < 0 ; on ne travaille pas la nuit du DIMANCHE précédent → ignorée
        if (i - 1 >= 0) excluded.add(i - 1);
        // Nuit qui couvre le férié → nuit i
        excluded.add(i);
    });
    if (friHoliday) {
        // Nuit dont la fin tombe sur Vendredi férié → nuit Jeudi (idx 3)
        excluded.add(3);
    }
    const days = [0, 1, 2, 3].filter((d) => !excluded.has(d));
    return { days, holidays: wh, friHoliday };
}

const dayName = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
export function dayLabel(idx) { return dayName[idx] || ""; }
