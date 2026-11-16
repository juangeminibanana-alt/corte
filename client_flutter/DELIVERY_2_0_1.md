# Corte 2.0.1 · apariencia

Claro, Oscuro y Sistema están disponibles en Configuración → Apariencia en el proyecto compartido Android, Windows y web. La elección se aplica al momento y se guarda mediante las preferencias de la cuenta en Google Cloud. Antes de iniciar sesión, la pantalla de acceso sigue el tema del dispositivo.

Las superficies, textos, fotos sin cargar, estados, gráficos, formularios, menús y calendarios respetan ambos temas. La navegación negra y los acentos coral y cian conservan la identidad elegida. La barra de título de Windows sigue el tema efectivo de la aplicación.

La preferencia utiliza la misma copia privada y cola de cambios existentes. Si no hay conexión se indica que falta enviarla; los conflictos se muestran para resolverlos sin sobrescribir otros campos. Cambiar apariencia conserva los borradores de firma y planificación. Las respuestas de una cuenta anterior no cambian el tema de la cuenta actual.

La web continúa en [Corte Flutter](https://corte-e-book-21589.web.app/flutter/). Los paquetes 2.0.0 permanecen intactos. iOS sigue aplazado.

Validación: 90 pruebas Flutter aprobadas, incluido contraste AA de textos y acentos sobre las superficies de ambos temas, tamaños 360/768/1440, seguimiento del sistema, persistencia tras reinicio sin conexión, conflictos, aislamiento entre cuentas y conservación de borradores. La compilación nativa de Windows se realiza en GitHub Actions; su paquete completo incluye el runtime.
