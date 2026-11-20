import 'package:flutter/material.dart';

import 'format.dart';
import 'theme.dart';

String studioCommissionAmount(Object? centavos) =>
    centavos == null ? '—' : '${money(centavos, decimals: true)} MXN';

class StudioEarningsBand extends StatelessWidget {
  const StudioEarningsBand({
    super.key,
    required this.label,
    required this.amount,
    required this.detail,
    this.breakdown,
    this.onPressed,
  });

  final String label, amount;
  final Widget detail;
  final Widget? breakdown;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => Material(
    color: CorteColors.chrome,
    clipBehavior: Clip.antiAlias,
    borderRadius: BorderRadius.circular(CorteRadius.panel),
    child: InkWell(
      onTap: onPressed,
      focusColor: CorteColors.cyan.withValues(alpha: .18),
      hoverColor: CorteColors.chromeInk.withValues(alpha: .06),
      child: LayoutBuilder(
        builder: (context, limits) {
          final wide = limits.maxWidth > 600;
          final scale =
              MediaQuery.textScalerOf(context).scale(CorteType.label) /
              CorteType.label;
          final prominentMark = wide && scale <= 1.5;
          final inset = wide ? CorteSpace.xl : CorteSpace.large;
          return Stack(
            children: [
              Positioned(
                right: wide ? -54 : -35,
                top: wide ? -40 : -18,
                child: ExcludeSemantics(
                  child: Opacity(
                    opacity: prominentMark ? .95 : .18,
                    child: Transform.scale(
                      scaleY: 1.6,
                      child: CorteMark(size: wide ? 280 : 130),
                    ),
                  ),
                ),
              ),
              Padding(
                padding: EdgeInsets.fromLTRB(
                  inset,
                  inset,
                  prominentMark ? 160 : inset,
                  inset,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Semantics(
                      header: true,
                      child: Text(
                        label,
                        style: Theme.of(context).textTheme.titleMedium
                            ?.copyWith(color: CorteColors.chromeInk),
                      ),
                    ),
                    const SizedBox(height: CorteSpace.xs),
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: AlignmentDirectional.centerStart,
                      child: Text(
                        amount,
                        style: studioDisplay(
                          context,
                          size: wide ? 72 : 52,
                          color: CorteColors.chromeInk,
                        ),
                      ),
                    ),
                    const SizedBox(height: CorteSpace.small),
                    DefaultTextStyle.merge(
                      style: const TextStyle(color: CorteColors.chromeMuted),
                      child: detail,
                    ),
                    if (breakdown case final content?) ...[
                      const SizedBox(height: CorteSpace.large),
                      content,
                    ],
                  ],
                ),
              ),
            ],
          );
        },
      ),
    ),
  );
}
