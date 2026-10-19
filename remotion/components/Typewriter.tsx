import React from 'react';
import { useCurrentFrame } from 'remotion';
import { C, FONTS } from '../theme';

interface TypewriterProps {
  text: string;
  speed?: number; // characters per frame
  startFrame?: number;
  showPrompt?: boolean;
  fontSize?: number;
}

export const Typewriter: React.FC<TypewriterProps> = ({
  text,
  speed = 1.4,
  startFrame = 0,
  showPrompt = true,
  fontSize = 24,
}) => {
  const frame = useCurrentFrame();
  const elapsed = Math.max(0, frame - startFrame);
  const charsToShow = Math.min(text.length, Math.floor(elapsed * speed));
  const currentText = text.slice(0, charsToShow);

  // Binary on/off cursor blink every 15 frames (no smooth alpha fade)
  const cursorVisible = Math.floor(frame / 15) % 2 === 0;

  // Highlight CLI flags (-f, --arch, etc.) in C.accent
  const renderHighlightedText = (content: string) => {
    const tokens = content.split(' ');
    return tokens.map((token, i) => {
      const isFlag = token.startsWith('-') || token.startsWith('--');
      return (
        <span
          key={i}
          style={{
            color: isFlag ? C.accent : C.text,
            marginRight: i === tokens.length - 1 ? '0' : '8px',
          }}
        >
          {token}
        </span>
      );
    });
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        fontFamily: FONTS.mono,
        fontSize: `${fontSize}px`,
        lineHeight: 1.4,
      }}
    >
      {showPrompt && (
        <span style={{ color: C.muted, marginRight: '12px', userSelect: 'none' }}>
          $
        </span>
      )}
      <span>{renderHighlightedText(currentText)}</span>
      <span
        style={{
          display: 'inline-block',
          width: '10px',
          height: `${fontSize}px`,
          backgroundColor: cursorVisible ? C.accent : 'transparent',
          marginLeft: '4px',
          verticalAlign: 'middle',
        }}
      />
    </div>
  );
};
