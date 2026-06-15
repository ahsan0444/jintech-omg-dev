// Registry resolution for the Agent OS verify harness.
// Resolves AGENT_OS_HOME + config.yml, then loads a repo's env/auth/feature data.
// Pure data access — no network, no logging of secrets.

import { readFileSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import yaml from 'js-yaml';

/** Expand a leading ~ to the user's home directory (cross-platform). */
export function expandUser(p) {
  if (!p) return p;
  if (p === '~') return homedir();
  if (p.startsWith('~/') || p.startsWith('~\\')) {
    return path.join(homedir(), p.slice(2));
  }
  return p;
}

/** Resolve AGENT_OS_HOME (env, default ~/.agent-os). */
export function agentOsHome() {
  const raw = process.env.AGENT_OS_HOME && process.env.AGENT_OS_HOME.trim()
    ? process.env.AGENT_OS_HOME.trim()
    : path.join(homedir(), '.agent-os');
  return path.resolve(expandUser(raw));
}

/** Read + parse the top-level config.yml. */
export function loadConfig() {
  const home = agentOsHome();
  const cfgPath = path.join(home, 'config.yml');
  if (!existsSync(cfgPath)) {
    throw new Error(`config.yml not found at ${cfgPath} (AGENT_OS_HOME=${home})`);
  }
  const cfg = yaml.load(readFileSync(cfgPath, 'utf8')) || {};
  cfg.__home = home;
  return cfg;
}

/**
 * Parse a KEY=VALUE env file. Ignores blank lines and # comments.
 * Trailing inline comments are NOT stripped (values may contain #), per registry format.
 */
export function parseEnvFile(text) {
  const out = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let val = line.slice(eq + 1).trim();
    // Strip matching surrounding quotes if present.
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (key) out[key] = val;
  }
  return out;
}

function loadYamlIfExists(p) {
  if (!existsSync(p)) return null;
  return yaml.load(readFileSync(p, 'utf8')) || {};
}

/**
 * Load a repo by name.
 * Returns { name, repoRoot, dbRepoRoot, dataDir, env, auth, authStateFile, feature(name) }.
 */
export function loadRepo(name) {
  const cfg = loadConfig();
  const repos = Array.isArray(cfg.repos) ? cfg.repos : [];
  const entry = repos.find((r) => r && r.name === name);
  if (!entry) {
    throw new Error(`repo "${name}" not found in config.yml`);
  }

  const home = cfg.__home;
  const dataDir = path.resolve(home, entry.data || name);
  const repoRoot = entry.repo_root ? path.resolve(expandUser(entry.repo_root)) : null;
  const dbRepoRoot = entry.db_repo_root ? path.resolve(expandUser(entry.db_repo_root)) : null;

  const registryDir = path.join(dataDir, 'registry');

  // env (non-secret) + .env.local (secrets) — later overrides earlier.
  let env = {};
  const envPath = path.join(registryDir, 'env');
  if (existsSync(envPath)) {
    env = { ...env, ...parseEnvFile(readFileSync(envPath, 'utf8')) };
  }
  const envLocalPath = path.join(registryDir, '.env.local');
  if (existsSync(envLocalPath)) {
    env = { ...env, ...parseEnvFile(readFileSync(envLocalPath, 'utf8')) };
  }

  const auth = loadYamlIfExists(path.join(registryDir, 'auth.yml')) || {};

  // AUTH_STATE_FILE is relative to the data dir.
  const authStateRel = env.AUTH_STATE_FILE
    || (auth.storage_state && auth.storage_state.file)
    || '.auth/state.json';
  const authStateFile = path.resolve(dataDir, expandUser(authStateRel));

  function feature(featureName) {
    const fp = path.join(registryDir, 'features', `${featureName}.yml`);
    const data = loadYamlIfExists(fp);
    if (!data) {
      throw new Error(`feature "${featureName}" not found at ${fp}`);
    }
    return data;
  }

  return {
    name,
    repoRoot,
    dbRepoRoot,
    dataDir,
    registryDir,
    env,
    auth,
    authStateFile,
    feature,
  };
}

/** Directory where result + screenshot evidence is written. */
export function outDir(repo) {
  return path.join(repo.dataDir, '.verify', 'out');
}
