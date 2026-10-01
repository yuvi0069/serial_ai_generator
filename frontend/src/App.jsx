import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./context/AuthContext.jsx";
import AuthPage from "./pages/AuthPage.jsx";
import Workspace from "./pages/Workspace.jsx";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="boot">Opening your desk</div>;
  if (!user) return <AuthPage />;
  return (
    <Routes>
      <Route path="/" element={<Workspace />} />
      <Route path="/s/:storyId" element={<Workspace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
