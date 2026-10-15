import { makeStyles } from '@material-ui/core';
import { createFrontendModule } from '@backstage/frontend-plugin-api';
import { ThemeBlueprint } from '@backstage/plugin-app-react';
import {
  UnifiedThemeProvider,
  createUnifiedTheme,
  genPageTheme,
  palettes,
  shapes,
} from '@backstage/theme';
import { otternet } from './brand';

/**
 * Waves everywhere: it is the shape in the logo, and it is the one page shape
 * that does not fight a mark made of water.
 */
const pages = (colors: string[]) => {
  const wave = genPageTheme({ colors, shape: shapes.wave });
  const wave2 = genPageTheme({ colors, shape: shapes.wave2 });

  // Every page kind Backstage asks for, so nothing falls back to the stock
  // purple. The two shapes alternate purely so neighbouring pages differ.
  return {
    home: wave,
    documentation: wave2,
    tool: wave,
    service: wave,
    website: wave2,
    library: wave2,
    other: wave,
    app: wave,
    apis: wave2,
    card: wave,
  };
};

/**
 * Two roles the panels need that the brand deliberately does not cover:
 * addresses and places. A graph in which every node is a shade of teal cannot
 * be read.
 */
const ADDRESS = '#b06a34';
const PLACE = '#2f7d5b';

/** The dark theme's canvas, wanted by both the palette and the body rule. */
const DARK_CANVAS = '#0f1e28';

/**
 * `body` keeps Backstage's own grey whatever the palette says, which left a
 * grey canvas beside the navy sidebar. Nothing in the cascade matches `body`
 * -- verified with a walk of every stylesheet -- so a plain rule wins, and
 * `@global` is how JSS emits one. `palette.background.default` is not enough;
 * neither is a `MuiCssBaseline` override, which produces no CSS at all here.
 */
function bodyPainter(colour: string) {
  const useCanvas = makeStyles({
    '@global': { body: { backgroundColor: colour } },
  });

  return function Canvas() {
    useCanvas();
    return null;
  };
}

const banner = {
  info: otternet.tealInk,
  error: '#E22134',
  text: '#FFFFFF',
  link: '#FFFFFF',
  closeButtonColor: '#FFFFFF',
  warning: '#FF9800',
};

const light = createUnifiedTheme({
  palette: {
    ...palettes.light,
    // The Infrahub panels take their colours from these roles rather than
    // hardcoding any -- see the plugin's useKindColours -- so filling them in
    // is what puts the brand on a rack elevation and a trace graph.
    primary: { main: otternet.tealInk },
    secondary: { main: PLACE },
    info: { main: otternet.tealInk },
    success: { main: otternet.mint },
    warning: { main: ADDRESS },
    link: otternet.tealInk,
    linkHover: otternet.teal,
    banner,
    navigation: {
      ...palettes.light.navigation,
      background: otternet.navyDeep,
      indicator: otternet.mint,
      selectedColor: '#FFFFFF',
      navItem: { hoverBackground: otternet.navy },
      submenu: { background: otternet.navy },
    },
    tabbar: { indicator: otternet.teal },
  },
  pageTheme: pages([otternet.navy, otternet.teal]),
});

const LightCanvas = bodyPainter(palettes.light.background.default);

const dark = createUnifiedTheme({
  palette: {
    ...palettes.dark,
    // Navy rather than grey: the sidebar is already navy, and a grey canvas
    // beside it reads as two different products.
    background: { default: DARK_CANVAS, paper: '#162935' },
    primary: { main: otternet.cyan, dark: otternet.teal },
    secondary: { main: PLACE },
    info: { main: otternet.teal },
    success: { main: otternet.mint },
    warning: { main: ADDRESS },
    link: otternet.cyan,
    linkHover: otternet.mint,
    banner,
    navigation: {
      ...palettes.dark.navigation,
      background: otternet.navyDeep,
      indicator: otternet.mint,
      selectedColor: '#FFFFFF',
      navItem: { hoverBackground: otternet.navy },
      submenu: { background: otternet.navy },
    },
    tabbar: { indicator: otternet.cyan },
  },
  pageTheme: pages([otternet.navyDeep, otternet.teal]),
});

const DarkCanvas = bodyPainter(DARK_CANVAS);

/**
 * The extension names must differ from the built-ins', because
 * `app-config.yaml` switches `theme:app/light` and `theme:app/dark` off and
 * that would disable these too. The *theme* ids stay 'light' and 'dark', so the
 * Settings page still offers just Light, Dark and Auto, and a stored choice
 * still resolves.
 */
export const themeModule = createFrontendModule({
  pluginId: 'app',
  extensions: [
    ThemeBlueprint.make({
      name: 'otternet-light',
      params: {
        theme: {
          id: 'light',
          title: 'Light',
          variant: 'light',
          Provider: ({ children }) => (
            <UnifiedThemeProvider theme={light}>
              <LightCanvas />
              {children}
            </UnifiedThemeProvider>
          ),
        },
      },
    }),
    ThemeBlueprint.make({
      name: 'otternet-dark',
      params: {
        theme: {
          id: 'dark',
          title: 'Dark',
          variant: 'dark',
          Provider: ({ children }) => (
            <UnifiedThemeProvider theme={dark}>
              <DarkCanvas />
              {children}
            </UnifiedThemeProvider>
          ),
        },
      },
    }),
  ],
});
