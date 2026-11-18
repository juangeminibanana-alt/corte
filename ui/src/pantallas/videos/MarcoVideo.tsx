/**
 * Portada grande del Detalle de video (01_ux §4.12, C4, C43). La portada es la foto del producto que más vendió en ese
 * video (MiniaturaVideo, con el rótulo «Foto del producto»; póster tipográfico si no hay foto).
 * - Windows (esWindows()): encima va el ReproductorTikTok oficial, bajo demanda ([Reproducir aquí]); su respaldo es
 *   «Abrir en TikTok».
 * - Android y navegador: NUNCA el reproductor; la pantalla pone [Abrir en TikTok] (BotonAbrirVideo), que abre el
 *   enlace fuera de la app con abrirExterno (en Android, Intent ACTION_VIEW que toma la app de TikTok).
 * rev. 6 · PortadaCatalogo: la de un video sin ventas del catálogo. Solo su portada REAL (nunca una foto de producto);
 * sin portada, el mosaico de respaldo. El reproductor no se ofrece si TikTok ya no lo da como público.
 */
import type { ReactElement } from 'react';
import type * as C from '@/contrato';
import { Boton, Foto, MiniaturaVideo, ReproductorTikTok, useToast } from '@/componentes';
import { formato } from '@/dominio';
import { abrirExterno, esWindows } from '@/plataforma';
import { portadaDe } from './logica';
import { T } from './textos';
import { cx } from './util';
import css from './videos.module.css';

export function useAbrirVideo(enlace: string): () => void {
  const toast = useToast();
  return () => {
    void abrirExterno(enlace).then((ok) => {
      if (!ok) toast.mostrar({ texto: T.abrirFallo, tono: 'error' });
    });
  };
}

/** [Abrir en TikTok] (fuera de la app). */
export function BotonAbrirVideo(p: { enlace: string; variante: 'primario' | 'secundario'; tamano?: 'md' | 'lg'; anchoCompleto?: boolean; className?: string }): ReactElement {
  const abrir = useAbrirVideo(p.enlace);
  return (
    <Boton
      variante={p.variante}
      tamano={p.tamano ?? 'md'}
      iconoFinal="ExternalLink"
      alPulsar={abrir}
      {...(p.anchoCompleto ? { anchoCompleto: true } : {})}
      {...(p.className ? { className: p.className } : {})}
    >
      {T.abrirEnTikTok}
    </Boton>
  );
}

/** `lugar`: su lugar por comisión en todo tu historial (el mismo «#4» de la galería; solo del 1 al 10). */
export function PortadaVideo(p: { video: C.FilaVideo; nombre: string; anchoCss: number; lugar?: number | null; className?: string }): ReactElement {
  const v = p.video;
  const abrir = useAbrirVideo(v.enlace);
  const windows = esWindows();
  const dinero = formato.dinero(v.comision_estimada_centavos);
  // rev. 5: la portada REAL del video (Display API) cuando existe; si no, la foto del producto rotulada.
  const portada = portadaDe(v);
  return (
    <div className={`${css.marco} ${p.className ?? ''}`} {...(windows ? { 'data-reproductor': '' } : {})}>
      <MiniaturaVideo
        url={portada.url}
        {...(portada.delProducto ? { rotulo: T.fotoDelProducto } : {})}
        {...(p.lugar && p.lugar <= 10 ? { ranking: p.lugar } : {})}
        comision={dinero}
        unidades={T.unidades(v.unidades)}
        nombre={p.nombre}
        fechaPoster={formato.fechaCorta(v.primera_venta)}
        tienda={v.tienda_principal}
        anchoCss={p.anchoCss}
        etiqueta={T.etiquetaVideo(p.lugar ?? null, dinero, v.unidades, p.nombre)}
        className={cx(css.marcoPortada)}
      />
      {windows ? (
        <ReproductorTikTok contentId={v.content_id} titulo={T.reproductorTitulo(p.nombre)} alAbrirFuera={abrir} className={cx(css.reproductor)} />
      ) : null}
    </div>
  );
}

export function PortadaCatalogo(p: { video: C.VideoCatalogo; nombre: string; anchoCss: number; className?: string }): ReactElement {
  const v = p.video;
  const abrir = useAbrirVideo(v.enlace);
  const reproductor = esWindows() && v.publicacion !== 'no_publico';
  return (
    <div className={`${css.marco} ${p.className ?? ''}`} {...(reproductor ? { 'data-reproductor': '' } : {})}>
      <Foto url={v.portada} alt={T.portadaDe(p.nombre)} anchoCss={p.anchoCss} proporcion="9:16" radio="lg" prioridad="alta" className={cx(css.marcoPortada)} />
      {reproductor ? (
        <ReproductorTikTok contentId={v.content_id} titulo={T.reproductorTitulo(p.nombre)} alAbrirFuera={abrir} className={cx(css.reproductor)} />
      ) : null}
    </div>
  );
}
