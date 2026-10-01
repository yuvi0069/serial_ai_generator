import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, tokenStore } from "../api.js";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const expired = () => setUser(null);
    window.addEventListener("auth:expired", expired);
    if (!tokenStore.get()) setLoading(false);
    else api.me().then(setUser).catch(() => tokenStore.clear()).finally(() => setLoading(false));
    return () => window.removeEventListener("auth:expired", expired);
  }, []);

  const finish = (res) => { tokenStore.set(res.access_token); setUser(res.user); };
  const login = useCallback(async (e, p) => finish(await api.login(e, p)), []);
  const register = useCallback(async (e, p) => finish(await api.register(e, p)), []);
  const logout = useCallback(() => { tokenStore.clear(); setUser(null); }, []);

  return <AuthCtx.Provider value={{ user, loading, login, register, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
