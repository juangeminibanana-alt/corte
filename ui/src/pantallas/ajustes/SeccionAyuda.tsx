/** I. Ayuda (01_ux §4.14 I): 5 preguntas, cada una con su respuesta de 2 a 4 líneas, en acordeón accesible (<details>). */
import type { ReactElement } from 'react';
import { Icono } from '@/componentes';
import { Grupo, Seccion } from './piezas';
import { T } from './textos';
import css from './ajustes.module.css';
import { cx } from './clases';
import { esNube } from '../../nube/entorno';

const AYUDA_WEB = [
  { pregunta: '¿Necesito mi PC encendida?', respuesta: 'Puedes abrir CUTGC desde tu teléfono o computadora usando internet. El servidor mantiene tus datos y realiza la sincronización automática según el intervalo que elijas.' },
  { pregunta: '¿Cómo conecto mi cuenta?', respuesta: 'Abre Configuración › TikTok Shop y autoriza tu cuenta en la página oficial de TikTok. La conexión de métricas de videos se configura por separado.' },
  { pregunta: '¿Quién puede entrar a mi espacio?', respuesta: 'El servicio verifica el acceso con Google y permite únicamente las cuentas autorizadas en la configuración del servidor. Cierra la sesión al terminar en un dispositivo compartido.' },
  { pregunta: '¿Dónde se guardan mis respaldos?', respuesta: 'Los respaldos que creas desde Privacidad y datos se guardan de forma privada en Firebase Storage. Puedes importarlos desde esa misma sección. No incluyen las credenciales de TikTok.' },
  { pregunta: '¿Por qué no aparecen mis datos nuevos?', respuesta: 'Revisa la última sincronización en Configuración › Sincronización. Si TikTok solicita una nueva autorización, vuelve a conectar tu cuenta. Los datos ya guardados se conservan.' },
];

export function SeccionAyuda(): ReactElement {
  return (
    <Seccion titulo={T.secciones.ayuda.titulo} id="ayuda" descripcion={T.ayudaDescripcion}>
      <Grupo>
        {(esNube() ? AYUDA_WEB : T.ayuda).map((x, i) => (
          <details key={x.pregunta} className={cx(css.pregunta)} {...(i === 0 ? { open: true } : {})}>
            <summary className={cx(css.preguntaResumen)}>
              <span>{x.pregunta}</span>
              <Icono nombre="ChevronDown" tamano={18} className={cx(css.preguntaFlecha)} />
            </summary>
            <p className={cx(css.preguntaRespuesta)}>{x.respuesta}</p>
          </details>
        ))}
      </Grupo>
    </Seccion>
  );
}
