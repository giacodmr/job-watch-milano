import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import Candidature from './Candidature';
import Opportunita from './Opportunita';
import './styles.css';
import './candidature.css';
import './opportunita.css';

const root = document.getElementById('root');
if (!root) throw new Error('Application root missing');
createRoot(root).render(
  <StrictMode>
    {window.location.pathname.replace(/\/$/,'')==='/candidature' ? <Candidature /> :
      window.location.pathname.replace(/\/$/,'')==='/opportunita' ? <Opportunita /> : <App />}
  </StrictMode>,
);
