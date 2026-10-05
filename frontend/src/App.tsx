import { Route, Routes } from "react-router";
import { Shell } from "./components/Shell";
import { Home, Packs } from "./pages/Home";
import { PackPage } from "./pages/PackPage";
import { RunPage } from "./pages/RunPage";
import { ComponentsPreview } from "./pages/ComponentsPreview";
import { NotFound } from "./pages/NotFound";

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Home />} />
        <Route path="packs" element={<Packs />} />
        <Route path="packs/:packId" element={<PackPage />} />
        <Route path="runs/:runId" element={<RunPage />} />
        <Route path="components" element={<ComponentsPreview />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
