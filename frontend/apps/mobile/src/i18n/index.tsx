import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getLocales } from "expo-localization";
import { kvGet, kvSet, type Db } from "../core/db";
import { en, type Dictionary, type Key } from "./en";
import { yo } from "./yo";

export type Language = "en" | "yo";
export const LANGUAGES: { code: Language; name: string }[] = [
  { code: "en", name: "English" },
  { code: "yo", name: "Yorùbá" },
];

const DICTIONARIES: Record<Language, Partial<Dictionary>> = { en, yo };

type Params = Record<string, string | number>;

/** Look a string up in `language`, falling back to English, then fill in `{values}`. */
export function translate(language: Language, key: Key, params?: Params): string {
  const template = DICTIONARIES[language][key] ?? en[key];
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

/** The language the phone is set to, when the app supports it. */
export function deviceLanguage(): Language {
  try {
    const code = getLocales()[0]?.languageCode;
    return code === "yo" ? "yo" : "en";
  } catch {
    return "en";
  }
}

interface I18n {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: Key, params?: Params) => string;
}

const I18nContext = createContext<I18n>({
  language: "en",
  setLanguage: () => undefined,
  t: (key, params) => translate("en", key, params),
});

/** The agent's choice is remembered on the phone; first launch follows the phone's language. */
export function I18nProvider({ db, children }: { db: Db | null; children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(deviceLanguage);

  useEffect(() => {
    if (!db) return;
    let alive = true;
    void kvGet(db, "language").then((stored) => {
      if (alive && (stored === "en" || stored === "yo")) setLanguageState(stored);
    });
    return () => {
      alive = false;
    };
  }, [db]);

  const setLanguage = useCallback(
    (next: Language) => {
      setLanguageState(next);
      if (db) void kvSet(db, "language", next);
    },
    [db],
  );

  const value = useMemo<I18n>(
    () => ({ language, setLanguage, t: (key, params) => translate(language, key, params) }),
    [language, setLanguage],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export const useI18n = (): I18n => useContext(I18nContext);
export const useT = (): I18n["t"] => useContext(I18nContext).t;
