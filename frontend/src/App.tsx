import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import KnowledgeBaseDetail from './pages/KnowledgeBaseDetail';
import GraphViewer from './pages/KnowledgeGraphViewer';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/kb/:id" element={<KnowledgeBaseDetail />} />
        <Route path="/graph-viewer" element={<GraphViewer />} />
      </Routes>
    </Router>
  );
}

export default App;
