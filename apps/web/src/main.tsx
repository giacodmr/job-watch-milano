import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import Candidature from './Candidature';
import './styles.css';
import './candidature.css';

const root = document.getElementById('root');
if (!root) throw new Error('Application root missing');
createRoot(root).render(
  <StrictMode>
    {window.location.pathname.replace(/\/$/,'')==='/candidature' ? <Candidature /> : <App />}
  </StrictMode>,
);
