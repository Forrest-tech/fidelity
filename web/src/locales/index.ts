import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import zh from "./zh.json";

export const LANGS = ["en", "zh"] as const;
export type Lang = (typeof LANGS)[number];
// Same storage key as the legacy review screen so both stay in step.
export const LANG_KEY = "fidelity.lang";

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en }, zh: { translation: zh } },
    fallbackLng: "en",
    supportedLngs: [...LANGS],
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: { order: ["localStorage", "navigator"], lookupLocalStorage: LANG_KEY, caches: ["localStorage"] },
  });

i18n.on("languageChanged", (l) => {
  document.documentElement.lang = l.startsWith("zh") ? "zh-CN" : "en";
});

export default i18n;
