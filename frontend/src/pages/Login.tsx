import { useState } from "react";
import { client } from "../api/client";
import { cn } from "../lib/utils";

export default function Login() {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [tokenId, setTokenId] = useState<number | null>(null);
  const [maskedEmail, setMaskedEmail] = useState<string | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { data, error: apiError } = await client.POST("/api/identity/login/", {
        body: { email, username, password },
      });
      if (apiError || !data) {
        setError("Invalid credentials.");
        return;
      }
      setTokenId(data.token_id);
      setMaskedEmail(data.masked_email);
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  async function handleOtp(e: React.FormEvent) {
    e.preventDefault();
    if (tokenId === null) return;
    setError(null);
    setLoading(true);
    try {
      const { error: apiError } = await client.POST("/api/identity/otp/verify/", {
        body: { token_id: tokenId, code: otpCode },
      });
      if (apiError) {
        setError("Invalid or expired code.");
        return;
      }
      window.location.href = "/dashboard";
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  if (tokenId !== null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-paper">
        <div className="w-full max-w-md bg-white rounded-lg shadow-lg p-8">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-harbour">Verify OTP</h1>
            <p className="text-slate text-sm mt-1">
              Code sent to {maskedEmail}
            </p>
          </div>
          <form onSubmit={handleOtp} className="space-y-4">
            <div>
              <label htmlFor="otp" className="block text-sm font-medium text-harbour mb-1">
                One-time code
              </label>
              <input
                id="otp"
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value)}
                required
                autoFocus
                className={cn(
                  "w-full rounded border border-paper-dark px-3 py-2 text-sm tracking-widest",
                  "focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent",
                )}
              />
            </div>
            {error && (
              <p role="alert" className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>
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
              {loading ? "Verifying…" : "Verify"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-paper">
      <div className="w-full max-w-md bg-white rounded-lg shadow-lg p-8">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-harbour">MbPA Portal</h1>
          <p className="text-slate text-sm mt-1">Mumbai Port Authority — Building Permission</p>
        </div>

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-harbour mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className={cn(
                "w-full rounded border border-paper-dark px-3 py-2 text-sm",
                "focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent",
              )}
            />
          </div>

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
            <p role="alert" className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>
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

