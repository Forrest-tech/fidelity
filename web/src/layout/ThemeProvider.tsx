import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ConfigProvider, theme as antTheme } from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";

const THEME_KEY = "fidelity.theme";
export type Theme = "system" | "light" | "dark";

function isDark(t: Theme) {
  return t === "dark" || (t === "system" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches);
}

function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = isDark(t) ? "dark" : "light";
}

interface ThemeCtx {
  theme: Theme;
  setTheme: (t: Theme) => void;
  dark: boolean;
}

const Ctx = createContext<ThemeCtx>({ theme: "system", setTheme: () => {}, dark: false });

/** The theme choice (system / light / dark), kept in step with the page and with Ant Design. */
export const useTheme = () => useContext(Ctx);

/** Wraps the whole app, so the sign-in page follows the theme and language too. */
export function ThemeProvider({ children, force }: { children: ReactNode; force?: "light" | "dark" }) {
  const { i18n } = useTranslation();
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem(THEME_KEY) as Theme) || "system";
    } catch {
      return "system";
    }
  });
  const eff: Theme = force ?? theme; // `force` is for Storybook, which picks the theme from its toolbar
  const [dark, setDark] = useState(() => isDark(eff));
  useEffect(() => {
    applyTheme(eff);
    setDark(isDark(eff));
    if (!force) {
      try {
        localStorage.setItem(THEME_KEY, theme);
      } catch {
        /* storage unavailable: the theme still applies for this session */
      }
    }
    if (eff !== "system" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => {
      applyTheme("system");
      setDark(mq.matches);
    };
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [eff, theme, force]);

  const value = useMemo(() => ({ theme: eff, setTheme, dark }), [eff, dark]);
  const zh = i18n.language.startsWith("zh");
  return (
    <Ctx.Provider value={value}>
      <ConfigProvider
        locale={zh ? zhCN : enUS}
        theme={{
          algorithm: dark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
          token: {
            colorPrimary: "#1d4ed8",
            borderRadius: 6,
            fontFamily: "inherit",
            // Colours chosen to meet WCAG AA (4.5:1) on both surfaces; antd's defaults are too light for text and tags.
            ...(dark
              ? {
                  // the dark algorithm darkens the blue; links and the selected menu item need a lighter one
                  colorLink: "#8fb0ff",
                  colorLinkHover: "#b3c8ff",
                  colorLinkActive: "#8fb0ff",
                  colorTextSecondary: "rgba(255,255,255,0.72)",
                  colorTextTertiary: "rgba(255,255,255,0.72)",
                  colorTextDescription: "rgba(255,255,255,0.72)",
                  colorTextPlaceholder: "rgba(255,255,255,0.6)", // placeholders must reach 4.5:1 too
                  colorError: "#ff7875",
                  colorInfo: "#69b1ff", // "running" tags and info alerts
                }
              : {
                  colorTextSecondary: "#595959",
                  colorTextTertiary: "#595959",
                  colorTextDescription: "#595959",
                  colorTextPlaceholder: "#737373", // antd's #bfbfbf is 1.8:1 on white; this is 4.7:1
                  // dark text colours, with the pale backgrounds pinned (antd would otherwise derive muddy ones from them)
                  colorSuccess: "#237804",
                  colorSuccessBg: "#f6ffed",
                  colorSuccessBorder: "#b7eb8f",
                  colorError: "#cf1322",
                  colorErrorBg: "#fff2f0",
                  colorErrorBorder: "#ffccc7",
                  colorWarning: "#8a5300", // small tag text on the pale background needs this to reach 4.5:1
                  colorWarningBg: "#fffbe6",
                  colorWarningBorder: "#ffe58f",
                  colorInfo: "#0958d9",
                  colorInfoBg: "#e6f4ff",
                  colorInfoBorder: "#91caff",
                }),
          },
          components: dark
            ? {
                Menu: { itemSelectedColor: "#8fb0ff", horizontalItemSelectedColor: "#8fb0ff", itemHoverColor: "#b3c8ff", horizontalItemHoverColor: "#b3c8ff" },
                Tabs: { itemSelectedColor: "#8fb0ff", itemActiveColor: "#8fb0ff", itemHoverColor: "#b3c8ff", inkBarColor: "#8fb0ff" },
              }
            : {},
        }}
      >
        {children}
      </ConfigProvider>
    </Ctx.Provider>
  );
}
