'use client';

import {
  colorsTuple,
  createTheme,
  DEFAULT_THEME,
  MantineProvider,
  mergeMantineTheme,
  virtualColor,
  type CSSVariablesResolver,
} from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { NavigationProgress } from '@mantine/nprogress';
import type React from 'react';

import '@mantine/charts/styles.css';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/dropzone/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/nprogress/styles.css';
import '@mantine/spotlight/styles.css';

const cssResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    // New Colors
    '--mantine-sidebar-bg': 'linear-gradient(0deg, rgba(0,0,0,0.04), rgba(0,0,0,0.04)), linear-gradient(0deg, rgba(255,255,255,0.01), rgba(255,255,255,0.01))',
    '--mantine-sidebar-mobile-bg': '#F8F8F6',
    '--mantine-color-bw': '#000000',
    '--mantine-color-navlink-bg': '#FAF9F5',
    // Backgrounds
    '--mantine-color-bg-primary': '#F8F8F6',
    '--mantine-color-bg-secondary': '#F3F3F3',
    '--mantine-color-campaign-bg': '#FFFFFF',
    '--mantine-color-campaign-status': '#FFFFFF',

    // Dividers
    '--mantine-color-divider': '#B5B5B5',
    '--mantine-color-underline': '#8D8D8D',
    '--mantine-color-profile-stroke': '#ACACAC',

    // chat block
    '--mantine-color-user-block': '#15151505',
    '--mantine-chat-input-icon-shadow': '0px 1.5px 0px 0px #FFFFFF59 inset, 0px 2px 6px 0px #00000033',
    '--mantine-chat-input-shadow': '0px 15px 26px 0px #1D1D1D26, 0px 2px 2px 0px #FFFFFFB2 inset, 1px -1px 2px 0px #FFFFFF80 inset',
    '--mantine-new-chat-input-shadow': '0px 2px 2px 0px #FFFFFFB2 inset, 1px -1px 2px 0px #FFFFFF80 inset, 0px 15px 10.8px 0px #1D1D1D12',
    '--mantine-new-chat-input-chip-shadow': '0px 2px 2px 0px #FFFFFFB2 inset, 1px -1px 40px 0px #FFFFFF80 inset, 0px 6px 10.8px 0px #1D1D1D12',

    // Texts
    '--mantine-color-text-primary': '#151515',
    '--mantine-color-text-secondary': '#62646A',

    // Widgets
    '--mantine-color-widget-primary': '#FFFFFF10',
    '--mantine-color-widget-inner-glass-bg': '#FFFFFF80',
    '--mantine-color-header-icon': '#ECEDEE',
    '--mantine-color-widget-secondary': '#F3F3F3',
    '--mantine-color-widget-stroke': '#FFFFFFE5',
    '--mantine-color-tab-bg': '#F3F3F3',
    '--mantine-widget-shadow': '0px 15px 26px 0px #1D1D1D14, 0px 2px 2px 0px #FFFFFFB2 inset, 1px -1px 2px 0px #FFFFFF80 inset',

    // Buttons
    '--mantine-color-button-primary': '#151515',
    '--mantine-color-button-primary-hover': '#00000008',
    '--mantine-color-button-secondary': '#FFFFFF',
    '--mantine-color-button-stroke': '#DBDBDB',
    '--mantine-color-button-disabled': '#FFFFFF30',
    '--mantine-color-plus-minus-button-bg': '#00000014',
    '--mantine-color-plus-minus-button-border': '#0000001F',
    '--mantine-color-plus-minus-button-hover': '#0000000D',
    '--mantine-color-plus-minus-button-shadow': '0px 15px 26px 0px #1D1D1D14, 0px 2px 2px 0px #FFFFFFB2 inset, 1px -1px 2px 0px #FFFFFF80 inset',
    '--mantine-color-info-shadow': '0px 4px 16px 0px #0000004D, 0px -1px 0px 0px #0000004D inset, 0px 1px 0px 0px #FFFFFF14 inset',
  },
  dark: {
    // New Colors
    '--mantine-sidebar-bg': 'rgba(255, 255, 255, 0.01)',
    '--mantine-sidebar-mobile-bg': 'rgba(255, 255, 255, 0.01)',
    '--mantine-color-bw': '#FFFFFF',
    '--mantine-color-navlink-bg': '#0000004F',
    // Backgrounds
    '--mantine-color-bg-primary': '#30302E',
    '--mantine-color-bg-secondary': '#3D3D3A',
    '--mantine-color-campaign-bg': '#151517',
    '--mantine-color-campaign-status': '#1E2B22',

    // Dividers
    '--mantine-color-divider': '#50504C',
    '--mantine-color-underline': '#8D8D8D',
    '--mantine-color-profile-stroke': '#2E2F33',

    // Texts
    '--mantine-color-text-primary': '#FAF9F5',
    '--mantine-color-text-secondary': '#E8E6DC',

    // chat block
    '--mantine-color-user-block': '#2D2D2D1A',
    '--mantine-chat-input-icon-shadow': '0px 1.5px 0px 0px #FFFFFF59 inset, 0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059',
    '--mantine-chat-input-shadow': '0px 8px 24px 0px #00000080, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
    '--mantine-new-chat-input-shadow': '0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset, 0px 8px 24px 0px #00000080',
    '--mantine-new-chat-input-chip-shadow': '0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset, 0px 8px 24px 0px #00000080',

    // Widgets
    '--mantine-color-widget-primary': '#FFFFFF03',
    '--mantine-color-widget-inner-glass-bg': '#0000004D',
    '--mantine-color-widget-secondary': '#30302E',
    '--mantine-color-header-icon': '#7B7B7B',
    '--mantine-color-widget-stroke': 'transparent',
    '--mantine-color-tab-bg': '#151517',
    '--mantine-widget-shadow': '0px 8px 24px 0px #00000080, 0px 0px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',

    // Buttons
    '--mantine-color-button-primary': '#272727',
    '--mantine-color-button-primary-hover': '#FFFFFF08',
    '--mantine-color-button-secondary': '#454545',
    '--mantine-color-button-stroke': 'transparent',
    '--mantine-color-button-disabled': '#FFFFFF0D',
    '--mantine-color-plus-minus-button-bg': '#FFFFFF14',
    '--mantine-color-plus-minus-button-border': '#FFFFFF1F',
    '--mantine-color-plus-minus-button-hover': '#FFFFFF0D',
    '--mantine-color-plus-minus-button-shadow': '0px 2px 6px 0px #00000033,0px 8px 32px 0px #00000059,0px 1.5px 0px 0px #FFFFFF59 inset',
    '--mantine-color-info-shadow': '0px 8px 24px 0px #00000080, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
  },
});

const MantineUIProvider = ({ children }: { children: React.ReactNode }) => {
  const themeOverride = createTheme({
    black: '#151515',
    white: '#EAEAEA',
    colors: {
      primaryLight: colorsTuple('#151515'),
      primaryDark: colorsTuple('#272727'),
      primary: virtualColor({
        name: 'primary',
        dark: 'primaryDark',
        light: 'primaryLight',
      }),
    },
    breakpoints: {
      xs: '30em',
      sm: '40em',
      md: '48em',
      lg: '64em',
      xl: '80em',
      xxl: '90em',
    },
    primaryColor: 'primary',
  });

  const theme = mergeMantineTheme(DEFAULT_THEME, themeOverride);

  return (
    <>
      <MantineProvider
        theme={theme}
        defaultColorScheme='dark'
        cssVariablesResolver={cssResolver}
      >
        <ModalsProvider>
          <Notifications zIndex={99999999999999} position='top-right' />
          <NavigationProgress />
          {children}
        </ModalsProvider>
      </MantineProvider>
    </>
  );
};

export default MantineUIProvider;
