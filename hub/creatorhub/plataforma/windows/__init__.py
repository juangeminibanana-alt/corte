"""Shell de Windows de Corte (windows-shell). Los módulos se importan por separado y de forma perezosa: ninguno carga
pywebview, pythonnet ni PIL al importarse, así no pesan en `t_hub_listo_ms` (C3, 04 §A.2).

- instancia.py ........ instancia única, activación y salida que se puede esperar (LITERAL de 04 §A.5)
- navegacion.py ....... lista de hosts de §6.4, NavigationStarting (04 §A.9), NewWindowRequested y FrameNavigationStarting (C43)
- dwm.py .............. color de la barra de título (DWMWA 20/34/35/36) y tema del sistema
- inicio_windows.py ... HKCU\\…\\Run + StartupApproved (04 §A.7)
- webview2.py ......... ¿está WebView2? (04 §A.2 paso 5) y el aviso con MessageBox
- notificaciones.py ... programar_notificaciones: temporizador propio y globos también con la ventana oculta (C44)
- bandeja.py .......... NotifyIcon de WinForms: «Abrir Corte» · «Sincronizar ahora» · «Salir»
- js_api.py ........... ApiPywebview EXACTO de spec/ui_firmas/plataforma.d.ts (BUILD §6.6)
- ventana.py .......... ventana pywebview (04 §A.4), geometría recordada, primer cierre (C23) y GanchosVentana
- autoprueba.py ....... --autoprueba (04 §A.2)
"""
from __future__ import annotations
