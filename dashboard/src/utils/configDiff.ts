/**
 * Diff two config snapshots down to only the leaves that actually changed.
 *
 * Both SystemSettingsPage and AgentConfigPage used to send their ENTIRE
 * local config copy as the PUT /api/config `updates` payload. Since
 * `save_user_config()` deep-merges `updates` onto whatever's currently
 * stored, sending a full (possibly stale) snapshot means every field the
 * user *didn't* touch on that page still gets re-written with whatever
 * value that page happened to load — silently reverting any change made
 * concurrently via the other config page, another browser tab, or the
 * balance-sync job. Sending only the real diff makes that impossible:
 * fields nobody touched on this page are never part of `updates` at all.
 */
export function diffConfig(
  baseline: Record<string, any> | undefined | null,
  current: Record<string, any> | undefined | null,
): Record<string, any> {
  const diff: Record<string, any> = {};
  const base = baseline ?? {};
  const cur = current ?? {};
  const keys = new Set([...Object.keys(base), ...Object.keys(cur)]);

  for (const key of keys) {
    const a = base[key];
    const b = cur[key];
    if (a === b) continue;

    const bothPlainObjects =
      a && b &&
      typeof a === 'object' && typeof b === 'object' &&
      !Array.isArray(a) && !Array.isArray(b);

    if (bothPlainObjects) {
      const nested = diffConfig(a, b);
      if (Object.keys(nested).length > 0) diff[key] = nested;
    } else if (JSON.stringify(a) !== JSON.stringify(b)) {
      // Primitive, array, or a type change (e.g. undefined -> object) —
      // arrays (like scheduler.watchlist) are compared/replaced whole,
      // which is the right granularity for a list field.
      diff[key] = b;
    }
  }

  return diff;
}
