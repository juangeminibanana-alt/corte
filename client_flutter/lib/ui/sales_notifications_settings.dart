import 'package:flutter/material.dart';

import '../app.dart';
import 'theme.dart';

class SalesNotificationsSettings extends StatelessWidget {
  const SalesNotificationsSettings({super.key});

  @override
  Widget build(BuildContext context) {
    final service = CorteScope.of(context).salesNotifications;
    if (!service.supported) {
      return const Text(
        'Activa los avisos de ventas desde Corte para Android o Windows.',
      );
    }
    return AnimatedBuilder(
      animation: service,
      builder: (context, _) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            title: const Text('Una notificación por cada venta nueva'),
            subtitle: Text(
              service.isWindows
                  ? 'Corte seguirá en la bandeja al cerrar la ventana. «Salir» detiene los avisos.'
                  : 'Recibe los avisos aunque Corte esté cerrada.',
            ),
            value: service.enabled,
            onChanged: service.busy
                ? null
                : (value) => service.setEnabled(value),
          ),
          Text(
            'Se avisa cuando TikTok reporta un pedido pagado. No se envían ventas antiguas al activar.',
            style: TextStyle(color: context.corte.muted, fontSize: 13),
          ),
          if (service.busy)
            const Padding(
              padding: EdgeInsets.only(top: 10),
              child: LinearProgressIndicator(),
            ),
          if (service.error != null)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                service.error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
        ],
      ),
    );
  }
}
