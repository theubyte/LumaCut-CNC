import { createRoot } from 'react-dom/client';
import '@/ui/base.css';
import { App } from '@/app/App';
import { applyTheme, useUi } from '@/store/ui';

applyTheme(useUi.getState().theme);
createRoot(document.getElementById('root')!).render(<App />);
// No browser context menu in the installed app, except in text fields.
window.addEventListener('contextmenu', (e) => { if (!(e.target as HTMLElement).closest('input,textarea')) e.preventDefault(); });
