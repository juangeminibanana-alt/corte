/* Punto de entrada de la interfaz de Corte (BUILD_SPEC §8.1, orden de 02 §4.1): fuentes → tokens → base → App. */
import './estilos/fuentes.css';
import './estilos/tokens.css';
import './estilos/base.css';
import './estilos/shop.css';
import { createRoot } from 'react-dom/client';
import { App } from '@/raiz';
import { AccesoNube } from './nube/AccesoNube';
import { AprobarDispositivo } from './nube/AprobarDispositivo';

const contenedor = document.getElementById('raiz');
if (!contenedor) throw new Error('Falta el contenedor #raiz en index.html');

createRoot(contenedor).render(<AccesoNube>{window.location.pathname === '/conectar-dispositivo' ? <AprobarDispositivo /> : <App />}</AccesoNube>);
