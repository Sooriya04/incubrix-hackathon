/**
 * Aspect Ratio System for Flat Plate Remotion.
 *
 * All four ratios share 1080 as the short side (1080p class, 30 fps).
 * Provides safe zones, margin boundaries, and ratio-specific typography scales.
 */

export const RATIOS = {
  '16:9': {
    id: 'Broll-16x9',
    w: 1920,
    h: 1080,
    margin: 96,
    captionSize: 44,
    captionMaxW: 0.72,
    captionBottom: 0.10,
    lines: 2,
    titleSize: 72,
    codeSize: 28,
  },
  '9:16': {
    id: 'Broll-9x16',
    w: 1080,
    h: 1920,
    margin: 72,
    captionSize: 52,
    captionMaxW: 0.86,
    captionBottom: 0.22, // Safe from platform UI bottom controls
    lines: 3,
    titleSize: 64,
    codeSize: 26,
  },
  '1:1': {
    id: 'Broll-1x1',
    w: 1080,
    h: 1080,
    margin: 72,
    captionSize: 46,
    captionMaxW: 0.84,
    captionBottom: 0.12,
    lines: 3,
    titleSize: 58,
    codeSize: 26,
  },
  '3:2': {
    id: 'Broll-3x2',
    w: 1620,
    h: 1080,
    margin: 88,
    captionSize: 44,
    captionMaxW: 0.76,
    captionBottom: 0.11,
    lines: 2,
    titleSize: 68,
    codeSize: 28,
  },
} as const;

export type RatioKey = keyof typeof RATIOS;
