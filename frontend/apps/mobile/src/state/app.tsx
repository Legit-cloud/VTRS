import { ApiError, setRandomSource, type Endpoints, type Me, type MyAssignment } from "@vtrs/core";
import * as Crypto from "expo-crypto";
import { useNetworkState } from "expo-network";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AppState as RNAppState, Platform } from "react-native";
import { kvGet, kvSet, migrate, type Db } from "../core/db";
import { listOutbox, pendingCount, retryAll, type OutboxEntry } from "../core/outbox";
import { SyncEngine } from "../core/sync";
import { APP_VERSION } from "../platform/config";
import { fileUploader } from "../platform/files";
import { secure } from "../platform/secure";
import { onNotificationTap, onTokenChange, registerForPush } from "../platform/push";
import { openDb } from "../platform/sqlite";
import { anonymous, ep, session } from "./session";

// React Native has no crypto.getRandomValues; ids and idempotency keys need real randomness.
setRandomSource((n) => Crypto.getRandomBytes(n));

export type Boot = "starting" | "signed-out" | "signed-in";

export interface AppValue {
  boot: Boot;
  db: Db | null;
  ep: Endpoints;
  deviceId: string | null;
  me: Me | null;
  assignments: MyAssignment[] | null;
  assignmentsAt: number | null;
  refreshingAssignments: boolean;
  refreshAssignments: () => Promise<void>;
  online: boolean;
  outbox: OutboxEntry[];
  pending: number;
  syncing: boolean;
  syncNow: () => Promise<void>;
  retryFailed: () => Promise<void>;
  /** Call after queuing a result so it leaves the phone as soon as it can. */
  afterEnqueue: () => void;
  signIn: (identifier: string, password: string) => Promise<void>;
  acceptInvitation: (token: string) => Promise<{ challengeId: string; hint: string }>;
  completeInvitation: (args: {
    token: string;
    challengeId: string;
    code: string;
    password: string;
  }) => Promise<void>;
  signOut: () => Promise<void>;
}

const AppContext = createContext<AppValue | null>(null);

export function useApp(): AppValue {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp outside AppProvider");
  return value;
}

const SYNC_INTERVAL_MS = 60_000;

export function AppProvider({ children }: { children: ReactNode }) {
  const [boot, setBoot] = useState<Boot>("starting");
  const [db, setDb] = useState<Db | null>(null);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [assignments, setAssignments] = useState<MyAssignment[] | null>(null);
  const [assignmentsAt, setAssignmentsAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [outbox, setOutbox] = useState<OutboxEntry[]>([]);
  const [pending, setPending] = useState(0);
  const [syncing, setSyncing] = useState(false);

  const network = useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  useEffect(() => {
    session.online = online;
  }, [online]);

  // Touched only from effects and callbacks, never while rendering.
  const engine = useRef<SyncEngine | null>(null);
  const dbRef = useRef<Db | null>(null);

  const reloadLocal = useCallback(async () => {
    const database = dbRef.current;
    if (!database) return;
    setOutbox(await listOutbox(database));
    setPending(await pendingCount(database));
  }, []);

  const syncNow = useCallback(async () => {
    const e = engine.current;
    if (!e || !session.online || !session.refresh) return;
    setSyncing(true);
    try {
      // A 401 inside the pass has already tried one refresh; if that failed the session ended.
      const summary = await e.run();
      if (!summary.signedOut) await e.refreshReviews();
    } finally {
      setSyncing(false);
      await reloadLocal();
    }
  }, [reloadLocal]);

  const loadAssignments = useCallback(async (database: Db) => {
    const cached = await kvGet(database, "assignments");
    if (cached) {
      setAssignments(JSON.parse(cached) as MyAssignment[]);
      const at = await kvGet(database, "assignments_at");
      setAssignmentsAt(at ? Number(at) : null);
    }
    const cachedMe = await kvGet(database, "me");
    if (cachedMe) setMe(JSON.parse(cachedMe) as Me);
  }, []);

  const refreshAssignments = useCallback(async () => {
    const database = dbRef.current;
    if (!database || !session.online || !session.refresh) return;
    setRefreshing(true);
    try {
      const [profile, list] = await Promise.all([ep.me.get(), ep.me.assignments()]);
      const items = Array.isArray(list) ? list : list.results;
      setMe(profile);
      setAssignments(items);
      const now = Date.now();
      setAssignmentsAt(now);
      await kvSet(database, "me", JSON.stringify(profile));
      await kvSet(database, "assignments", JSON.stringify(items));
      await kvSet(database, "assignments_at", String(now));
    } catch {
      // Offline or not reachable: what is cached stays on screen.
    } finally {
      setRefreshing(false);
    }
  }, []);

  // ---- start-up --------------------------------------------------------------------------
  useEffect(() => {
    let alive = true;
    (async () => {
      const database = await openDb();
      await migrate(database);
      dbRef.current = database;
      engine.current = new SyncEngine({ db: database, ep, files: fileUploader });
      engine.current.subscribe(() => void reloadLocal());
      session.refresh = await secure.get("refresh");
      session.device = await secure.get("device");
      if (!alive) return;
      setDb(database);
      setDeviceId(session.device);
      await loadAssignments(database);
      await reloadLocal();
      setBoot(session.refresh && session.device ? "signed-in" : "signed-out");
    })().catch(() => setBoot("signed-out"));
    return () => {
      alive = false;
    };
  }, [loadAssignments, reloadLocal]);

  const endSession = useCallback(async () => {
    // The device id stays: the server bound this agent to this phone, and signing in again
    // needs it. Only the means of getting a new access token is removed.
    session.access = null;
    session.refresh = null;
    await secure.clear();
    setBoot("signed-out");
  }, []);

  // ---- sync triggers ---------------------------------------------------------------------
  useEffect(() => {
    if (boot !== "signed-in") return;
    if (online) {
      void (async () => {
        await refreshAssignments();
        await syncNow();
      })();
    }
  }, [boot, online, refreshAssignments, syncNow]);

  useEffect(() => {
    if (boot !== "signed-in") return;
    const subscription = RNAppState.addEventListener("change", (state) => {
      if (state === "active") void syncNow();
    });
    const timer = setInterval(() => void syncNow(), SYNC_INTERVAL_MS);
    return () => {
      subscription.remove();
      clearInterval(timer);
    };
  }, [boot, syncNow]);

  // ---- push ------------------------------------------------------------------------------
  const registered = useRef<string | null>(null);
  useEffect(() => {
    if (boot !== "signed-in" || !online) return;
    let alive = true;
    void (async () => {
      const database = dbRef.current;
      if (database && registered.current === null) {
        registered.current = await kvGet(database, "push_token");
      }
      const token = await registerForPush(ep, registered.current);
      if (alive && token && database) {
        registered.current = token;
        await kvSet(database, "push_token", token);
      }
    })();
    const stopRefresh = onTokenChange((token) => {
      void ep.me.registerPushToken(token).then(() => {
        registered.current = token;
      });
    });
    // A decision on a result is worth a look: bring the outbox up to date.
    const stopTap = onNotificationTap(() => void syncNow());
    return () => {
      alive = false;
      stopRefresh();
      stopTap();
    };
  }, [boot, online, syncNow]);

  // ---- actions ---------------------------------------------------------------------------
  const adopt = useCallback(
    async (pair: { access_token?: string; refresh_token?: string; device_id?: string | null }) => {
      if (!pair.access_token || !pair.refresh_token || !pair.device_id) {
        throw new ApiError({
          status: 0,
          code: "bad_response",
          detail: "The server did not finish setting up this phone. Try again.",
        });
      }
      session.access = pair.access_token;
      session.refresh = pair.refresh_token;
      session.device = pair.device_id;
      await secure.set("refresh", pair.refresh_token);
      await secure.set("device", pair.device_id);
      setDeviceId(pair.device_id);
      setBoot("signed-in");
    },
    [],
  );

  const signIn = useCallback(
    async (identifier: string, password: string) => {
      const pair = await anonymous.auth.login({
        identifier,
        password,
        client: "MOBILE",
        device_id: session.device,
      });
      await adopt(pair as never);
    },
    [adopt],
  );

  const acceptInvitation = useCallback(async (token: string) => {
    const challenge = await anonymous.auth.acceptInvitation(token);
    return { challengeId: challenge.challenge_id, hint: challenge.destination_hint ?? "" };
  }, []);

  const completeInvitation = useCallback(
    async (args: { token: string; challengeId: string; code: string; password: string }) => {
      const pair = await anonymous.auth.completeInvitation({
        token: args.token,
        challenge_id: args.challengeId,
        code: args.code,
        password: args.password,
        device: {
          platform: Platform.OS === "ios" ? "IOS" : "ANDROID",
          app_version: APP_VERSION,
          public_key: "",
          push_token: "",
        },
      });
      await adopt(pair as never);
    },
    [adopt],
  );

  useEffect(() => {
    session.onSignedOut = () => void endSession();
    return () => {
      session.onSignedOut = () => undefined;
    };
  }, [endSession]);

  const signOut = useCallback(async () => {
    try {
      await ep.auth.logout();
    } catch {
      // Offline sign-out still clears this phone.
    }
    await endSession();
  }, [endSession]);

  const retryFailed = useCallback(async () => {
    if (dbRef.current) await retryAll(dbRef.current);
    await syncNow();
  }, [syncNow]);

  const afterEnqueue = useCallback(() => {
    void reloadLocal().then(() => syncNow());
  }, [reloadLocal, syncNow]);

  const value: AppValue = {
    boot,
    db,
    ep,
    deviceId,
    me,
    assignments,
    assignmentsAt,
    refreshingAssignments: refreshing,
    refreshAssignments,
    online,
    outbox,
    pending,
    syncing,
    syncNow,
    retryFailed,
    afterEnqueue,
    signIn,
    acceptInvitation,
    completeInvitation,
    signOut,
  };
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
