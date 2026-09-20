import { Navigate } from 'react-router-dom';
import type { ReactElement } from 'react';
import { useAuth } from '../auth/store';

export default function ProtectedRoute({ children }: { children: ReactElement }): ReactElement {
  return useAuth().token ? children : <Navigate to="/login" replace />;
}