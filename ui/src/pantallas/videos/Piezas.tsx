/**
 * Piezas del Detalle de video que comparten el detalle con ventas (PantallaVideo.tsx) y el de un video sin ventas del
 * catálogo (DetalleCatalogo.tsx, rev. 6): sección en tarjeta con título, muestras vinculadas e ID del video con [Copiar].
 */
import { useMemo, type ReactElement, type ReactNode } from 'react';
import { useConsulta } from '@/datos';
import { EnlaceRuta, navegar } from '@/app';
import { BotonIcono, Icono, Tarjeta, useToast } from '@/componentes';
import { formato } from '@/dominio';
import { TarjetaMuestra } from '@/bloques';
import { copiarTexto } from '@/plataforma';
import { muestraConNombre } from './logica';
import { T } from './textos';
import { cx, rutaMuestra } from './util';
import css from './videos.module.css';

export function Seccion(p: { titulo: string; nota?: string; children: ReactNode; className?: string }): ReactElement {
  return (
    <Tarjeta padding="amplio" className={`${css.seccion} ${p.className ?? ''}`}>
      <section aria-label={p.titulo} className={cx(css.seccionInterior)}>
        <header className={cx(css.seccionCabeza)}>
          <h2 className={cx(css.seccionTitulo)}>{p.titulo}</h2>
          {p.nota ? <p className={cx(css.seccionNota)}>{p.nota}</p> : null}
        </header>
        {p.children}
      </section>
    </Tarjeta>
  );
}

export function IdVideo(p: { id: string }): ReactElement {
  const toast = useToast();
  return (
    <p className={cx(css.id)}>
      <span>{T.idVideo}</span>
      <code className={cx(css.mono)} title={p.id}>{p.id}</code>
      <BotonIcono
        icono="Copy"
        etiqueta={T.copiarId}
        tamano="sm"
        alPulsar={() => void copiarTexto(p.id).then((ok) => ok && toast.mostrar({ texto: T.idCopiado, tono: 'ok' }))}
      />
    </p>
  );
}

/** «Muestras vinculadas» (application_id del contrato): la tarjeta de la muestra si está en la lista; si no, su enlace. */
export function SeccionMuestras(p: { ids: readonly string[] }): ReactElement {
  const muestras = useConsulta('muestras', {}, { activa: p.ids.length > 0 });
  const porId = useMemo(() => new Map((muestras.datos?.items ?? []).map((m) => [m.application_id, m])), [muestras.datos]);
  return (
    <Seccion titulo={T.muestras}>
      {p.ids.length === 0 ? (
        <p className={cx(css.vacioCorto)}>{T.muestrasVacio}</p>
      ) : (
        <ul className={cx(css.listaMuestras)}>
          {p.ids.map((id) => {
            const m = porId.get(id);
            return (
              <li key={id}>
                {m ? (
                  <TarjetaMuestra muestra={muestraConNombre(m)} variante="lista" conAccion={false} alAbrir={() => navegar(rutaMuestra(id))} />
                ) : (
                  <EnlaceRuta a={rutaMuestra(id)} className={cx(css.enlaceMuestra)}>
                    {T.muestraSinDatos(formato.idCorto(id))}
                    <Icono nombre="ChevronRight" tamano={16} />
                  </EnlaceRuta>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Seccion>
  );
}
