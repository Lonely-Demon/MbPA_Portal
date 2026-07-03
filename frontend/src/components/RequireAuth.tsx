import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { client } from "../api/client";

interface RequireAuthProps {
  /** If set, the signed-in user's user_type must be one of these. */
  roles?: string[];
  children: ReactNode;
}

/**
 * L-3: shared route guard. Every protected page used to reimplement its own
 * /api/identity/me/ check in a useEffect, with its own copy of the loading
 * flash before redirect — easy to forget on the next protected route. The
 * backend is the real enforcement boundary (this is UX only, see the
 * OfficerDashboard role-check comment history), but the check still needs
 * to exist exactly once.
 */
export default function RequireAuth({ roles, children }: RequireAuthProps) {
  const navigate = useNavigate();
  const [authorized, setAuthorized] = useState(false);
  // Stable dependency key — `roles` array literals passed inline by callers
  // would otherwise be a new reference on every render.
  const rolesKey = roles?.join(",") ?? "";

  useEffect(() => {
    let cancelled = false;
    async function check() {
      const { data, error } = await client.GET("/api/identity/me/");
      if (cancelled) return;
      const allowedRoles = rolesKey ? rolesKey.split(",") : null;
      if (error || !data || (allowedRoles && !allowedRoles.includes(data.user_type))) {
        navigate("/");
        return;
      }
      setAuthorized(true);
    }
    check();
    return () => {
      cancelled = true;
    };
  }, [navigate, rolesKey]);

  if (!authorized) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center">
        <p className="text-slate text-sm">Loading…</p>
      </div>
    );
  }

  return <>{children}</>;
}
