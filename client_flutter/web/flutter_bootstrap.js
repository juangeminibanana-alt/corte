{{flutter_js}}
{{flutter_build_config}}

window.addEventListener('flutter-first-frame', () => {
  document.getElementById('corte-loading')?.remove();
}, { once: true });

_flutter.loader.load({
  config: {
    fontFallbackBaseUrl: new URL('fonts/', document.baseURI).href,
  },
  serviceWorkerSettings: {
    serviceWorkerVersion: {{flutter_service_worker_version}},
  },
});
