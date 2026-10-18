import Storage from './kv';
import { create } from 'zustand';

// Who is signed in and which forest they are working in.
// `server`: signed in to hemlock-api, which holds the trees and runs the model.
// `local`: the offline demo, with sample forests stored on this phone and a stand-in matcher.
export type Mode = 'server' | 'local';
export type User = { name: string; email: string };
export type ForestRef = { id: number; name: string; lat: number | null; lng: number | null };

type State = {
  mode: Mode;
  server: string;
  token: string | null;
  user: User | null;
  forest: ForestRef | null;
};

type Session = State & {
  signIn(s: Pick<State, 'mode' | 'server' | 'token' | 'user'>): void;
  setForest(f: ForestRef | null): void;
  signOut(): void;
};

const KEY = 'session';
const EMPTY: State = { mode: 'local', server: '', token: null, user: null, forest: null };

const load = (): State => {
  try {
    return { ...EMPTY, ...JSON.parse(Storage.getItemSync(KEY) ?? '{}') };
  } catch {
    return EMPTY;
  }
};

export const useSession = create<Session>((set, get) => {
  const save = (s: Partial<State>) => {
    set(s);
    const { mode, server, token, user, forest } = get();
    Storage.setItemSync(KEY, JSON.stringify({ mode, server, token, user, forest }));
  };
  return {
    ...load(),
    signIn: (s) => save({ ...s, forest: null }),
    setForest: (forest) => save({ forest }),
    signOut: () => save({ token: null, user: null, forest: null }),
  };
});

export const isServer = () => useSession.getState().mode === 'server';

// Forest names from the server end in "(demo)" for the seeded account; drop it in headers.
export const shortName = (name: string) => name.replace(/\s*\(demo\)\s*$/i, '');
