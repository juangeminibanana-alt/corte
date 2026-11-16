"""Capa de plataforma del hub (windows-shell; BUILD_SPEC §3.1, §6.6, §6.7; 04 §A).

Solo Windows: `plataforma.windows` tiene la instancia única (literal de 04 §A.5), la ventana pywebview, la barra de
título con DWM, la bandeja, el inicio con Windows, la `js_api` (ApiPywebview), los globos programados, la detección de
WebView2, los ganchos de navegación (04 §A.9 + C43) y la autoprueba. El punto de entrada es `creatorhub.__main__`.
"""
from __future__ import annotations
