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
            // the tenth design's tokens (design.css), so antd widgets match the custom components
            fontFamily: '"IBM Plex Sans", "Noto Sans SC", system-ui, -apple-system, "Segoe UI", sans-serif',
            fontFamilyCode: '"IBM Plex Mono", ui-monospace, Consolas, monospace',
            fontSize: 13,
            controlHeight: 30,
            borderRadius: 6,
            borderRadiusLG: 10,
            borderRadiusSM: 4,
            ...(dark
              ? {
                  colorPrimary: "#7aa2ff",
                  colorTextLightSolid: "#0f1115", // text on the light dark-mode accent (7:1)
                  colorBgLayout: "#0f1115",
                  colorBgContainer: "#171a21",
                  colorBgElevated: "#1d2129",
                  colorFillAlter: "#12151b",
                  colorBorder: "#2a2f3a",
                  colorBorderSecondary: "#2a2f3a",
                  colorSplit: "#2a2f3a",
                  colorText: "#e8eaee",
                  colorTextSecondary: "#9aa2b1",
                  colorTextTertiary: "#9aa2b1",
                  colorTextDescription: "#9aa2b1",
                  colorTextPlaceholder: "#8a93a3",
                  colorLink: "#7aa2ff",
                  colorLinkHover: "#a6c0ff",
                  colorLinkActive: "#7aa2ff",
                  colorSuccess: "#5fd08a",
                  colorWarning: "#f2b84b",
                  colorError: "#ff8a80",
                  colorInfo: "#6bb6ff",
                }
              : {
                  colorPrimary: "#1d4ed8",
                  colorBgLayout: "#f3f4f6",
                  colorBgContainer: "#ffffff",
                  colorFillAlter: "#f7f8fa",
                  colorBorder: "#dfe2e8",
                  colorBorderSecondary: "#dfe2e8",
                  colorSplit: "#dfe2e8",
                  colorText: "#16181d",
                  colorTextSecondary: "#5b6270",
                  colorTextTertiary: "#5b6270",
                  colorTextDescription: "#5b6270",
                  colorTextPlaceholder: "#6b7280", // 4.8:1 on white
                  colorLink: "#1d4ed8",
                  colorSuccess: "#13703a",
                  colorSuccessBg: "#e3f5ea",
                  colorSuccessBorder: "#a9dcbc",
                  colorWarning: "#8a5300",
                  colorWarningBg: "#fff2d6",
                  colorWarningBorder: "#f1cf8a",
                  colorError: "#b42318",
                  colorErrorBg: "#fde8e6",
                  colorErrorBorder: "#f4b9b2",
                  colorInfo: "#0b5cad",
                  colorInfoBg: "#e1f0fd",
                  colorInfoBorder: "#a9cdf2",
                }),
          },
          components: {
            Table: { headerBg: dark ? "#12151b" : "#f7f8fa", headerColor: dark ? "#9aa2b1" : "#5b6270", cellPaddingBlockSM: 8, headerSplitColor: "transparent" },
            Modal: { borderRadiusLG: 12 },
            Drawer: { colorBgElevated: dark ? "#171a21" : "#ffffff" },
          },
        }}
      >
        {children}
      </ConfigProvider>
    </Ctx.Provider>
  );
}
