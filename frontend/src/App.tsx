import { useEffect } from "react";
import { initCsrf } from "./lib/api";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ApplicantDashboard from "./pages/ApplicantDashboard";
import OfficerDashboard from "./pages/OfficerDashboard";
import StatusLookup from "./pages/StatusLookup";

/** Minimal hash-based router — replace with react-router-dom when adding navigation. */
function usePage(): string {
  const path = window.location.pathname;
  if (path.startsWith("/signup")) return "signup";
  if (path.startsWith("/status")) return "status";
  if (path.startsWith("/officer")) return "officer";
  if (path.startsWith("/dashboard")) return "applicant";
  return "login";
}

export default function App() {
  useEffect(() => {
    initCsrf().catch(console.error);
  }, []);

  const page = usePage();

  return (
    <>
      {page === "login" && <Login />}
      {page === "signup" && <Signup />}
      {page === "status" && <StatusLookup />}
      {page === "applicant" && <ApplicantDashboard />}
      {page === "officer" && <OfficerDashboard />}
    </>
  );
}
