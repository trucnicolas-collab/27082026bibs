import React from "react";

// Indicateur de chargement animé, cohérent dans toute l'app.
export const LoadingState = ({ message = "Chargement…", testId }) => (
    <div
        className="flex-1 flex flex-col items-center justify-center h-full gap-3 text-gray-500 eeg-fade"
        data-testid={testId}
    >
        <div className="eeg-spinner" aria-hidden="true" />
        <span className="text-sm">{message}</span>
    </div>
);

export default LoadingState;
