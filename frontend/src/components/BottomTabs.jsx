import React from "react";

export default function BottomTabs({ tabs, active, onChange }) {
    return (
        <div
            className="h-10 border-t border-gray-300 bg-gray-100 flex items-center flex-shrink-0 overflow-x-auto px-2"
            data-testid="bottom-tab-bar"
        >
            {tabs.map((t) => {
                const isActive = t.id === active;
                return (
                    <button
                        key={t.id}
                        onClick={() => onChange(t.id)}
                        data-testid={`tab-${t.id}`}
                        className={`h-full px-4 text-sm flex items-center gap-2 transition-colors whitespace-nowrap ${
                            isActive
                                ? "border-t-2 border-[#005BAB] bg-white text-[#005BAB] font-medium -mt-px shadow-sm"
                                : "border-t-2 border-transparent text-gray-600 hover:bg-gray-200"
                        }`}
                    >
                        <span>{t.label}</span>
                        <span
                            className={`text-xs px-1.5 py-0.5 rounded ${
                                isActive ? "bg-blue-100 text-[#005BAB]" : "bg-gray-200 text-gray-600"
                            }`}
                        >
                            {t.count.toLocaleString("fr-FR")}
                        </span>
                    </button>
                );
            })}
        </div>
    );
}
