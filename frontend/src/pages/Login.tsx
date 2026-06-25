import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { cn } from "../lib/utils";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api("/api/identity/login/", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      // Redirect to dashboard after successful login
      window.location.href = "/dashboard";
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "Invalid credentials." : err.statusText);
      } else {
        setError("An unexpected error occurred.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-paper">
      <div className="w-full max-w-md bg-white rounded-lg shadow-lg p-8">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-harbour">MbPA Portal</h1>
          <p className="text-slate text-sm mt-1">Mumbai Port Authority — Building Permission</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-harbour mb-1">
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className={cn(
                "w-full rounded border border-paper-dark px-3 py-2 text-sm",
                "focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent",
              )}
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-harbour mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className={cn(
                "w-full rounded border border-paper-dark px-3 py-2 text-sm",
                "focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent",
              )}
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className={cn(
              "w-full rounded bg-harbour text-white font-medium py-2 px-4 text-sm",
              "hover:bg-harbour-light transition-colors",
              "disabled:opacity-60 disabled:cursor-not-allowed",
            )}
          >
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate">
          New applicant?{" "}
          <a href="/signup" className="text-teal hover:underline">
            Register
          </a>
        </p>
      </div>
    </div>
  );
}
