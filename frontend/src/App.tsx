import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Login from './pages/Login';
import Register from './pages/Register';
import Records from './pages/Records';
import RecordForm from './pages/RecordForm';
import RecordDetail from './pages/RecordDetail';
import Dashboard from './pages/Dashboard';
import Profiles from './pages/Profiles';
import CaseDetail from './pages/CaseDetail';
import DataDescription from './pages/DataDescription';
import AdminUsers from './pages/AdminUsers';
import ImportWizard from './pages/ImportWizard';
import TemplateAdmin from './pages/TemplateAdmin';
import SoftwareAdmin from './pages/SoftwareAdmin';
import SourceAdmin from './pages/SourceAdmin';
import SoftwareAnalysis from './pages/SoftwareAnalysis';
import ProtectedRoute from './components/ProtectedRoute';
import AppShell from './components/AppShell';

function BusinessPage({ children }: { children: JSX.Element }): JSX.Element { return <ProtectedRoute><AppShell>{children}</AppShell></ProtectedRoute>; }
export default function App(): JSX.Element { return <BrowserRouter><Routes>
  <Route path="/login" element={<Login />} />
  <Route path="/register" element={<Register />} />
  <Route path="/dashboard" element={<BusinessPage><Dashboard /></BusinessPage>} />
  <Route path="/profiles" element={<BusinessPage><Profiles /></BusinessPage>} />
  <Route path="/profiles/:softwareId" element={<BusinessPage><Profiles /></BusinessPage>} />
  <Route path="/cases/:id" element={<BusinessPage><CaseDetail /></BusinessPage>} />
  <Route path="/data-description" element={<BusinessPage><DataDescription /></BusinessPage>} />
  <Route path="/records" element={<BusinessPage><Records /></BusinessPage>} />
  <Route path="/records/new" element={<BusinessPage><RecordForm /></BusinessPage>} />
  <Route path="/records/:id" element={<BusinessPage><RecordDetail /></BusinessPage>} />
  <Route path="/import" element={<BusinessPage><ImportWizard /></BusinessPage>} />
  <Route path="/admin/users" element={<BusinessPage><AdminUsers /></BusinessPage>} />
  <Route path="/admin/templates" element={<BusinessPage><TemplateAdmin /></BusinessPage>} />
  <Route path="/admin/software" element={<BusinessPage><SoftwareAdmin /></BusinessPage>} />
  <Route path="/admin/sources" element={<BusinessPage><SourceAdmin /></BusinessPage>} />
  <Route path="/analysis/:softwareCode" element={<BusinessPage><SoftwareAnalysis /></BusinessPage>} />
  <Route path="*" element={<Navigate to="/dashboard" replace />} />
</Routes></BrowserRouter>; }