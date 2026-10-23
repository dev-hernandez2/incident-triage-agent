import { BrowserRouter, Route, Routes } from "react-router-dom";
import { IncidentDetail } from "./pages/IncidentDetail";
import { IncidentList } from "./pages/IncidentList";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<IncidentList />} />
        <Route path="/incidents/:id" element={<IncidentDetail />} />
      </Routes>
    </BrowserRouter>
  );
}
