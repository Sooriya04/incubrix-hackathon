import React from 'react';
import { interpolate, useCurrentFrame } from 'remotion';
import { C } from '../theme';

interface CrossProps {
  size?: number;
  strokeWidth?: number;
  color?: string;
  delayFrames?: number;
}

export const Cross: React.FC<CrossProps> = ({
  size = 28,
  strokeWidth = 3,
  color = C.danger,
  delayFrames = 0,
}) => {
  const frame = useCurrentFrame();
  const elapsed = Math.max(0, frame - delayFrames);

  // Draws "" mark with strokeDashoffset over 8 frames
  const progress = interpolate(elapsed, [0, 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const pathLength = 40;
  const strokeDashoffset = pathLength * (1 - progress);

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      style={{ display: 'inline-block', verticalAlign: 'middle' }}
    >
      <line
        x1="6"
        y1="6"
        x2="26"
        y2="26"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={pathLength}
        strokeDashoffset={strokeDashoffset}
      />
      <line
        x1="26"
        y1="6"
        x2="6"
        y2="26"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={pathLength}
        strokeDashoffset={strokeDashoffset}
      />
    </svg>
  );
};
