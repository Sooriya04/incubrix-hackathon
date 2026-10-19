import React from 'react';
import { Easing, interpolate, useCurrentFrame } from 'remotion';
import { C, FONTS } from '../theme';

interface CounterProps {
  from?: number;
  to: number;
  suffix?: string;
  prefix?: string;
  durationInFrames?: number;
  fontSize?: number;
  label?: string;
}

export const Counter: React.FC<CounterProps> = ({
  from = 0,
  to,
  suffix = '',
  prefix = '',
  durationInFrames = 30,
  fontSize = 72,
  label,
}) => {
  const frame = useCurrentFrame();

  const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

  const currentValue = Math.round(from + progress * (to - from));

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: FONTS.sans,
      }}
    >
      <div
        style={{
          fontSize: `${fontSize}px`,
          fontWeight: 700,
          color: C.accent,
          lineHeight: 1.0,
          fontFamily: FONTS.mono,
        }}
      >
        {prefix}
        {currentValue}
        {suffix}
      </div>
      {label && (
        <div
          style={{
            fontSize: `${Math.round(fontSize * 0.32)}px`,
            color: C.muted,
            marginTop: '8px',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            fontWeight: 600,
          }}
        >
          {label}
        </div>
      )}
    </div>
  );
};
