// Tiny argv parser. Supports --key value and --flag (boolean).
// No shell interpolation anywhere in the harness; this only reads process.argv.

export function parseArgs(argv = process.argv.slice(2)) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) {
        out[key] = true;
      } else {
        out[key] = next;
        i++;
      }
    } else {
      out._.push(a);
    }
  }
  return out;
}

/** Split a command string like "podman restart omg" into array args (no shell). */
export function splitCmd(cmd) {
  if (!cmd) return [];
  return cmd.trim().split(/\s+/).filter(Boolean);
}
