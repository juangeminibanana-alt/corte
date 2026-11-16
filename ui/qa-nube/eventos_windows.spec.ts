import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { conectarEventosShellWindows, crearTransporteWindows } from '../src/datos/transporte_windows';

const entorno = vi.hoisted(() => ({ nube: false }));
vi.mock('../src/nube/entorno', () => ({ esNube: () => entorno.nube, expirarSesionNube: vi.fn() }));
vi.mock('../src/datos/dominio', () => ({ dom: {}, registrarMetaDe: vi.fn() }));

class FuentePrueba extends EventTarget {
  static abiertas: FuentePrueba[] = [];
  readonly url: string;
  cerrada = false;
  constructor(url: string) { super(); this.url = url; FuentePrueba.abiertas.push(this); }
  close(): void { this.cerrada = true; }
  emitir(nombre: string, cuerpo: unknown): void {
    this.dispatchEvent(new MessageEvent(nombre, { data: JSON.stringify(cuerpo) }));
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  FuentePrueba.abiertas = [];
  entorno.nube = false;
  vi.stubGlobal('EventSource', FuentePrueba);
  vi.stubGlobal('fetch', vi.fn());
});
afterEach(() => {
  Reflect.deleteProperty(window, 'pywebview');
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test('el canal loopback conserva cierre, navegación y recordatorio sin duplicar eventos de Google', () => {
  const evento = vi.fn();
  const invalidar = vi.fn();
  const cerrar = conectarEventosShellWindows({ evento, invalidar });
  const fuente = FuentePrueba.abiertas[0]!;
  expect(fuente.url).toBe('/api/events');
  fuente.emitir('ventana.preguntar_cierre', {});
  fuente.emitir('ventana.mostrar_ruta', { ruta: '/plan' });
  fuente.emitir('recordatorio.vencido', { recordatorio: { id: 'recordatorio-local' } });
  fuente.emitir('message', { tipo: 'ventana.mostrar_ruta', ruta: '/ajustes' });
  fuente.emitir('ventana.preguntar_cierre', { tipo: 'sync.fin', estado: {} });
  fuente.emitir('message', { tipo: 'datos.cambiaron', secciones: ['plan'] });
  fuente.emitir('datos.cambiaron', { secciones: ['local'], local_rev: 9 });
  expect(evento.mock.calls.map(([e]) => e.tipo)).toEqual([
    'ventana.preguntar_cierre', 'ventana.mostrar_ruta', 'recordatorio.vencido', 'ventana.mostrar_ruta', 'datos.cambiaron',
  ]);
  expect(invalidar).not.toHaveBeenCalled();
  cerrar();
  fuente.emitir('ventana.preguntar_cierre', {});
  expect(evento).toHaveBeenCalledTimes(5);
  expect(fuente.cerrada).toBe(true);
});

test('Windows combina polling con un único SSE local y elimina los recursos al desmontar', () => {
  Object.defineProperty(window, 'pywebview', { value: {}, configurable: true });
  entorno.nube = true;
  const cerrar = crearTransporteWindows().conectarEventos({ evento: vi.fn(), invalidar: vi.fn() });
  expect(FuentePrueba.abiertas.map((f) => f.url)).toEqual(['/api/events']);
  expect(vi.getTimerCount()).toBe(1);
  cerrar();
  expect(vi.getTimerCount()).toBe(0);
  expect(FuentePrueba.abiertas[0]!.cerrada).toBe(true);
});

test('la página web en Google utiliza polling sin abrir un canal SSE', () => {
  entorno.nube = true;
  const cerrar = crearTransporteWindows().conectarEventos({ evento: vi.fn(), invalidar: vi.fn() });
  expect(FuentePrueba.abiertas).toHaveLength(0);
  cerrar();
});
