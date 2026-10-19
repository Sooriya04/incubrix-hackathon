import React from 'react';
import {
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  Video,
} from 'remotion';
import { RATIOS, RatioKey } from './ratios';
import { FONTS, ThemeName, THEMES } from './theme';

export interface SceneData {
  id: number;
  name: string;
  title?: string;
  subtitle?: string;
  text?: string;
  voiceText?: string;
  startFrame: number;
  durationInFrames: number;
  startTimeSec?: number;
  durationSec?: number;
  visual_hint?: string | null;
  footageUrl?: string | null;
  audioFile?: string | null;
  clip?: {
    source_url?: string;
    source_provider?: string;
    attribution?: string;
  } | null;
}

export interface SegmentData {
  sceneId: number;
  text: string;
  start: number;
  end: number;
  startFrame: number;
  durationInFrames: number;
}

export interface WordData {
  word: string;
  start: number;
  end: number;
  startFrame: number;
  endFrame: number;
  sceneId: number;
}

export interface CaptionsPayload {
  fps: number;
  totalFrames: number;
  totalDurationSec?: number;
  scenes: SceneData[];
  segments?: SegmentData[];
  words?: WordData[];
}

export interface BrollVideoProps {
  ratio: RatioKey;
  themeName?: ThemeName;
  captions?: CaptionsPayload;
  audioSrc?: string;
}

/**
 * Neutral, explicit scene fallback renderer when footage is not assigned or available.
 * Complies with anti-AI-slop standard: no gradients, no fake b-roll, pure typography & geometry.
 */
const FallbackPlateScene: React.FC<{
  scene: SceneData;
  ratio: RatioKey;
  theme: (typeof THEMES)[ThemeName];
  cfg: (typeof RATIOS)[RatioKey];
}> = ({ scene, ratio, theme, cfg }) => {
  const isVertical = ratio === '9:16';
  const headline = scene.text || scene.voiceText || scene.title || `Scene ${scene.id}`;
  const sceneNum = scene.id < 10 ? `0${scene.id}` : `${scene.id}`;
  const badgeLabel = scene.title || `SCENE ${sceneNum}`;

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        backgroundColor: theme.plate,
        color: theme.ink,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: isVertical ? 'flex-start' : 'center',
        alignItems: 'center',
        padding: `${cfg.margin}px`,
        paddingTop: isVertical ? '220px' : `${cfg.margin}px`,
        position: 'relative',
        boxSizing: 'border-box',
      }}
    >
      {/* Perimeter boundary mark */}
      <div
        style={{
          position: 'absolute',
          top: `${cfg.margin / 2}px`,
          left: `${cfg.margin / 2}px`,
          right: `${cfg.margin / 2}px`,
          bottom: `${cfg.margin / 2}px`,
          border: `1px solid ${theme.line}`,
          pointerEvents: 'none',
        }}
      />

      {/* Dynamic scene badge */}
      <div
        style={{
          fontFamily: FONTS.mono,
          fontSize: '15px',
          color: theme.accent,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          marginBottom: '28px',
          padding: '6px 16px',
          border: `1px solid ${theme.line}`,
          backgroundColor: theme.surface,
          borderRadius: '4px',
          fontWeight: 600,
        }}
      >
        [SCENE {sceneNum} · {badgeLabel}]
      </div>

      {/* Main dynamic narration headline */}
      <div
        style={{
          fontFamily: FONTS.sans,
          fontSize: `${cfg.titleSize}px`,
          fontWeight: 700,
          lineHeight: 1.15,
          textAlign: 'center',
          maxWidth: '92%',
          color: theme.ink,
          marginBottom: '24px',
        }}
      >
        {headline}
      </div>

      {/* Semantic visual cue / hint */}
      {scene.visual_hint && scene.visual_hint !== headline && (
        <div
          style={{
            fontFamily: FONTS.mono,
            fontSize: '18px',
            color: theme.muted,
            textAlign: 'center',
            maxWidth: '80%',
            lineHeight: 1.4,
            padding: '10px 18px',
            backgroundColor: theme.surface,
            border: `1px solid ${theme.line}`,
            borderRadius: '6px',
          }}
        >
          // Cue: {scene.visual_hint}
        </div>
      )}
    </div>
  );
};


export const BrollVideo: React.FC<BrollVideoProps> = ({
  ratio = '16:9',
  themeName = 'developer',
  captions,
  audioSrc = 'voiceover.mp3',
}) => {
  const frame = useCurrentFrame();
  const cfg = RATIOS[ratio] || RATIOS['16:9'];
  const theme = THEMES[themeName] || THEMES.developer;

  const scenes = captions?.scenes || [];
  const segments = captions?.segments || [];
  const words = captions?.words || [];

  // Active segment for the current frame
  const activeSegment = segments.find(
    (seg) => frame >= seg.startFrame && frame < seg.startFrame + seg.durationInFrames
  );

  // Filter word-level timings belonging to the active segment (if reliable timestamps exist)
  const activeWords = activeSegment
    ? words.filter(
        (w) =>
          w.sceneId === activeSegment.sceneId &&
          w.startFrame >= activeSegment.startFrame &&
          w.endFrame <= activeSegment.startFrame + activeSegment.durationInFrames
      )
    : [];

  return (
    <div
      style={{
        width: `${cfg.w}px`,
        height: `${cfg.h}px`,
        backgroundColor: theme.plate,
        color: theme.ink,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <style>{`
        @font-face {
          font-family: 'Inter';
          src: url('${staticFile('fonts/Inter.ttf')}') format('truetype');
          font-weight: 400 700;
          font-style: normal;
          font-display: block;
        }
        @font-face {
          font-family: 'JetBrains Mono';
          src: url('${staticFile('fonts/JetBrainsMono.ttf')}') format('truetype');
          font-weight: 400 700;
          font-style: normal;
          font-display: block;
        }
        * {
          box-sizing: border-box;
          margin: 0;
          padding: 0;
          -webkit-font-smoothing: antialiased;
          -moz-osx-font-smoothing: grayscale;
        }
      `}</style>

      {/* Fallback global narration audio track if per-scene audio is not available */}
      {audioSrc && !scenes.some((s) => s.audioFile) && <Audio src={staticFile(audioSrc)} />}

      {/* Timed scene sequence layer */}
      {scenes.map((scene) => {
        const rawFootage = scene.footageUrl || scene.clip?.source_url;
        const footageSrc = rawFootage
          ? rawFootage.startsWith('http://') || rawFootage.startsWith('https://') || rawFootage.startsWith('/')
            ? rawFootage
            : staticFile(rawFootage)
          : null;

        return (
          <Sequence
            key={scene.id}
            from={scene.startFrame}
            durationInFrames={scene.durationInFrames}
            name={scene.name}
          >
            {/* Lockstep scene-synchronized narration audio */}
            {scene.audioFile && <Audio src={staticFile(scene.audioFile)} />}

            {footageSrc ? (
              <Video
                src={footageSrc}
                muted
                style={{
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                }}
              />
            ) : (
              <FallbackPlateScene scene={scene} ratio={ratio} theme={theme} cfg={cfg} />
            )}
          </Sequence>
        );
      })}

      {/* Captions Plate Layer: Burned in on solid plate with active-word highlight */}
      {activeSegment && (
        <div
          style={{
            position: 'absolute',
            left: '50%',
            bottom: `${cfg.captionBottom * 100}%`,
            transform: 'translateX(-50%)',
            maxWidth: `${cfg.captionMaxW * 100}%`,
            backgroundColor: theme.surface,
            border: `2px solid ${theme.line}`,
            borderRadius: '8px',
            padding: '16px 28px',
            color: theme.ink,
            fontFamily: FONTS.sans,
            fontSize: `${cfg.captionSize}px`,
            fontWeight: 600,
            lineHeight: 1.25,
            textAlign: 'center',
            zIndex: 10,
          }}
        >
          {activeWords.length > 0 ? (
            activeWords.map((w, idx) => {
              const isWordActive = frame >= w.startFrame && frame <= w.endFrame;
              return (
                <span
                  key={idx}
                  style={{
                    color: isWordActive ? theme.accent : theme.ink,
                    marginRight: idx === activeWords.length - 1 ? 0 : '8px',
                  }}
                >
                  {w.word}
                </span>
              );
            })
          ) : (
            // No fabricated word timestamps: render full phrase in theme.ink
            <span>{activeSegment.text}</span>
          )}
        </div>
      )}
    </div>
  );
};
