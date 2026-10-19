/**
 * Tokenized Theme & Color Palette for Anti-AI-Slop Remotion Compositions.
 *
 * Implements strict design guidelines:
 * - Zero gradients, blurs, glow, shadows, or backdrop filters.
 * - Flat matte plates and high-contrast typography.
 * - Single accent color per palette preset.
 */

export const C = {
  bg: '#0F1115', // Canvas background
  surface: '#171A21', // Cards, terminal window, panels
  surfaceAlt: '#1F242E', // Secondary containers
  line: '#262B35', // 2px solid borders & dividers
  text: '#E8EAED', // Primary high-contrast text
  muted: '#8B93A1', // Secondary text, comments, prompts
  accent: '#3DDC97', // The single accent: ticks, active flags, key words
  danger: '#F2685B', // Pain points, danger cross marks
  paper: '#F4F5F7', // Inverted flash frames & impact cuts
} as const;

export const THEMES = {
  developer: {
    plate: C.bg,
    ink: C.text,
    accent: C.accent,
    surface: C.surface,
    line: C.line,
    muted: C.muted,
    danger: C.danger,
    paper: C.paper,
  },
  ink: {
    plate: '#111111',
    ink: '#F5F2EA',
    accent: '#FF5A1F',
    surface: '#1A1A1A',
    line: '#2E2E2E',
    muted: '#9E9E9E',
    danger: '#F2685B',
    paper: '#F5F2EA',
  },
  paper: {
    plate: '#F4F1EA',
    ink: '#141414',
    accent: '#0B3D91',
    surface: '#EAE6DC',
    line: '#D2CDC1',
    muted: '#666666',
    danger: '#D93829',
    paper: '#FFFFFF',
  },
  signal: {
    plate: '#0B3D91',
    ink: '#FFFFFF',
    accent: '#FFD400',
    surface: '#0F47A6',
    line: '#1A5AC7',
    muted: '#B0C8F5',
    danger: '#FF5C4D',
    paper: '#FFFFFF',
  },
} as const;

export type ThemeName = keyof typeof THEMES;

export const FONTS = {
  sans: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  mono: '"JetBrains Mono", "Courier New", monospace',
} as const;

export const SPRINGS = {
  rigid: { damping: 200, mass: 1, stiffness: 100 },
  snappy: { damping: 150, mass: 0.8, stiffness: 120 },
} as const;
