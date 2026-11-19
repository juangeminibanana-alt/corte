import 'package:flutter/material.dart';

import '../domain/domain.dart';
import 'format.dart';
import 'theme.dart';

/// Same Display API profile snapshot used by the Web home.
class HomeTikTokProfile extends StatelessWidget {
  const HomeTikTokProfile({super.key, required this.profile});

  final JsonMap? profile;

  @override
  Widget build(BuildContext context) {
    final data = JsonDto(profile ?? const {});
    final username = data.text('username');
    final followers = data.integer('seguidores');
    final weeklyChange = data.integer('seguidores_cambio_7d');
    final title = Theme.of(context).textTheme.titleSmall;
    final muted = TextStyle(color: context.corte.muted);
    final changeText = switch (weeklyChange) {
      null => 'Variación semanal no disponible',
      > 0 => '+${integer(weeklyChange)} en 7 días',
      < 0 => '−${integer(weeklyChange.abs())} en 7 días',
      _ => '0 en 7 días',
    };
    return Container(
      padding: const EdgeInsets.only(bottom: 16),
      margin: const EdgeInsets.only(bottom: 20),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.people_outline_rounded, color: context.corte.cyanInk),
          const SizedBox(width: 12),
          Expanded(
            child: Wrap(
              spacing: 12,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                if (username != null && username.isNotEmpty)
                  Text(
                    '@${username.replaceFirst(RegExp(r'^@'), '')}',
                    style: title,
                  ),
                if (followers != null && followers >= 0) ...[
                  Text(
                    '${integer(followers)} ${followers == 1 ? 'seguidor' : 'seguidores'} en TikTok',
                    style: title,
                  ),
                  Text(changeText, style: muted),
                ] else
                  Text('Seguidores de TikTok no disponibles', style: muted),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
