import { Link, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { EmptyState, buttonClass } from './components/ui';
import { RunPage } from './pages/RunPage';
import { DashboardPage } from './pages/DashboardPage';
import { ReferencePage } from './pages/ReferencePage';
import { Compass } from 'lucide-react';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<RunPage />} />
        <Route path="runs/:id" element={<RunPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="reference" element={<ReferencePage />} />
        <Route
          path="*"
          element={
            <EmptyState
              className="py-24"
              icon={<Compass className="h-5 w-5" />}
              title="Page not found"
              body="That address does not match any screen."
              action={
                <Link to="/" className={buttonClass('primary')}>
                  Back to processing
                </Link>
              }
            />
          }
        />
      </Route>
    </Routes>
  );
}
