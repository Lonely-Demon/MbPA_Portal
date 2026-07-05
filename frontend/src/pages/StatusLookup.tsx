import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { cn } from "../lib/utils";

interface MilestoneSummary {
  code: string;
  name: string;
  sequence: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  is_deemed: boolean;
}

interface StatusResult {
  application_number: string;
  status: string;
  stream: string;
  submitted_at: string | null;
  milestones: MilestoneSummary[];
}

export default function StatusLookup() {
  const [appNumber, setAppNumber] = useState("");
  const [result, setResult] = useState<StatusResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const data = await api<StatusResult>(
        `/api/applications/status/?application_number=${encodeURIComponent(appNumber)}`,
      );
      setResult(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError("Application not found.");
      } else {
        setError("Unable to fetch status. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-paper">
      <div className="w-full max-w-lg bg-white rounded-lg shadow-lg p-8">
        <h1 className="text-xl font-bold text-harbour mb-1">Application Status</h1>
        <p className="text-slate text-sm mb-6">Track your building permission application.</p>

        <form onSubmit={handleSearch} className="flex gap-2">
          <label htmlFor="app-number" className="sr-only">
            Application number
          </label>
          <input
            id="app-number"
            type="text"
            placeholder="e.g. MBPASPA20260001"
            value={appNumber}
            onChange={(e) => setAppNumber(e.target.value)}
            required
            className={cn(
              "flex-1 rounded border border-paper-dark px-3 py-2 text-sm",
              "focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent",
            )}
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-teal text-white px-4 py-2 text-sm font-medium hover:bg-teal-light transition-colors disabled:opacity-60"
          >
            {loading ? "…" : "Search"}
          </button>
        </form>

        {error && (
          <p role="alert" className="mt-4 text-sm text-red-600 bg-red-50 rounded px-3 py-2">
            {error}
          </p>
        )}

        {result && (
          <>
            <dl className="mt-6 space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-slate">Application</dt>
                <dd className="font-mono font-medium text-harbour">{result.application_number}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate">Stream</dt>
                <dd>{result.stream}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate">Status</dt>
                <dd className="capitalize font-medium text-teal">{result.status.replace(/_/g, " ")}</dd>
              </div>
              {result.submitted_at && (
                <div className="flex justify-between">
                  <dt className="text-slate">Submitted</dt>
                  <dd>{new Date(result.submitted_at).toLocaleDateString("en-IN")}</dd>
                </div>
              )}
            </dl>

            {result.milestones && result.milestones.length > 0 && (
              <div className="mt-5 border-t pt-4">
                <h3 className="text-sm font-medium text-harbour mb-3">Milestones</h3>
                <ol className="space-y-2">
                  {result.milestones.map((m) => (
                    <li key={m.code} className="flex items-start gap-3 text-sm">
                      <span
                        aria-label={
                          m.status === "completed"
                            ? "Completed"
                            : m.status === "in_progress"
                              ? "In progress"
                              : "Pending"
                        }
                        className={cn(
                          "mt-0.5 w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center text-xs",
                          m.status === "completed" && "bg-teal text-white",
                          m.status === "in_progress" && "bg-amber-400 text-white",
                          m.status === "pending" && "bg-paper-dark text-slate",
                        )}
                      >
                        <span aria-hidden="true">
                          {m.status === "completed" ? "✓" : m.sequence}
                        </span>
                      </span>
                      <div className="flex-1">
                        <span
                          className={cn(
                            m.status === "in_progress" && "font-medium text-harbour",
                            m.status === "pending" && "text-slate",
                          )}
                        >
                          {m.name}
                        </span>
                        {m.completed_at && (
                          <span className="block text-xs text-slate">
                            {new Date(m.completed_at).toLocaleDateString("en-IN")}
                          </span>
                        )}
                      </div>
                      {m.is_deemed && (
                        <span className="text-xs bg-teal/10 text-teal rounded px-1.5 py-0.5 flex-shrink-0">
                          Deemed
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
