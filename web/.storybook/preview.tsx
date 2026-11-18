import type { Preview } from "@storybook/react";
import i18n from "../src/locales";
import "../src/index.css";

// Toolbar switches for language and theme so every component can be seen in each.
const preview: Preview = {
  globalTypes: {
    locale: { description: "Language", defaultValue: "en", toolbar: { icon: "globe", items: ["en", "zh"] } },
    theme: { description: "Theme", defaultValue: "light", toolbar: { icon: "mirror", items: ["light", "dark"] } },
  },
  decorators: [
    (Story, ctx) => {
      void i18n.changeLanguage(ctx.globals.locale);
      document.documentElement.dataset.theme = ctx.globals.theme;
      return (
        <div className="bg-bg p-6 text-fg">
          <Story />
        </div>
      );
    },
  ],
  parameters: { a11y: { test: "error" } },
};
export default preview;
