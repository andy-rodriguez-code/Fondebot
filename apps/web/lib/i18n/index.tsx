"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, ReactNode } from "react";
import { en } from "./en";
import { es } from "./es";
import type { Dictionary } from "./en";

export type Lang = "en" | "es";

const dictionaries = { en, es };
const DEFAULT_LANG: Lang = "es";
const STORAGE_KEY = "openlivery.lang";

// Todas las rutas de clave con puntos válidas, derivadas de la forma del
// diccionario. Un error de tipeo en una llamada a t("…") se vuelve un error de
// TypeScript en vez de un fallback silencioso en tiempo de ejecución.
type DottedKeys<T, Prefix extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${Prefix}${K}` : DottedKeys<T[K], `${Prefix}${K}.`>;
}[keyof T & string];

export type I18nKey = DottedKeys<Dictionary>;

export type TranslateFn = (key: I18nKey, vars?: Record<string, string | number>) => string;

type LanguageContextValue = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: TranslateFn;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

// Búsqueda estricta: sin fallback silencioso. Una clave faltante es un bug que
// queremos que salga a la luz, no que se esconda. Las claves se verifican por
// tipo en tiempo de compilación, así que un fallo en ejecución solo puede
// significar que los diccionarios se desincronizaron: lanzamos para detectarlo
// en el momento.
function lookup(lang: Lang, key: string): string {
  let node: unknown = dictionaries[lang];
  for (const part of key.split(".")) {
    if (node && typeof node === "object" && part in (node as Record<string, unknown>)) {
      node = (node as Record<string, unknown>)[part];
    } else {
      throw new Error(`Missing i18n key "${key}" for language "${lang}"`);
    }
  }
  if (typeof node !== "string") {
    throw new Error(`i18n key "${key}" does not resolve to a string`);
  }
  return node;
}

function format(text: string, vars?: Record<string, string | number>): string {
  if (!vars) return text;
  let result = text;
  for (const [name, value] of Object.entries(vars)) {
    result = result.replace(new RegExp(`\\{${name}\\}`, "g"), String(value));
  }
  return result;
}

function readStoredLang(): Lang {
  if (typeof document === "undefined") return DEFAULT_LANG;
  const match = document.cookie.match(/(?:^|;\s*)openlivery\.lang=(en|es)/);
  if (match) return match[1] as Lang;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "es" || stored === "en" ? stored : DEFAULT_LANG;
}

// Traducción para código que no es un componente de React (el envoltorio de
// fetch, helpers sueltos), donde no se puede usar un hook. Lee la preferencia
// guardada en cada llamada; en el servidor cae al idioma por defecto.
export function translate(key: I18nKey, vars?: Record<string, string | number>): string {
  return format(lookup(readStoredLang(), key), vars);
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  // El SSR renderiza el idioma por defecto; la preferencia guardada se aplica
  // al montar, para evitar un desajuste de hidratación.
  const [lang, setLangState] = useState<Lang>(DEFAULT_LANG);

  useEffect(() => {
    const stored = readStoredLang();
    setLangState(stored);
    document.documentElement.lang = stored;
  }, []);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
    document.cookie = `openlivery.lang=${next}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.lang = next;
  }, []);

  const t = useCallback<TranslateFn>((key, vars) => format(lookup(lang, key), vars), [lang]);

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useLanguage must be used within LanguageProvider");
  return ctx;
}

// Hook de conveniencia para cuando solo hace falta la función de traducción.
export function useT(): TranslateFn {
  return useLanguage().t;
}
