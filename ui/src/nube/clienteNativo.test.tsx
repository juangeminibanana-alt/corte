import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SesionNativa } from './clienteNativo';

const mocks = vi.hoisted(() => ({
  leerSesionNativa: vi.fn(), accionNativa: vi.fn(), pedir: vi.fn(), plataforma: vi.fn(),
}));
vi.mock('./clienteNativo', () => ({ leerSesionNativa: mocks.leerSesionNativa, accionNativa: mocks.accionNativa }));
vi.mock('@/plataforma', () => ({ infoPlataforma: mocks.plataforma }));
vi.mock('../datos/transporte', () => ({ obtenerTransporte: async () => ({ pedir: mocks.pedir }) }));

import { AccesoClienteNativo } from './AccesoClienteNativo';
import { fetchCorte } from './servicio';
import { ErrorHub } from '../datos/errores';

const inicial: SesionNativa = {
  native_client: true, platform: 'android', authenticated: false,
  connected: false, offline: true, hay_copia: false,
};

describe('acceso nativo y transporte de Android', () => {
  let contenedor: HTMLDivElement;
  let raiz: Root;
  let sesion: SesionNativa;
  const montado = vi.fn();
  const desmontado = vi.fn();

  function DatosPrivados() {
    useEffect(() => { montado(); return () => { desmontado(); }; }, []);
    return <p>Resultados privados del creador</p>;
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.stubGlobal('fetch', vi.fn());
    vi.clearAllMocks();
    sesion = { ...inicial };
    mocks.leerSesionNativa.mockImplementation(async () => ({ ...sesion }));
    mocks.plataforma.mockReturnValue({ plataforma: 'android' });
    contenedor = document.createElement('div');
    document.body.appendChild(contenedor);
    raiz = createRoot(contenedor);
  });

  afterEach(async () => {
    await act(async () => { raiz.unmount(); });
    contenedor.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function mostrar() {
    await act(async () => { raiz.render(<AccesoClienteNativo inicial={sesion}><DatosPrivados /></AccesoClienteNativo>); });
  }

  it('no monta consultas ni contenido privado antes de aprobar el dispositivo', async () => {
    await mostrar();
    expect(contenedor.textContent).toContain('Tu espacio, conectado');
    expect(contenedor.textContent).not.toContain('Resultados privados');
    expect(montado).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(7500); });
    expect(mocks.leerSesionNativa.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(montado).not.toHaveBeenCalled();
  });

  it('entra al aprobar y desmonta los datos privados cuando el dispositivo es revocado', async () => {
    await mostrar();
    sesion = { ...sesion, authenticated: true, connected: true, offline: false };
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(contenedor.textContent).toContain('Resultados privados del creador');
    expect(montado).toHaveBeenCalledTimes(1);
    sesion = { ...sesion, authenticated: false, connected: false, offline: true };
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(contenedor.textContent).toContain('Continuar con Google');
    expect(contenedor.textContent).not.toContain('Resultados privados');
    expect(desmontado).toHaveBeenCalledTimes(1);
  });

  it('revalida al recibir el evento nativo y conserva el estado ante un fallo temporal', async () => {
    sesion = { ...sesion, authenticated: true, connected: false, hay_copia: true };
    await mostrar();
    mocks.leerSesionNativa.mockRejectedValueOnce(new Error('fallo temporal sintético'));
    await act(async () => { window.dispatchEvent(new Event('creatorhub-conexion')); });
    expect(contenedor.textContent).toContain('Resultados privados del creador');
    sesion = { ...sesion, authenticated: false };
    await act(async () => { window.dispatchEvent(new Event('creatorhub-conexion')); });
    expect(contenedor.textContent).toContain('Continuar con Google');
    expect(contenedor.textContent).not.toContain('Resultados privados');
  });

  it('envía el cuerpo JSON de la mutación Android por el puente sin hacer fetch POST', async () => {
    const cuerpo = { ops: [{ op_id: 'synthetic-op-1', tipo: 'nota.crear', datos: { texto: 'Café ☕', fijada: false } }] };
    mocks.pedir.mockResolvedValueOnce({ resultados: [{ op_id: 'synthetic-op-1', estado: 'aplicada' }] });
    const r = await fetchCorte('/api/local/ops', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });
    expect(mocks.pedir).toHaveBeenCalledExactlyOnceWith('POST', '/api/local/ops', cuerpo);
    expect(fetch).not.toHaveBeenCalled();
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ resultados: [{ op_id: 'synthetic-op-1', estado: 'aplicada' }] });
  });

  it('conserva el estado HTTP de errores del puente para no simular una mutación exitosa', async () => {
    mocks.pedir.mockRejectedValueOnce(new ErrorHub('red', 'Fallo temporal sintético', 503));
    const r = await fetchCorte('/api/sync', { method: 'POST', body: '{}' });
    expect(r.status).toBe(503);
    expect(await r.json()).toEqual({ error: { codigo: 'red', mensaje: 'Fallo temporal sintético' } });
    expect(fetch).not.toHaveBeenCalled();
  });
});
