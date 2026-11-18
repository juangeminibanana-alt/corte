/**
 * Encabezado de #/videos compartido por sus dos vistas: título, contexto y [Actualizar]. rev. 6: debajo, las pestañas
 * «Con ventas | Todos» con el subrayado coral de Muestras (DESIGN.md), solo si el hub tiene el catálogo. Cambiar de
 * pestaña reemplaza la entrada del historial (no apila vistas de la misma pantalla) y deja el orden de cada vista.
 */
import type { ReactElement } from 'react';
import { useSync } from '@/datos';
import { navegar } from '@/app';
import { Boton } from '@/componentes';
import type { SegmentoVideos } from './logicaCatalogo';
import { T } from './textos';
import css from './videos.module.css';

export const RUTA_SEGMENTO: Readonly<Record<SegmentoVideos, string>> = { ventas: '/videos', todos: '/videos?segmento=todos' };

export function CabeceraVideos(): ReactElement {
  const sync = useSync();
  return (
    <header className={css.videoCabecera}>
      <div><h1>{T.titulo}</h1><p>{T.subtitulo}</p></div>
      <Boton variante="secundario" icono="RefreshCw" cargando={sync.estado?.en_curso === true} deshabilitado={!sync.puede} alPulsar={() => void sync.sincronizar()}>{T.actualizar}</Boton>
    </header>
  );
}

const PESTANAS: ReadonlyArray<{ id: SegmentoVideos; etiqueta: string }> = [
  { id: 'ventas', etiqueta: T.pestanaConVentas },
  { id: 'todos', etiqueta: T.pestanaTodos },
];

export function PestanasVideos(p: { activa: SegmentoVideos }): ReactElement {
  return (
    <nav className={css.pestanas} aria-label={T.pestanas}>
      {PESTANAS.map((t) => (
        <a
          key={t.id}
          href={`#${RUTA_SEGMENTO[t.id]}`}
          aria-current={p.activa === t.id ? 'page' : undefined}
          onClick={(ev) => {
            ev.preventDefault();
            if (p.activa !== t.id) navegar(RUTA_SEGMENTO[t.id], { reemplazar: true });
          }}
        >
          {t.etiqueta}
        </a>
      ))}
    </nav>
  );
}
