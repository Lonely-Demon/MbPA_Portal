import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { client } from "../api/client";
import type { components } from "../api/schema";
import { cn } from "../lib/utils";

type StreamListItem = components["schemas"]["StreamListItem"];

interface WizardData {
  email: string;
  username: string;
  password: string;
  full_name: string;
  aadhaar: string;
  stream_id: string;
  plpn: string;
  plot_area_sqm: string;
  proposed_bua_sqm: string;
  existing_bua_sqm: string;
  zonal_rrr: string;
}

const STEP_LABELS = ["Account", "Verify OTP", "Application", "Review"];

const inputCls = cn(
  "w-full rounded border border-paper-dark px-3 py-2 text-sm",
  "focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent",
);

export default function Signup() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [data, setData] = useState<WizardData>({
    email: "",
    username: "",
    password: "",
    full_name: "",
    aadhaar: "",
    stream_id: "",
    plpn: "",
    plot_area_sqm: "",
    proposed_bua_sqm: "",
    existing_bua_sqm: "",
    zonal_rrr: "",
  });
  const [tokenRef, setTokenRef] = useState<string | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [draftId, setDraftId] = useState<number | null>(null);
  const [streams, setStreams] = useState<StreamListItem[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendMsg, setResendMsg] = useState<string | null>(null);

  useEffect(() => {
    if (step === 3 && streams.length === 0) {
      client.GET("/api/applications/streams/").then(({ data: d }) => {
        if (d) setStreams(d);
      });
    }
  }, [step, streams.length]);

  function set(field: keyof WizardData, value: string) {
    setData((prev) => ({ ...prev, [field]: value }));
  }

  async function handleAccount(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { data: resp, error: apiError } = await client.POST("/api/identity/signup/", {
        body: {
          email: data.email,
          username: data.username,
          password: data.password,
          full_name: data.full_name,
          aadhaar: data.aadhaar,
        },
      });
      if (apiError || !resp) {
        const detail =
          typeof apiError === "object" && apiError !== null && "detail" in apiError
            ? String((apiError as Record<string, unknown>)["detail"])
            : "Registration failed. Check your details and try again.";
        setError(detail);
        return;
      }
      setTokenRef(resp.token_ref);
      setStep(2);
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleOtp(e: React.FormEvent) {
    e.preventDefault();
    if (!tokenRef) return;
    setError(null);
    setSubmitting(true);
    try {
      const { error: apiError } = await client.POST("/api/identity/otp/verify/", {
        body: { token_ref: tokenRef, code: otpCode },
      });
      if (apiError) {
        setError("Invalid or expired OTP. Please try again.");
        return;
      }
      setStep(3);
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    if (!tokenRef) return;
    setResendMsg(null);
    const { data: resp } = await client.POST("/api/identity/otp/resend/", {
      body: { token_ref: tokenRef },
    });
    if (resp) {
      setTokenRef(resp.token_ref);
      setResendMsg("A new OTP has been sent to your email.");
    }
  }

  async function handleApplication(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { data: resp, error: apiError } = await client.POST("/api/applications/", {
        body: {
          stream_id: parseInt(data.stream_id, 10),
          plpn: data.plpn,
          plot_area_sqm: data.plot_area_sqm,
          proposed_bua_sqm: data.proposed_bua_sqm,
          existing_bua_sqm: data.existing_bua_sqm,
          zonal_rrr: data.zonal_rrr,
        },
      });
      if (apiError || !resp) {
        setError("Could not create application draft. Check your inputs.");
        return;
      }
      setDraftId(resp.id);
      setStep(4);
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!draftId) return;
    setError(null);
    setSubmitting(true);
    try {
      const { error: apiError } = await client.POST("/api/applications/{id}/submit/", {
        params: { path: { id: draftId } },
      });
      if (apiError) {
        setError("Submission failed. Please try again.");
        return;
      }
      navigate("/dashboard");
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setSubmitting(false);
    }
  }

  const selectedStream = streams.find((s) => String(s.id) === data.stream_id) ?? null;

  return (
    <main className="min-h-screen bg-paper py-8 px-4">
      <div className="max-w-lg mx-auto">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-harbour">Create Account</h1>
          <p className="text-slate text-sm mt-1">MbPA Building Permission Portal</p>
        </div>

        {/* Progress chips */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {STEP_LABELS.map((label, i) => {
            const n = i + 1;
            const done = step > n;
            const active = step === n;
            return (
              <div key={n} className="flex items-center gap-2">
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      "w-8 h-8 rounded-full text-xs font-bold flex items-center justify-center",
                      done && "bg-teal text-white",
                      active && "bg-harbour text-white",
                      !done && !active && "bg-paper-dark text-slate",
                    )}
                  >
                    {done ? "✓" : n}
                  </div>
                  <span
                    className={cn(
                      "text-xs mt-1 hidden sm:block",
                      active ? "text-harbour font-medium" : "text-slate",
                    )}
                  >
                    {label}
                  </span>
                </div>
                {n < STEP_LABELS.length && (
                  <div
                    className={cn(
                      "w-8 h-px mb-4",
                      done ? "bg-teal" : "bg-paper-dark",
                    )}
                  />
                )}
              </div>
            );
          })}
        </div>

        <div className="bg-white rounded-lg shadow-sm p-6">
          {error && (
            <p role="alert" className="text-sm text-red-600 bg-red-50 rounded px-3 py-2 mb-4">
              {error}
            </p>
          )}

          {/* Step 1: Account */}
          {step === 1 && (
            <form onSubmit={handleAccount} className="space-y-4">
              <h2 className="font-semibold text-harbour mb-2">Account Details</h2>
              <div>
                <label htmlFor="full-name" className="block text-sm font-medium text-harbour mb-1">
                  Full name
                </label>
                <input
                  id="full-name"
                  type="text"
                  value={data.full_name}
                  onChange={(e) => set("full_name", e.target.value)}
                  required
                  className={inputCls}
                  placeholder="As per Aadhaar"
                />
              </div>
              <div>
                <label htmlFor="signup-email" className="block text-sm font-medium text-harbour mb-1">
                  Email
                </label>
                <input
                  id="signup-email"
                  type="email"
                  value={data.email}
                  onChange={(e) => set("email", e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="signup-username" className="block text-sm font-medium text-harbour mb-1">
                  Username
                </label>
                <input
                  id="signup-username"
                  type="text"
                  value={data.username}
                  onChange={(e) => set("username", e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="signup-password" className="block text-sm font-medium text-harbour mb-1">
                  Password
                </label>
                <input
                  id="signup-password"
                  type="password"
                  value={data.password}
                  onChange={(e) => set("password", e.target.value)}
                  required
                  minLength={8}
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="signup-aadhaar" className="block text-sm font-medium text-harbour mb-1">
                  Aadhaar number
                </label>
                <input
                  id="signup-aadhaar"
                  type="text"
                  value={data.aadhaar}
                  onChange={(e) => set("aadhaar", e.target.value)}
                  required
                  pattern="\d{12}"
                  maxLength={12}
                  className={inputCls}
                  placeholder="12-digit Aadhaar"
                />
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded bg-teal text-white font-medium py-2 text-sm hover:bg-teal-light transition-colors disabled:opacity-60"
              >
                {submitting ? "Registering…" : "Continue"}
              </button>
            </form>
          )}

          {/* Step 2: OTP */}
          {step === 2 && (
            <form onSubmit={handleOtp} className="space-y-4">
              <h2 className="font-semibold text-harbour mb-2">Verify Email</h2>
              <p className="text-sm text-slate">
                A 6-digit OTP has been sent to <strong>{data.email}</strong>.
              </p>
              <div>
                <label htmlFor="signup-otp" className="block text-sm font-medium text-harbour mb-1">
                  OTP
                </label>
                <input
                  id="signup-otp"
                  type="password"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  required
                  pattern="\d{6}"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  className={inputCls}
                  placeholder="000000"
                />
              </div>
              {resendMsg && (
                <p className="text-sm text-teal">{resendMsg}</p>
              )}
              <div className="flex items-center justify-between gap-3">
                <button
                  type="button"
                  onClick={handleResend}
                  className="text-sm text-teal-link underline"
                >
                  Resend OTP
                </button>
                <button
                  type="submit"
                  disabled={submitting || otpCode.length !== 6}
                  className="rounded bg-teal text-white font-medium py-2 px-5 text-sm hover:bg-teal-light transition-colors disabled:opacity-60"
                >
                  {submitting ? "Verifying…" : "Verify"}
                </button>
              </div>
            </form>
          )}

          {/* Step 3: Application */}
          {step === 3 && (
            <form onSubmit={handleApplication} className="space-y-4">
              <h2 className="font-semibold text-harbour mb-2">Application Details</h2>
              <div>
                <label htmlFor="signup-stream" className="block text-sm font-medium text-harbour mb-1">
                  Stream
                </label>
                <select
                  id="signup-stream"
                  value={data.stream_id}
                  onChange={(e) => set("stream_id", e.target.value)}
                  required
                  className={inputCls}
                >
                  <option value="">— choose a stream —</option>
                  {streams.map((s) => (
                    <option key={s.code} value={String(s.id)}>
                      {s.name}
                    </option>
                  ))}
                </select>
                {selectedStream?.description && (
                  <p className="text-xs text-slate mt-1">{selectedStream.description}</p>
                )}
              </div>
              <div>
                <label htmlFor="signup-plpn" className="block text-sm font-medium text-harbour mb-1">
                  PLPN (optional)
                </label>
                <input
                  id="signup-plpn"
                  type="text"
                  value={data.plpn}
                  onChange={(e) => set("plpn", e.target.value)}
                  className={inputCls}
                  placeholder="Plot/Land Plan Number"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="signup-plot" className="block text-sm font-medium text-harbour mb-1">
                    Plot area (sqm)
                  </label>
                  <input
                    id="signup-plot"
                    type="number"
                    step="0.01"
                    min="0"
                    value={data.plot_area_sqm}
                    onChange={(e) => set("plot_area_sqm", e.target.value)}
                    required
                    className={inputCls}
                  />
                </div>
                <div>
                  <label htmlFor="signup-bua" className="block text-sm font-medium text-harbour mb-1">
                    Proposed BUA (sqm)
                  </label>
                  <input
                    id="signup-bua"
                    type="number"
                    step="0.01"
                    min="0"
                    value={data.proposed_bua_sqm}
                    onChange={(e) => set("proposed_bua_sqm", e.target.value)}
                    required
                    className={inputCls}
                  />
                </div>
                <div>
                  <label htmlFor="signup-existing-bua" className="block text-sm font-medium text-harbour mb-1">
                    Existing BUA (sqm)
                  </label>
                  <input
                    id="signup-existing-bua"
                    type="number"
                    step="0.01"
                    min="0"
                    value={data.existing_bua_sqm}
                    onChange={(e) => set("existing_bua_sqm", e.target.value)}
                    required
                    className={inputCls}
                  />
                </div>
                <div>
                  <label htmlFor="signup-rrr" className="block text-sm font-medium text-harbour mb-1">
                    Zonal RRR (₹/sqm)
                  </label>
                  <input
                    id="signup-rrr"
                    type="number"
                    step="0.01"
                    min="0"
                    value={data.zonal_rrr}
                    onChange={(e) => set("zonal_rrr", e.target.value)}
                    required
                    className={inputCls}
                  />
                </div>
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded bg-teal text-white font-medium py-2 text-sm hover:bg-teal-light transition-colors disabled:opacity-60"
              >
                {submitting ? "Saving…" : "Continue"}
              </button>
            </form>
          )}

          {/* Step 4: Review + Submit */}
          {step === 4 && (
            <form onSubmit={handleSubmit} className="space-y-4">
              <h2 className="font-semibold text-harbour mb-2">Review & Submit</h2>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-slate">Name</dt>
                  <dd className="font-medium">{data.full_name}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate">Email</dt>
                  <dd className="font-medium">{data.email}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate">Username</dt>
                  <dd className="font-medium">{data.username}</dd>
                </div>
                <div className="border-t pt-2 mt-2">
                  <div className="flex justify-between">
                    <dt className="text-slate">Stream</dt>
                    <dd className="font-medium">
                      {streams.find((s) => String(s.id) === data.stream_id)?.name ?? data.stream_id}
                    </dd>
                  </div>
                  {data.plpn && (
                    <div className="flex justify-between mt-1">
                      <dt className="text-slate">PLPN</dt>
                      <dd className="font-medium">{data.plpn}</dd>
                    </div>
                  )}
                  <div className="flex justify-between mt-1">
                    <dt className="text-slate">Plot area</dt>
                    <dd className="font-medium">{data.plot_area_sqm} sqm</dd>
                  </div>
                  <div className="flex justify-between mt-1">
                    <dt className="text-slate">Proposed BUA</dt>
                    <dd className="font-medium">{data.proposed_bua_sqm} sqm</dd>
                  </div>
                  <div className="flex justify-between mt-1">
                    <dt className="text-slate">Existing BUA</dt>
                    <dd className="font-medium">{data.existing_bua_sqm} sqm</dd>
                  </div>
                  <div className="flex justify-between mt-1">
                    <dt className="text-slate">Zonal RRR</dt>
                    <dd className="font-medium">₹{data.zonal_rrr}/sqm</dd>
                  </div>
                </div>
              </dl>
              <p className="text-xs text-slate bg-amber-50 rounded px-3 py-2">
                By submitting you confirm that all details are accurate. The application
                number will be assigned on submission.
              </p>
              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded bg-harbour text-white font-medium py-2 text-sm hover:bg-harbour/90 transition-colors disabled:opacity-60"
              >
                {submitting ? "Submitting…" : "Submit Application"}
              </button>
            </form>
          )}
        </div>

        <p className="mt-4 text-center text-sm text-slate">
          Already have an account?{" "}
          <a href="/" className="text-teal-link underline">
            Sign in
          </a>
        </p>
      </div>
    </main>
  );
}
