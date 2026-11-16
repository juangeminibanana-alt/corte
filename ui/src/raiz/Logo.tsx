/**
 * @/raiz · marca de la barra lateral: el ícono de app de 02 §2.2 (spec/assets/icon.svg, misma geometría) en su versión
 * plana. El ícono no cambia con el tema (como el de la app): mosaico grafito, corte lima y papel.
 */
import type { ReactElement } from 'react';
import css from './Logo.module.css';

export function Logo(p: { tamano: number }): ReactElement {
  return (
    <svg className={css.logo} width={p.tamano} height={p.tamano} viewBox="0 0 40 44" fill="none" aria-hidden="true" focusable="false">
      <path d="M9 15H31L33 35C33.2 37.1 31.6 39 29.5 39H10.5C8.4 39 6.8 37.1 7 35L9 15Z" stroke="currentColor" strokeWidth="2.6" strokeLinejoin="round" />
      <path d="M14 15V10A6 6 0 0 1 26 10V15" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M29 5L31 1" stroke="var(--brand)" strokeWidth="3" strokeLinecap="round" />
      <path d="M34 10L38 8" stroke="#00b8bd" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
