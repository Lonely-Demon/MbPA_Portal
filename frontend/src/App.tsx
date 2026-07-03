import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { initCsrf } from "./lib/api";
import ErrorBoundary from "./components/ErrorBoundary";
import RequireAuth from "./components/RequireAuth";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ApplicantDashboard from "./pages/ApplicantDashboard";
import OfficerDashboard from "./pages/OfficerDashboard";
import StatusLookup from "./pages/StatusLookup";
import StreamPlanner from "./pages/StreamPlanner";

export default function App() {
  useEffect(() => {
    initCsrf().catch(console.error);
  }, []);

  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/status" element={<StatusLookup />} />
          <Route path="/planner" element={<StreamPlanner />} />
          <Route
            path="/dashboard/*"
            element={
              <RequireAuth>
                <ApplicantDashboard />
              </RequireAuth>
            }
          />
          <Route
            path="/officer/*"
            element={
              <RequireAuth roles={["officer", "admin"]}>
                <OfficerDashboard />
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
