import React from 'react';import {createRoot} from 'react-dom/client';import App from './App';
fetch('/config.json').then(r=>r.json()).then(config=>createRoot(document.getElementById('root')).render(<App config={config}/>)).catch(()=>{document.getElementById('root').textContent='Configuration unavailable';});
