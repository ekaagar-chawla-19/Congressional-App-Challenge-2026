// Web: localStorage. expo-sqlite's synchronous API needs SharedArrayBuffer, which the dev server's
// page is not allowed to use (it would need COOP/COEP headers on the HTML).
const Storage = {
  getItemSync: (k: string) => globalThis.localStorage?.getItem(k) ?? null,
  setItemSync: (k: string, v: string) => globalThis.localStorage?.setItem(k, v),
  removeItemSync: (k: string) => globalThis.localStorage?.removeItem(k),
};
export default Storage;
