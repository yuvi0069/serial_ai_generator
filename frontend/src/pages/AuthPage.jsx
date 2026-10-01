import { useState } from "react";
import { useAuth } from "../context/AuthContext.jsx";

export default function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await (mode === "login" ? login : register)(email.trim(), password);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth">
      <section className="auth-copy">
        <h1 className="auth-title">Two hundred episodes.<br />One continuous story.</h1>
        <p>Give it a premise. Approve the arc. Read every episode before it becomes canon, and steer the rest with a sentence.</p>
      </section>
      <form className="auth-form" onSubmit={submit}>
        <h2>{mode === "login" ? "Sign in" : "Create an account"}</h2>
        <label>Email<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Password
          <input type="password" required minLength={mode === "register" ? 8 : 1} maxLength={72}
            autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {mode === "register" && <p className="hint">At least 8 characters.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn primary" disabled={busy}>{busy ? "One moment" : mode === "login" ? "Sign in" : "Create account"}</button>
        <button type="button" className="btn link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </form>
    </main>
  );
}
