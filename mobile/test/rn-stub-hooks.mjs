// Node module hooks so app modules that import react-native / the key-value store can run under plain
// Node (with --experimental-strip-types): those two are replaced by tiny stand-ins, and extensionless
// relative imports resolve to their .ts file like Metro does.
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const STUBS = {
  "react-native": "data:text/javascript,export const Platform = { OS: 'ios' }; export const NativeModules = {}; export const AppState = { currentState: 'active', addEventListener: () => ({ remove() {} }) };",
  kv: "data:text/javascript,const m = new Map(); export default { getItemSync: (k) => m.get(k) ?? null, setItemSync: (k, v) => void m.set(k, v), removeItemSync: (k) => void m.delete(k) };",
};

// Native-only Expo modules and React, for the data layer (src/data.ts) run against Node's SQLite.
const MORE = {
  "expo-file-system": "data:text/javascript,export class File { constructor(...a) { this.uri = a.map(String).join('/'); } async copy() {} async write() {} } export const Paths = { document: 'doc', cache: 'cache' };",
  "expo-router": "data:text/javascript,export const useFocusEffect = () => {};",
  "expo-constants": "data:text/javascript,export default { expoConfig: {} };",
  react: "data:text/javascript,export const useState = (v) => [v, () => {}]; export const useCallback = (f) => f; export const createContext = () => ({}); export const useContext = () => null;",
  "./db": "data:text/javascript,export const useDb = () => null; export const localDbAvailable = true;",
};

export async function resolve(spec, ctx, next) {
  if (spec === "react-native") return { url: STUBS["react-native"], shortCircuit: true };
  if (spec === "./kv") return { url: STUBS.kv, shortCircuit: true };
  if (spec in MORE && !ctx.parentURL?.includes("/node_modules/")) return { url: MORE[spec], shortCircuit: true }; // the app's imports only
  if (spec.startsWith(".") && !/\.[cm]?[jt]sx?$/.test(spec) && ctx.parentURL?.startsWith("file:")) {
    const url = new URL(spec + ".ts", ctx.parentURL);
    if (existsSync(fileURLToPath(url))) return { url: url.href, shortCircuit: true };
  }
  return next(spec, ctx);
}
