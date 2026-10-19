import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { C, FONTS, SPRINGS } from '../theme';

interface TerminalProps {
  title?: string;
  width?: string | number;
  maxWidth?: string | number;
  children: React.ReactNode;
}

export const Terminal: React.FC<TerminalProps> = ({
  title = 'bash',
  width = '100%',
  maxWidth = '1000px',
  children,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Rigid spring entrance with zero overshoot bounce
  const enterProgress = spring({
    frame,
    fps,
    config: SPRINGS.rigid,
  });

  const opacity = interpolate(enterProgress, [0, 1], [0, 1]);
  const translateY = interpolate(enterProgress, [0, 1], [24, 0]);

  return (
    <div
      style={{
        width,
        maxWidth,
        backgroundColor: C.surface,
        border: `2px solid ${C.line}`,
        borderRadius: '12px',
        overflow: 'hidden',
        opacity,
        transform: `translateY(${translateY}px)`,
        fontFamily: FONTS.mono,
      }}
    >
      {/* Title bar with neutral mono dots (strictly no macOS red/yellow/green) */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 18px',
          borderBottom: `2px solid ${C.line}`,
          backgroundColor: C.surface,
        }}
      >
        <div style={{ display: 'flex', gap: '8px' }}>
          <div
            style={{
              width: '10px',
              height: '10px',
              borderRadius: '50%',
              backgroundColor: C.line,
            }}
          />
          <div
            style={{
              width: '10px',
              height: '10px',
              borderRadius: '50%',
              backgroundColor: C.line,
            }}
          />
          <div
            style={{
              width: '10px',
              height: '10px',
              borderRadius: '50%',
              backgroundColor: C.line,
            }}
          />
        </div>
        <div
          style={{
            fontSize: '14px',
            color: C.muted,
            fontWeight: 500,
            letterSpacing: '0.04em',
          }}
        >
          {title}
        </div>
        <div style={{ width: '46px' }} />
      </div>

      {/* Terminal body */}
      <div style={{ padding: '24px 28px', color: C.text }}>{children}</div>
    </div>
  );
};
