/** Marca de Corte: dos cortes coral y cian de la dirección visual aprobada. */
import type { ReactElement } from 'react';
import css from './Logo.module.css';

export function Logo(p: { tamano: number }): ReactElement {
  return (
    <svg className={css.logo} width={p.tamano} height={p.tamano} viewBox="0 0 40 40" fill="none" aria-hidden="true" focusable="false">
      <path d="M5 32L22 8" stroke="var(--brand)" strokeWidth="7" strokeLinecap="round" />
      <path d="M18 32L35 8" stroke="var(--shop-cyan)" strokeWidth="7" strokeLinecap="round" />
    </svg>
  );
}
