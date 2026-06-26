import { useEffect, useState } from "react";
import { client } from "../api/client";
import type { components } from "../api/schema";
import { cn } from "../lib/utils";

type StreamListItem = components["schemas"]["StreamListItem"];
type FeeEstimateResponse = components["schemas"]["FeeEstimateResponse"];

function fmt(v: string | null | undefined) {
  if (!v) return "—";
  return `₹${parseFloat(v).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
}

export default function StreamPlanner() {
  const [streams, setStreams] = useState<StreamListItem[]>([]);
  const [selectedCode, setSelectedCode] = useState("");
  const [bua, setBua] = useState("");
  const [plot, setPlot] = useState("");
  const [rrr, setRrr] = useState("");
  const [openSpace, setOpenSpace] = useState("");
  const [parking, setParking] = useState("");
  const [estimate, setEstimate] = useState<FeeEstimateResponse | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client.GET("/api/applications/streams/").then(({ data }) => {
      if (data) setStreams(data);
    });
  }, []);

  const selectedStream = streams.find((s) => s.code === selectedCode) ?? null;

  async function handleEstimate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setEstimate(null);
    setEstimating(true);
    try {
      const params: Record<string, string> = {
        proposed_bua_sqm: bua,
        plot_area_sqm: plot,
        zonal_rrr: rrr,
      };
      if (openSpace) params.open_space_shortfall_sqm = openSpace;
      if (parking) params.parking_waiver_sqm = parking;

      const { data, error: apiError } = await client.GET("/api/fees/estimate/", {
        params: { query: params as never },
      });
      if (apiError || !data) {
        setError("Unable to calculate estimate. Check your inputs.");
        return;
      }
      setEstimate(data);
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setEstimating(false);
    }
  }

  const inputCls = cn(
    "w-full rounded border border-paper-dark px-3 py-2 text-sm",
    "focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent",
  );

  return (
    <div className="min-h-screen bg-paper">
      <header className="bg-harbour text-white px-6 py-3">
        <h1 className="text-lg font-bold">MbPA Stream Planner</h1>
        <p className="text-xs text-white/70 mt-0.5">
          Plan your application and get a non-binding fee estimate
        </p>
      </header>

      <div className="max-w-2xl mx-auto p-6 space-y-6">
        {/* Stream selector */}
        <div className="bg-white rounded-lg shadow-sm p-6 space-y-4">
          <h2 className="font-semibold text-harbour">1. Select Stream</h2>
          <select
            value={selectedCode}
            onChange={(e) => setSelectedCode(e.target.value)}
            className={inputCls}
          >
            <option value="">— choose a stream —</option>
            {streams.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>

          {selectedStream && (
            <div>
              {selectedStream.description && (
                <p className="text-sm text-slate mb-3">{selectedStream.description}</p>
              )}
              <h3 className="text-sm font-medium text-harbour mb-2">Milestones</h3>
              <ol className="space-y-1">
                {selectedStream.milestones.map((m) => (
                  <li key={m.code} className="flex items-center gap-3 text-sm">
                    <span className="w-6 h-6 rounded-full bg-harbour text-white text-xs flex items-center justify-center flex-shrink-0">
                      {m.sequence}
                    </span>
                    <span className="flex-1">{m.name}</span>
                    <span className="text-xs text-slate">{m.sla_working_days}d</span>
                    {m.deemed_clearance_eligible && (
                      <span className="text-xs bg-teal/10 text-teal rounded px-1.5 py-0.5">
                        Deemed
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>

        {/* Fee estimate form */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="font-semibold text-harbour mb-4">2. Fee Estimate</h2>
          <form onSubmit={handleEstimate} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-harbour mb-1">
                  Proposed BUA (sqm)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={bua}
                  onChange={(e) => setBua(e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-harbour mb-1">
                  Plot area (sqm)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={plot}
                  onChange={(e) => setPlot(e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-harbour mb-1">
                  Zonal RRR (₹/sqm)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={rrr}
                  onChange={(e) => setRrr(e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
            </div>

            <details className="text-sm">
              <summary className="cursor-pointer text-slate hover:text-harbour">
                Concession inputs (optional)
              </summary>
              <div className="grid grid-cols-2 gap-4 mt-3">
                <div>
                  <label className="block text-sm font-medium text-harbour mb-1">
                    Open-space shortfall (sqm)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={openSpace}
                    onChange={(e) => setOpenSpace(e.target.value)}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-harbour mb-1">
                    Parking waiver (sqm)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={parking}
                    onChange={(e) => setParking(e.target.value)}
                    className={inputCls}
                  />
                </div>
              </div>
            </details>

            {error && (
              <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>
            )}

            <button
              type="submit"
              disabled={estimating}
              className="rounded bg-teal text-white font-medium py-2 px-5 text-sm hover:bg-teal-light transition-colors disabled:opacity-60"
            >
              {estimating ? "Calculating…" : "Estimate Fees"}
            </button>
          </form>

          {estimate && (
            <div className="mt-5 border-t pt-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate">Scrutiny fee</span>
                <span>{fmt(estimate.scrutiny_fee)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate">Security deposit</span>
                <span>{fmt(estimate.security_deposit)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate">Debris deposit</span>
                <span>{fmt(estimate.debris_deposit)}</span>
              </div>
              {parseFloat(estimate.premium_total) > 0 && (
                <div className="flex justify-between">
                  <span className="text-slate">Premium total</span>
                  <span>{fmt(estimate.premium_total)}</span>
                </div>
              )}
              <div className="flex justify-between font-semibold border-t pt-2 text-harbour">
                <span>Total estimate</span>
                <span>{fmt(estimate.total_amount)}</span>
              </div>
              <p className="text-xs text-slate bg-amber-50 rounded px-3 py-2">
                Non-binding estimate. Actual fees are determined at the time of formal assessment
                by the reviewing officer and may differ based on updated rates or additional
                concessions.
              </p>
            </div>
          )}
        </div>

        <div className="text-center text-sm text-slate">
          Ready to apply?{" "}
          <a href="/signup" className="text-teal hover:underline">
            Register and submit an application
          </a>
        </div>
      </div>
    </div>
  );
}
