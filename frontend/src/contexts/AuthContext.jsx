import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Axios global : envoie systématiquement les cookies (httpOnly access/refresh tokens)
axios.defaults.withCredentials = true;

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    // user state: null = checking, false = not authenticated, object = authenticated
    const [user, setUser] = useState(null);

    const fetchMe = useCallback(async () => {
        try {
            const res = await axios.get(`${API}/auth/me`);
            setUser(res.data);
            return res.data;
        } catch (_err) {
            setUser(false);
            return null;
        }
    }, []);

    useEffect(() => {
        fetchMe();
    }, [fetchMe]);

    const login = useCallback(async (email, password) => {
        const res = await axios.post(`${API}/auth/login`, { email, password });
        setUser(res.data);
        return res.data;
    }, []);

    const register = useCallback(async (email, password, name) => {
        const res = await axios.post(`${API}/auth/register`, { email, password, name });
        setUser(res.data);
        return res.data;
    }, []);

    const logout = useCallback(async () => {
        try {
            await axios.post(`${API}/auth/logout`);
        } catch (_) {}
        setUser(false);
        try { localStorage.removeItem("eeg.lastUploadId"); } catch (_) {}
    }, []);

    return (
        <AuthContext.Provider value={{ user, login, register, logout, refresh: fetchMe }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error("useAuth must be used within AuthProvider");
    return ctx;
}
