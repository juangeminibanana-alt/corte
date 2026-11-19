/**
 * @/app · límite de error por sección (01 §4.16): «Algo salió mal al mostrar esta sección.» [Reintentar]. Un error al
 * pintar una tarjeta nunca tumba la app completa: se queda dentro de la sección que falló.
 */
import { Component, type ErrorInfo, type ReactElement, type ReactNode } from 'react';
import { Boton, Icono } from '@/componentes';
import css from './LimiteError.module.css';

export const TEXTO_ERROR_SECCION = 'Algo salió mal al mostrar esta sección.';

interface Props {
  seccion: string;
  children: ReactNode;
}

export function esErrorDeModulo(error: unknown): boolean {
  return error instanceof Error && /dynamically imported module|importing a module script|loading chunk|loading css chunk/i.test(error.message);
}

class Limite extends Component<Props, { error: boolean; modulo: boolean; intento: number }> {
  override state = { error: false, modulo: false, intento: 0 };

  static getDerivedStateFromError(error: unknown): { error: boolean; modulo: boolean } {
    return { error: true, modulo: esErrorDeModulo(error) };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    if (import.meta.env.DEV) console.error(`[CUTGC · ${this.props.seccion}]`, error, info.componentStack);
  }

  override render(): ReactNode {
    if (!this.state.error) return <Reinicio key={this.state.intento}>{this.props.children}</Reinicio>;
    return (
      <div role="alert" className={css.error} data-limite-error={this.props.seccion}>
        <span className={css.icono} aria-hidden="true">
          <Icono nombre="CircleAlert" tamano={20} />
        </span>
        <p className={css.texto}>{this.state.modulo ? 'No pudimos abrir esta sección. Recarga CUTGC para volver a intentarlo.' : TEXTO_ERROR_SECCION}</p>
        <Boton variante="secundario" tamano="sm" icono="RotateCcw" alPulsar={() => this.state.modulo ? window.location.reload() : this.setState((s) => ({ error: false, modulo: false, intento: s.intento + 1 }))}>
          {this.state.modulo ? 'Recargar CUTGC' : 'Reintentar'}
        </Boton>
      </div>
    );
  }
}

/** Fragmento con clave: al reintentar se vuelve a montar el contenido desde cero. */
function Reinicio(p: { children: ReactNode }): ReactElement {
  return <>{p.children}</>;
}

/** "Algo salió mal al mostrar esta sección." [Reintentar] — nunca tumba la app completa (01_ux §4.16). */
export function LimiteError(p: { children: ReactNode; seccion: string }): ReactElement {
  return <Limite seccion={p.seccion}>{p.children}</Limite>;
}
