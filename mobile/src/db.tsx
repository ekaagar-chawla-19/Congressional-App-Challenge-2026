import { SQLiteProvider, useSQLiteContext, type SQLiteDatabase } from 'expo-sqlite';
import { createContext, useContext, type PropsWithChildren } from 'react';
import { Platform } from 'react-native';

// The phone's own database (offline demo, saved scans). In a browser it needs a secure page
// (https or localhost): opened from a phone over the Wi-Fi address (http://192.168.x.x:8081) it is
// not available, and the app runs signed in to the server only.
export const localDbAvailable = Platform.OS !== 'web' || globalThis.isSecureContext !== false;

const Db = createContext<SQLiteDatabase | null>(null);

// null when there is no local database; server-mode code never touches it.
export const useDb = () => useContext(Db) as SQLiteDatabase;

export function DbProvider({ children, onInit }: PropsWithChildren<{ onInit(db: SQLiteDatabase): Promise<void> }>) {
  if (!localDbAvailable) return <Db.Provider value={null}>{children}</Db.Provider>;
  return (
    <SQLiteProvider databaseName="hemlockid.db" onInit={onInit}>
      <Bridge>{children}</Bridge>
    </SQLiteProvider>
  );
}

function Bridge({ children }: PropsWithChildren) {
  return <Db.Provider value={useSQLiteContext()}>{children}</Db.Provider>;
}
