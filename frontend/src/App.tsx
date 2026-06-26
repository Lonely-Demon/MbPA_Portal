import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { initCsrf } from "./lib/api";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ApplicantDashboard from "./pages/ApplicantDashboard";
import OfficerDashboard from "./pages/OfficerDashboard";
import StatusLookup from "./pages/StatusLookup";

export default function App() {
  useEffect(() => {
    initCsrf().catch(console.error);
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/status" element={<StatusLookup />} />
        <Route path="/dashboard/*" element={<ApplicantDashboard />} />
        <Route path="/officer/*" element={<OfficerDashboard />} />
      </Routes>
    </BrowserRouter>
  );
}
